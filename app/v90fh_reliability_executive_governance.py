from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception as exc: raise HTTPException(400,'period_key must be YYYY-MM') from exc

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def ensure_v90fh_schema(e):
    with e.begin() as c:
        stmts=[
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_governance_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            action_count INTEGER NOT NULL DEFAULT 0, open_action_count INTEGER NOT NULL DEFAULT 0,
            overdue_action_count INTEGER NOT NULL DEFAULT 0, high_priority_open_count INTEGER NOT NULL DEFAULT 0,
            evidence_gap_count INTEGER NOT NULL DEFAULT 0, effective_action_count INTEGER NOT NULL DEFAULT 0,
            ineffective_action_count INTEGER NOT NULL DEFAULT 0, governance_score NUMERIC NOT NULL DEFAULT 0,
            assessment TEXT NOT NULL DEFAULT 'NO_BASELINE', status TEXT NOT NULL DEFAULT 'OPEN',
            recommendation TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_governance_escalation(
            escalation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            action_id TEXT NOT NULL, escalation_level TEXT NOT NULL, reason TEXT NOT NULL, owner_user_id TEXT,
            due_date DATE, status TEXT NOT NULL DEFAULT 'OPEN', resolution_note TEXT, evidence_note TEXT,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolved_by TEXT, resolved_at TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_governance_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            action_count INTEGER NOT NULL DEFAULT 0, open_escalation_count INTEGER NOT NULL DEFAULT 0,
            closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_rel_exec_gov_scope ON maintenance_reliability_executive_governance_snapshot(organization_id,entity_id,period_key,status)',
        'CREATE INDEX IF NOT EXISTS ix_rel_exec_gov_esc ON maintenance_reliability_executive_governance_escalation(organization_id,entity_id,period_key,status,escalation_level)']
        for s in stmts: c.execute(text(s))
        for p,n in [('maintenance_reliability_governance.view','View Reliability Executive Governance'),('maintenance_reliability_governance.manage','Manage Reliability Executive Escalations'),('maintenance_reliability_governance.close','Close Reliability Executive Governance Period')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})

