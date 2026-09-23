from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(engine, request, permission):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _valid(pk: str):
    try:
        y, m = map(int, pk.split('-'))
        if y < 2000 or not 1 <= m <= 12:
            raise ValueError
    except Exception as exc:
        raise HTTPException(400, 'period_key must be YYYY-MM') from exc


def ensure_v90fd_schema(engine):
    stmts = [
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_audit_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL, capa_open_count INTEGER NOT NULL DEFAULT 0,
            capa_overdue_count INTEGER NOT NULL DEFAULT 0, capa_evidence_gap_count INTEGER NOT NULL DEFAULT 0,
            approval_gap_count INTEGER NOT NULL DEFAULT 0, unauthorized_change_count INTEGER NOT NULL DEFAULT 0,
            standard_adoption_gap_count INTEGER NOT NULL DEFAULT 0, open_exception_count INTEGER NOT NULL DEFAULT 0,
            compliance_score NUMERIC NOT NULL DEFAULT 0, assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_audit_exception(
            exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL, exception_type TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM',
            object_type TEXT NOT NULL, object_id TEXT NOT NULL, finding TEXT NOT NULL,
            required_action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            evidence_note TEXT, resolved_by TEXT, resolved_at TIMESTAMP, resolution_note TEXT,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_audit_event(
            audit_event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL, event_type TEXT NOT NULL, object_type TEXT NOT NULL,
            object_id TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'INFO', detail TEXT NOT NULL,
            actor_user_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        'CREATE INDEX IF NOT EXISTS ix_reliability_audit_exception_queue ON maintenance_reliability_audit_exception(organization_id,entity_id,period_key,status,severity)',
        'CREATE INDEX IF NOT EXISTS ix_reliability_audit_event_scope ON maintenance_reliability_audit_event(organization_id,entity_id,period_key,event_type)',
    ]
    with engine.begin() as c:
        for s in stmts:
            c.execute(text(s))
        perms = {
            'maintenance_reliability_audit.view': 'View Reliability Audit and Compliance',
            'maintenance_reliability_audit.manage': 'Manage Reliability Audit Exceptions',
            'maintenance_reliability_audit.close': 'Close Reliability Audit Period',
        }
        for p, n in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p': p, 'n': n})


def _scan(engine, organization_id: str, entity_id: str, period_key: str, actor: str):
    findings = []
    with engine.connect() as c:
        capas = c.execute(text('''SELECT * FROM quality_capa WHERE organization_id=:o AND entity_id=:e
            AND CAST(created_at AS TEXT) LIKE :p'''), {'o': organization_id, 'e': entity_id, 'p': period_key + '%'}).mappings().all()
        for r in capas:
            if r['status'] == 'OPEN' and r['due_date'] is not None:
                overdue = c.execute(text('SELECT CASE WHEN :d < CURRENT_DATE THEN 1 ELSE 0 END'), {'d': r['due_date']}).scalar()
                if overdue:
                    findings.append(('OVERDUE_CAPA','HIGH','quality_capa',r['capa_id'],'CAPA is overdue while still OPEN','Assign/complete corrective action or formally rebaseline with evidence.'))
            eff = c.execute(text('SELECT COUNT(*) FROM capa_effectiveness WHERE capa_id=:i'), {'i': r['capa_id']}).scalar() or 0
            if not eff:
                sev = 'HIGH' if r['status'] == 'CLOSED' else 'MEDIUM'
                finding = 'Closed CAPA has no effectiveness verification record' if r['status'] == 'CLOSED' else 'CAPA has no effectiveness verification evidence yet'
                findings.append(('CAPA_EVIDENCE_GAP',sev,'quality_capa',r['capa_id'],finding,'Record documented effectiveness evidence before closure or compliance sign-off.'))
        # Governance approval integrity: implementations must reference an approved proposal.
        impls = c.execute(text('''SELECT i.*, p.status proposal_status FROM maintenance_reliability_change_implementation i
            LEFT JOIN maintenance_reliability_change_proposal p ON p.proposal_id=i.proposal_id
            WHERE i.organization_id=:o AND i.entity_id=:e AND i.period_key=:p'''), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        for r in impls:
            if r['proposal_status'] != 'APPROVED':
                findings.append(('APPROVAL_GAP','CRITICAL','change_implementation',r['implementation_id'],'Reliability change implementation is not backed by an APPROVED governance proposal','Stop/hold the change and reconcile governance approval evidence.'))
        revs = c.execute(text('''SELECT * FROM maintenance_reliability_plan_change_revision
            WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('IMPLEMENTED','APPROVED')'''), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        for r in revs:
            if r['status'] == 'IMPLEMENTED' and (not r['approved_by'] or not r['approved_at']):
                findings.append(('UNAUTHORIZED_CHANGE','CRITICAL','plan_change_revision',r['revision_id'],'Plan change revision is marked IMPLEMENTED without approval evidence','Reconcile approval record and operational implementation evidence; do not infer authorization from status alone.'))
        deployments = c.execute(text('''SELECT * FROM maintenance_reliability_standard_deployment
            WHERE organization_id=:o AND entity_id=:e AND period_key=:p'''), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        for r in deployments:
            if r['status'] == 'ACTIVE' and not r['deployed_by']:
                findings.append(('APPROVAL_GAP','HIGH','standard_deployment',r['deployment_id'],'Active standard deployment has no deployment actor recorded','Reconcile activation evidence and responsible approver/operator.'))
            if r['status'] == 'ACTIVE' and float(r['adoption_pct'] or 0) < 100:
                findings.append(('STANDARD_ADOPTION_GAP','MEDIUM','standard_deployment',r['deployment_id'],f"Active standard adoption is {float(r['adoption_pct'] or 0):.2f}%",'Complete acknowledgement or document approved exceptions and evidence.'))
        # CAPA evidence gap for reliability CAPAs created by V90.fc.
        links = c.execute(text('''SELECT l.capa_id,l.trigger_type,l.benchmark_id FROM maintenance_reliability_capa_link l
            WHERE l.organization_id=:o AND l.entity_id=:e AND l.period_key=:p'''), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        for r in links:
            ev = c.execute(text('SELECT COUNT(*) FROM capa_effectiveness WHERE capa_id=:i'), {'i':r['capa_id']}).scalar() or 0
            if not ev:
                findings.append(('CAPA_EVIDENCE_GAP','MEDIUM','reliability_capa',r['capa_id'],'Reliability CAPA has no effectiveness evidence yet','Record effectiveness verification before closure.'))
    with engine.begin() as c:
        for typ, sev, objt, objid, detail, action in findings:
            existing = c.execute(text('''SELECT exception_id FROM maintenance_reliability_audit_exception
                WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND exception_type=:t AND object_type=:ot AND object_id=:oi AND status='OPEN' LIMIT 1'''),
                {'o':organization_id,'e':entity_id,'p':period_key,'t':typ,'ot':objt,'oi':objid}).scalar()
            if not existing:
                c.execute(text('''INSERT INTO maintenance_reliability_audit_exception(exception_id,organization_id,entity_id,period_key,exception_type,severity,object_type,object_id,finding,required_action,created_by)
                    VALUES(:i,:o,:e,:p,:t,:s,:ot,:oi,:f,:a,:u)'''), {'i':str(uuid4()),'o':organization_id,'e':entity_id,'p':period_key,'t':typ,'s':sev,'ot':objt,'oi':objid,'f':detail,'a':action,'u':actor})
            c.execute(text('''INSERT INTO maintenance_reliability_audit_event(audit_event_id,organization_id,entity_id,period_key,event_type,object_type,object_id,severity,detail,actor_user_id)
                VALUES(:i,:o,:e,:p,:t,:ot,:oi,:s,:d,:u)'''), {'i':str(uuid4()),'o':organization_id,'e':entity_id,'p':period_key,'t':typ,'ot':objt,'oi':objid,'s':sev,'d':detail,'u':actor})
    return findings


def register_v90fd_routes(app: FastAPI, engine):
    ensure_v90fd_schema(engine)

    @app.post('/v90fd/maintenance/reliability-audit/snapshot')
    def snapshot(body: dict, request: Request):
        u = _perm(engine, request, 'maintenance_reliability_audit.manage')
        o, e, p = body.get('organization_id'), body.get('entity_id'), body.get('period_key')
        if not o or not e or not p: raise HTTPException(400, 'organization_id, entity_id and period_key are required')
        _valid(p)
        findings = _scan(engine, str(o), str(e), p, str(u.user_id))
        with engine.begin() as c:
            open_capa = c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"), {'o':o,'e':e}).scalar() or 0
            overdue = c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN' AND due_date IS NOT NULL AND due_date<CURRENT_DATE"), {'o':o,'e':e}).scalar() or 0
            capa_gap = c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND exception_type='CAPA_EVIDENCE_GAP' AND status='OPEN'"), {'o':o,'e':e,'p':p}).scalar() or 0
            approval_gap = c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND exception_type='APPROVAL_GAP' AND status='OPEN'"), {'o':o,'e':e,'p':p}).scalar() or 0
            unauthorized = c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND exception_type='UNAUTHORIZED_CHANGE' AND status='OPEN'"), {'o':o,'e':e,'p':p}).scalar() or 0
            adoption = c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND exception_type='STANDARD_ADOPTION_GAP' AND status='OPEN'"), {'o':o,'e':e,'p':p}).scalar() or 0
            open_exc = c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"), {'o':o,'e':e,'p':p}).scalar() or 0
            score = max(0, min(100, 100 - overdue*15 - capa_gap*10 - approval_gap*20 - unauthorized*30 - adoption*5 - max(0, open_exc-capa_gap-approval_gap-unauthorized-adoption)*5))
            assessment = 'COMPLIANT' if score >= 90 and open_exc == 0 else ('WATCH' if score >= 75 else 'AT_RISK')
            sid = str(uuid4())
            c.execute(text('''INSERT INTO maintenance_reliability_audit_snapshot(snapshot_id,organization_id,entity_id,period_key,capa_open_count,capa_overdue_count,capa_evidence_gap_count,approval_gap_count,unauthorized_change_count,standard_adoption_gap_count,open_exception_count,compliance_score,assessment,created_by)
                VALUES(:i,:o,:e,:p,:co,:ov,:cg,:ag,:uc,:sg,:oe,:sc,:a,:u)
                ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET capa_open_count=:co,capa_overdue_count=:ov,capa_evidence_gap_count=:cg,approval_gap_count=:ag,unauthorized_change_count=:uc,standard_adoption_gap_count=:sg,open_exception_count=:oe,compliance_score=:sc,assessment=:a,created_by=:u,created_at=CURRENT_TIMESTAMP'''), {'i':sid,'o':o,'e':e,'p':p,'co':int(open_capa),'ov':int(overdue),'cg':int(capa_gap),'ag':int(approval_gap),'uc':int(unauthorized),'sg':int(adoption),'oe':int(open_exc),'sc':round(score,2),'a':assessment,'u':str(u.user_id)})
            row = c.execute(text('SELECT * FROM maintenance_reliability_audit_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'), {'o':o,'e':e,'p':p}).mappings().first()
        return {'snapshot':dict(row),'finding_count':len(findings),'unauthorized_change_detection':'workflow-integrity checks; not a database write interceptor'}

    @app.get('/v90fd/maintenance/reliability-audit/dashboard')
    def dashboard(organization_id: str, entity_id: str, period_key: str, request: Request):
        _perm(engine, request, 'maintenance_reliability_audit.view'); _valid(period_key)
        with engine.connect() as c:
            s = c.execute(text('SELECT * FROM maintenance_reliability_audit_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().first()
            x = c.execute(text("SELECT * FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN' ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END,created_at DESC"), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'snapshot':dict(s) if s else None,'open_exceptions':[dict(r) for r in x],'audit_scope':'reliability governance, CAPA, controlled standards, approvals, evidence'}

    @app.get('/v90fd/maintenance/reliability-audit/exceptions')
    def exceptions(organization_id: str, entity_id: str, period_key: str, request: Request, status: str = 'OPEN'):
        _perm(engine, request, 'maintenance_reliability_audit.view'); _valid(period_key)
        with engine.connect() as c:
            rows = c.execute(text('SELECT * FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status=:s ORDER BY created_at DESC'), {'o':organization_id,'e':entity_id,'p':period_key,'s':status.upper()}).mappings().all()
        return {'count':len(rows),'exceptions':[dict(r) for r in rows]}

    @app.post('/v90fd/maintenance/reliability-audit/exceptions/{exception_id}/resolve')
    def resolve(exception_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'maintenance_reliability_audit.manage')
        note = str(body.get('resolution_note') or '').strip()
        evidence = str(body.get('evidence_note') or '').strip()
        if not note or not evidence: raise HTTPException(400, 'resolution_note and evidence_note are required')
        with engine.begin() as c:
            x = c.execute(text('SELECT * FROM maintenance_reliability_audit_exception WHERE exception_id=:i'), {'i':exception_id}).mappings().first()
            if not x: raise HTTPException(404, 'audit exception not found')
            c.execute(text("UPDATE maintenance_reliability_audit_exception SET status='RESOLVED',evidence_note=:e,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP,resolution_note=:n WHERE exception_id=:i"), {'e':evidence,'u':str(u.user_id),'n':note,'i':exception_id})
        return {'exception_id':exception_id,'status':'RESOLVED','evidence_recorded':True}

    @app.post('/v90fd/maintenance/reliability-audit/{period_key}/close')
    def close(period_key: str, body: dict, request: Request):
        u = _perm(engine, request, 'maintenance_reliability_audit.close'); _valid(period_key)
        o, e = body.get('organization_id'), body.get('entity_id')
        if not o or not e: raise HTTPException(400, 'organization_id and entity_id are required')
        with engine.begin() as c:
            critical = c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN' AND severity='CRITICAL'"), {'o':o,'e':e,'p':period_key}).scalar() or 0
            open_n = c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"), {'o':o,'e':e,'p':period_key}).scalar() or 0
            if (critical or open_n) and not bool(body.get('force',False)):
                raise HTTPException(409, f'open audit exceptions={open_n}, critical={critical}; resolve or force close')
        return {'organization_id':o,'entity_id':e,'period_key':period_key,'status':'CLOSED','forced':bool(body.get('force',False)),'closed_by':str(u.user_id),'note':'Audit closure is a control acknowledgement; it does not erase exception history.'}

    @app.get('/ui/maintenance-reliability-audit')
    def ui():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'maintenance-reliability-audit.html')
