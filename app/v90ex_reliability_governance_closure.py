from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def register_v90ex_routes(app:FastAPI,e):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_control_snapshot(
            control_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            effectiveness_score NUMERIC NOT NULL DEFAULT 0, target_met_pct NUMERIC NOT NULL DEFAULT 0,
            failed_change_count INTEGER NOT NULL DEFAULT 0, repeat_failure_count INTEGER NOT NULL DEFAULT 0,
            open_feedback_count INTEGER NOT NULL DEFAULT 0, critical_exception_count INTEGER NOT NULL DEFAULT 0,
            governance_score NUMERIC NOT NULL DEFAULT 0, control_score NUMERIC NOT NULL DEFAULT 0,
            assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED', recommendation TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_executive_control_scope ON maintenance_reliability_executive_control_snapshot(organization_id,entity_id,period_key,status,assessment)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_management_exception(
            exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            source_type TEXT NOT NULL, source_id TEXT, work_center_id TEXT, severity TEXT NOT NULL DEFAULT 'MEDIUM',
            title TEXT NOT NULL, rationale TEXT NOT NULL, recommended_action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN', owner_user_id TEXT, due_date DATE, resolution_note TEXT,
            resolved_by TEXT, resolved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,source_type,source_id))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_management_exception_scope ON maintenance_reliability_management_exception(organization_id,entity_id,period_key,status,severity)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_closure(
            closure_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED', closure_score NUMERIC NOT NULL DEFAULT 0,
            unresolved_exception_count INTEGER NOT NULL DEFAULT 0, closed_by TEXT NOT NULL,
            closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        for p,n in [('maintenance_reliability_executive_control.view','View Executive Reliability Control'),('maintenance_reliability_executive_control.manage','Manage Executive Reliability Control'),('maintenance_reliability_executive_control.resolve','Resolve Reliability Exceptions'),('maintenance_reliability_executive_control.close','Close Executive Reliability Governance')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

    @app.post('/v90ex/maintenance/reliability-governance/control/snapshot')
    def snapshot(body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_executive_control.manage')
        o,ei,pk=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not o or not ei or not pk: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        valid(pk)
        with e.begin() as c:
            if c.execute(text('SELECT 1 FROM maintenance_reliability_governance_closure WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
            rows=c.execute(text('SELECT * FROM maintenance_reliability_change_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).mappings().all()
            fb=c.execute(text("SELECT * FROM maintenance_reliability_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('PROPOSED','OPEN')"),{'o':o,'e':ei,'p':pk}).mappings().all()
            gov=c.execute(text('SELECT governance_score FROM maintenance_reliability_governance_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).scalar()
            critical=sum(1 for x in fb if str(x['priority']).upper()=='CRITICAL')
            # Promote ineffective changes into explicit management exceptions. This is advisory; no operational mutation occurs.
            for x in rows:
                if int(x['failure_flag'] or 0):
                    sev='CRITICAL' if int(x['repeat_failure_count'] or 0)>0 else 'HIGH'
                    title='Ineffective reliability change'
                    rationale=str(x['recommendation'] or 'Effectiveness target not met')
                    c.execute(text('''INSERT INTO maintenance_reliability_management_exception(exception_id,organization_id,entity_id,period_key,source_type,source_id,work_center_id,severity,title,rationale,recommended_action,status,created_by)
                        VALUES(:id,:o,:e,:p,'CHANGE_EFFECTIVENESS',:sid,:w,:s,:t,:r,:a,'OPEN',:u)
                        ON CONFLICT(organization_id,entity_id,period_key,source_type,source_id) DO UPDATE SET severity=:s,rationale=:r,recommended_action=:a,status='OPEN',created_by=:u'''),
                        {'id':str(uuid4()),'o':o,'e':ei,'p':pk,'sid':x['effectiveness_id'],'w':x['work_center_id'],'s':sev,'t':title,'r':rationale,'a':rationale,'u':str(u.user_id)})
            exc=c.execute(text("SELECT * FROM maintenance_reliability_management_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':pk}).mappings().all()
            critical=max(critical,sum(1 for x in exc if str(x['severity']).upper()=='CRITICAL'))
            target_pct=d(sum(Decimal(str(x['target_met'] or 0)) for x in rows)/len(rows)*100) if rows else d(0)
            eff=d(sum(Decimal(str(x['actual_effectiveness_score'] or 0)) for x in rows)/len(rows)) if rows else d(0)
            failed=sum(int(x['failure_flag'] or 0) for x in rows); repeat=sum(int(x['repeat_failure_count'] or 0) for x in rows); openfb=len(fb)
            gs=d(gov or 0)
            control=d(max(0,min(100, target_pct*Decimal('0.35') + eff*Decimal('0.35') + max(Decimal('0'),Decimal('100')-Decimal(critical)*Decimal('20'))*Decimal('0.20') + gs*Decimal('0.10'))))
            assessment='CONTROLLED' if control>=80 and critical==0 else ('ESCALATE' if critical>0 or failed>0 else 'REVIEW_REQUIRED')
            rec='Close period with evidence retained.' if assessment=='CONTROLLED' else ('Resolve critical exceptions and obtain governance decision.' if critical else 'Review failed changes and open improvement feedback before closure.')
            c.execute(text('''INSERT INTO maintenance_reliability_executive_control_snapshot(control_id,organization_id,entity_id,period_key,effectiveness_score,target_met_pct,failed_change_count,repeat_failure_count,open_feedback_count,critical_exception_count,governance_score,control_score,assessment,recommendation,status,created_by)
                VALUES(:id,:o,:e,:p,:eff,:tm,:fc,:rf,:fb,:ce,:gs,:cs,:a,:r,'OPEN',:u)
                ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET effectiveness_score=:eff,target_met_pct=:tm,failed_change_count=:fc,repeat_failure_count=:rf,open_feedback_count=:fb,critical_exception_count=:ce,governance_score=:gs,control_score=:cs,assessment=:a,recommendation=:r,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),
                {'id':str(uuid4()),'o':o,'e':ei,'p':pk,'eff':float(eff),'tm':float(target_pct),'fc':failed,'rf':repeat,'fb':openfb,'ce':critical,'gs':float(gs),'cs':float(control),'a':assessment,'r':rec,'u':str(u.user_id)})
        return {'period_key':pk,'control_score':float(control),'assessment':assessment,'failed_change_count':failed,'repeat_failure_count':repeat,'critical_exception_count':critical,'open_feedback_count':openfb,'causal_attribution':False}

    @app.get('/v90ex/maintenance/reliability-governance/control/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_executive_control.view'); valid(period_key)
        with e.connect() as c:
            s=c.execute(text('SELECT * FROM maintenance_reliability_executive_control_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().first()
            ex=c.execute(text('SELECT * FROM maintenance_reliability_management_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY CASE severity WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 WHEN \'MEDIUM\' THEN 3 ELSE 4 END,created_at'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
            cl=c.execute(text('SELECT * FROM maintenance_reliability_governance_closure WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().first()
        return {'snapshot':dict(s) if s else None,'exceptions':[dict(x) for x in ex],'closure':dict(cl) if cl else None,'causal_attribution':False}

    @app.get('/v90ex/maintenance/reliability-governance/control/trend')
    def trend(request:Request,organization_id:str,entity_id:str):
        perm(e,request,'maintenance_reliability_executive_control.view')
        with e.connect() as c:
            rows=c.execute(text('SELECT period_key,control_score,effectiveness_score,target_met_pct,failed_change_count,critical_exception_count,assessment FROM maintenance_reliability_executive_control_snapshot WHERE organization_id=:o AND entity_id=:e ORDER BY period_key'),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'count':len(rows),'trend':[dict(x) for x in rows],'causal_attribution':False}

    @app.get('/v90ex/maintenance/reliability-governance/control/exceptions')
    def exceptions(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_executive_control.view'); valid(period_key)
        with e.connect() as c:
            rows=c.execute(text('SELECT * FROM maintenance_reliability_management_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY CASE severity WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 WHEN \'MEDIUM\' THEN 3 ELSE 4 END,created_at'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'exceptions':[dict(x) for x in rows]}

    @app.post('/v90ex/maintenance/reliability-governance/control/exceptions/{exception_id}/resolve')
    def resolve(exception_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_executive_control.resolve')
        note=str(body.get('resolution_note') or '').strip()
        if not note: raise HTTPException(400,'resolution_note is required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_management_exception SET status='RESOLVED',resolution_note=:n,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP,owner_user_id=COALESCE(:o,owner_user_id) WHERE exception_id=:i AND status='OPEN' RETURNING exception_id"),{'n':note,'u':str(u.user_id),'o':body.get('owner_user_id'),'i':exception_id}).first()
            if not r: raise HTTPException(404,'open exception not found')
        return {'exception_id':exception_id,'status':'RESOLVED'}

    @app.post('/v90ex/maintenance/reliability-governance/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_executive_control.close'); valid(period_key)
        o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            ex=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_management_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            if ex and not bool(body.get('force')): raise HTTPException(409,f'{ex} open management exception(s) must be resolved or force=true')
            s=c.execute(text('SELECT control_score FROM maintenance_reliability_executive_control_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            c.execute(text('''INSERT INTO maintenance_reliability_governance_closure(closure_id,organization_id,entity_id,period_key,status,closure_score,unresolved_exception_count,closed_by,closure_note) VALUES(:i,:o,:e,:p,'CLOSED',:s,:x,:u,:n) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closure_score=:s,unresolved_exception_count=:x,closed_by=:u,closure_note=:n,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'s':float(s),'x':int(ex),'u':str(u.user_id),'n':body.get('closure_note')})
            c.execute(text("UPDATE maintenance_reliability_executive_control_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key})
        return {'period_key':period_key,'status':'CLOSED','unresolved_exception_count':int(ex),'closure_score':float(s)}

    @app.get('/ui/maintenance-reliability-governance-control')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-governance-control.html')