def _snapshot(e,o,ei,p,u):
    today=date.today().isoformat()
    with e.connect() as c:
        actions=c.execute(text("SELECT * FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        reviews=c.execute(text("SELECT action_id,assessment,evidence_note FROM maintenance_reliability_executive_effectiveness_review WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        esc=c.execute(text("SELECT action_id FROM maintenance_reliability_executive_governance_escalation WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':p}).mappings().all()
    reviewed={r['action_id']:r for r in reviews}; escalated={r['action_id'] for r in esc}
    total=len(actions); open_actions=sum(1 for a in actions if a['status'] not in ('COMPLETED','CANCELLED','REJECTED'))
    overdue=sum(1 for a in actions if a['status'] not in ('COMPLETED','CANCELLED','REJECTED') and a['due_date'] and str(a['due_date'])<today)
    high=sum(1 for a in actions if a['status'] not in ('COMPLETED','CANCELLED','REJECTED') and str(a.get('priority','')).upper() in ('HIGH','CRITICAL'))
    evidence=sum(1 for a in actions if a['action_id'] in reviewed and not (reviewed[a['action_id']].get('evidence_note') or '').strip())
    effective=sum(1 for r in reviews if r['assessment']=='EFFECTIVE'); ineffective=sum(1 for r in reviews if r['assessment']=='INEFFECTIVE')
    # Governance score is a transparent control score, not a causal business-performance measure.
    score=max(Decimal('0'),min(Decimal('100'),Decimal('100')-Decimal(min(overdue,5))*10-Decimal(min(high,5))*5-Decimal(min(evidence,5))*5-Decimal(min(ineffective,5))*7))
    assessment='COMPLIANT' if score>=90 and not overdue and not high and not evidence else ('WATCH' if score>=75 else ('AT_RISK' if total else 'NO_BASELINE'))
    rec='Maintain executive governance controls and monitor escalations.' if assessment=='COMPLIANT' else ('Resolve overdue/high-priority/evidence gaps before period closure.' if assessment!='NO_BASELINE' else 'Generate executive actions and establish accountable owners.')
    vals={'id':str(uuid4()),'o':o,'e':ei,'p':p,'ac':total,'op':open_actions,'ov':overdue,'hi':high,'eg':evidence,'ef':effective,'ine':ineffective,'gs':float(score),'a':assessment,'r':rec,'u':str(u.user_id)}
    with e.begin() as c:
        c.execute(text('''INSERT INTO maintenance_reliability_executive_governance_snapshot(snapshot_id,organization_id,entity_id,period_key,action_count,open_action_count,overdue_action_count,high_priority_open_count,evidence_gap_count,effective_action_count,ineffective_action_count,governance_score,assessment,status,recommendation,created_by) VALUES(:id,:o,:e,:p,:ac,:op,:ov,:hi,:eg,:ef,:ine,:gs,:a,'OPEN',:r,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET action_count=:ac,open_action_count=:op,overdue_action_count=:ov,high_priority_open_count=:hi,evidence_gap_count=:eg,effective_action_count=:ef,ineffective_action_count=:ine,governance_score=:gs,assessment=:a,status='OPEN',recommendation=:r,created_by=:u,created_at=CURRENT_TIMESTAMP'''),vals)
        row=c.execute(text('SELECT * FROM maintenance_reliability_executive_governance_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).mappings().first()
    return dict(row)

def register_v90fh_routes(app:FastAPI,e):
    ensure_v90fh_schema(e)
    @app.post('/v90fh/maintenance/reliability-governance/snapshot')
    def snapshot(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance.manage'); o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not o or not ei or not p: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        _valid(p); return {'snapshot':_snapshot(e,o,ei,p,u),'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fh/maintenance/reliability-governance/dashboard')
    def dashboard(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_governance.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_executive_governance_snapshot WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY governance_score ASC,entity_id'),par).mappings().all()
            escq='SELECT * FROM maintenance_reliability_executive_governance_escalation WHERE organization_id=:o AND period_key=:p AND status=\'OPEN\' ORDER BY CASE escalation_level WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 ELSE 3 END,due_date'
            esc=c.execute(text(escq),{'o':organization_id,'p':period_key}).mappings().all()
        return {'organization_id':organization_id,'period_key':period_key,'entity_count':len(rows),'average_governance_score':float(_d(sum((_d(r['governance_score']) for r in rows),Decimal('0'))/len(rows))) if rows else 0,'rows':[dict(r) for r in rows],'open_escalations':[dict(x) for x in esc],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fh/maintenance/reliability-governance/escalations')
    def escalations(organization_id:str,period_key:str,request:Request,entity_id:str|None=None,status:str='OPEN'):
        _perm(e,request,'maintenance_reliability_governance.view'); _valid(period_key)
        q='SELECT * FROM maintenance_reliability_executive_governance_escalation WHERE organization_id=:o AND period_key=:p AND status=:s'; par={'o':organization_id,'p':period_key,'s':status.upper()}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        with e.connect() as c: rows=c.execute(text(q+' ORDER BY CASE escalation_level WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 ELSE 3 END,due_date'),par).mappings().all()
        return {'escalations':[dict(r) for r in rows]}
    @app.post('/v90fh/maintenance/reliability-governance/escalations')
    def create_escalation(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance.manage'); o,ei,p,aid=body.get('organization_id'),body.get('entity_id'),body.get('period_key'),body.get('action_id')
        if not all([o,ei,p,aid,body.get('reason'),body.get('escalation_level')]): raise HTTPException(400,'organization_id, entity_id, period_key, action_id, escalation_level and reason are required')
        _valid(p); level=str(body['escalation_level']).upper()
        if level not in ('CRITICAL','HIGH','MEDIUM'): raise HTTPException(400,'escalation_level must be CRITICAL, HIGH or MEDIUM')
        eid=str(uuid4())
        with e.begin() as c:
            exists=c.execute(text('SELECT action_id FROM maintenance_reliability_executive_action WHERE action_id=:a AND organization_id=:o AND entity_id=:e AND period_key=:p'),{'a':aid,'o':o,'e':ei,'p':p}).first()
            if not exists: raise HTTPException(404,'executive action not found in scope')
            c.execute(text('''INSERT INTO maintenance_reliability_executive_governance_escalation(escalation_id,organization_id,entity_id,period_key,action_id,escalation_level,reason,owner_user_id,due_date,created_by) VALUES(:id,:o,:e,:p,:a,:l,:r,:owner,:due,:u)'''),{'id':eid,'o':o,'e':ei,'p':p,'a':aid,'l':level,'r':body['reason'],'owner':body.get('owner_user_id'),'due':body.get('due_date'),'u':str(u.user_id)})
            row=c.execute(text('SELECT * FROM maintenance_reliability_executive_governance_escalation WHERE escalation_id=:id'),{'id':eid}).mappings().first()
        return {'escalation':dict(row),'automatic_operational_mutation':False}
    @app.post('/v90fh/maintenance/reliability-governance/escalations/{escalation_id}/resolve')
    def resolve(escalation_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance.manage')
        if not (body.get('resolution_note') or '').strip() or not (body.get('evidence_note') or '').strip(): raise HTTPException(400,'resolution_note and evidence_note are required')
        with e.begin() as c:
            row=c.execute(text('SELECT * FROM maintenance_reliability_executive_governance_escalation WHERE escalation_id=:id'),{'id':escalation_id}).mappings().first()
            if not row: raise HTTPException(404,'escalation not found')
            c.execute(text("UPDATE maintenance_reliability_executive_governance_escalation SET status='RESOLVED',resolution_note=:r,evidence_note=:ev,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE escalation_id=:id"),{'r':body['resolution_note'],'ev':body['evidence_note'],'u':str(u.user_id),'id':escalation_id})
        return {'escalation_id':escalation_id,'status':'RESOLVED'}
    @app.post('/v90fh/maintenance/reliability-governance/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance.close'); _valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.connect() as c:
            total=c.execute(text('SELECT COUNT(*) FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar_one()
            openesc=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_governance_escalation WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':period_key}).scalar_one()
        if openesc and not body.get('force'): raise HTTPException(409,f'cannot close: {openesc} open governance escalation(s)')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_executive_governance_close(close_id,organization_id,entity_id,period_key,action_count,open_escalation_count,closed_by,closure_note) VALUES(:id,:o,:e,:p,:a,:x,:u,:n) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET action_count=:a,open_escalation_count=:x,closed_by=:u,closure_note=:n,closed_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'o':o,'e':ei,'p':period_key,'a':int(total),'x':int(openesc),'u':str(u.user_id),'n':body.get('closure_note')})
            c.execute(text("UPDATE maintenance_reliability_executive_governance_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key})
        return {'organization_id':o,'entity_id':ei,'period_key':period_key,'status':'CLOSED','open_escalation_count':int(openesc),'forced':bool(body.get('force'))}
    @app.get('/ui/maintenance-reliability-governance')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-governance.html')
