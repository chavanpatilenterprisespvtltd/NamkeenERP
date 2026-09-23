from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _perm(e, r, p):
    u = authenticate(r); ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403, 'permission denied')
    return u

def _valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception as exc: raise HTTPException(400,'period_key must be YYYY-MM') from exc

def ensure_v90fe_schema(e):
    with e.begin() as c:
        stmts=[
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_command_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            reliability_score NUMERIC NOT NULL DEFAULT 0, maintenance_cost NUMERIC NOT NULL DEFAULT 0,
            breakdown_hours NUMERIC NOT NULL DEFAULT 0, oee_pct NUMERIC NOT NULL DEFAULT 0,
            effectiveness_score NUMERIC NOT NULL DEFAULT 0, target_met_pct NUMERIC NOT NULL DEFAULT 0,
            standard_adoption_pct NUMERIC NOT NULL DEFAULT 0, capa_open_count INTEGER NOT NULL DEFAULT 0,
            capa_overdue_count INTEGER NOT NULL DEFAULT 0, capa_ineffective_count INTEGER NOT NULL DEFAULT 0,
            benchmark_exception_count INTEGER NOT NULL DEFAULT 0, audit_open_exception_count INTEGER NOT NULL DEFAULT 0,
            audit_compliance_score NUMERIC NOT NULL DEFAULT 0, control_score NUMERIC NOT NULL DEFAULT 0,
            executive_health_score NUMERIC NOT NULL DEFAULT 0, assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',
            status TEXT NOT NULL DEFAULT 'OPEN', recommendation TEXT, created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_command_exception(
            exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            exception_type TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'MEDIUM', source_type TEXT NOT NULL,
            source_id TEXT, title TEXT NOT NULL, detail TEXT NOT NULL, required_action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN', resolution_note TEXT, evidence_note TEXT,
            resolved_by TEXT, resolved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_command_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED', health_score NUMERIC NOT NULL DEFAULT 0,
            unresolved_exception_count INTEGER NOT NULL DEFAULT 0, closed_by TEXT NOT NULL,
            closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_reliability_command_scope ON maintenance_reliability_executive_command_snapshot(organization_id,entity_id,period_key,status)',
        'CREATE INDEX IF NOT EXISTS ix_reliability_command_exception ON maintenance_reliability_executive_command_exception(organization_id,entity_id,period_key,status,severity)']
        for s in stmts: c.execute(text(s))
        for p,n in [('maintenance_reliability_command.view','View Reliability Executive Command Center'),('maintenance_reliability_command.manage','Manage Reliability Executive Exceptions'),('maintenance_reliability_command.close','Close Reliability Executive Period')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})

def _latest(c, table, o, e, p):
    return c.execute(text(f'SELECT * FROM {table} WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC LIMIT 1'),{'o':o,'e':e,'p':p}).mappings().first()

def _num(r,k): return _d(r[k] if r and k in r else 0)

def _snapshot(e,o,ei,p,u):
    with e.connect() as c:
        audit=_latest(c,'maintenance_reliability_audit_snapshot',o,ei,p)
        control=_latest(c,'maintenance_reliability_executive_control_snapshot',o,ei,p)
        capa=_latest(c,'maintenance_reliability_capa_snapshot',o,ei,p)
        cost=_latest(c,'maintenance_reliability_cost_snapshot',o,ei,p)
        eff=c.execute(text("SELECT COALESCE(AVG(actual_effectiveness_score),0),COALESCE(AVG(target_met_pct),0) FROM maintenance_reliability_change_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).first()
        adoption=c.execute(text("SELECT COALESCE(AVG(adoption_pct),0) FROM maintenance_reliability_standard_deployment WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='ACTIVE'"),{'o':o,'e':ei,'p':p}).scalar() or 0
        bex=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_benchmark_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':p}).scalar() or 0
        aex=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_audit_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':p}).scalar() or 0
        capopen=c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':o,'e':ei}).scalar() or 0
        capov=c.execute(text("SELECT COUNT(*) FROM quality_capa WHERE organization_id=:o AND entity_id=:e AND status='OPEN' AND due_date IS NOT NULL AND due_date<CURRENT_DATE"),{'o':o,'e':ei}).scalar() or 0
    effs=_d(eff[0]); target=_d(eff[1])*Decimal('100') if _d(eff[1])<=1 else _d(eff[1])
    control_score=_num(control,'control_score'); audit_score=_num(audit,'compliance_score')
    capa_score=_num(capa,'control_score')
    reliability=_num(cost,'reliability_score')
    adoption=_d(adoption)
    health=(audit_score*Decimal('.25')+control_score*Decimal('.20')+reliability*Decimal('.05')+effs*Decimal('.10')+target*Decimal('.10')+adoption*Decimal('.10')+capa_score*Decimal('.15')+max(Decimal('0'),Decimal('100')-Decimal(min(int(bex),20))*Decimal('5'))*Decimal('.05')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    health=max(Decimal('0'),min(Decimal('100'),health))
    assessment='HEALTHY' if health>=90 and not aex and not bex else ('WATCH' if health>=75 else 'AT_RISK')
    rec='Maintain controls and continue evidence-based reliability improvement.' if assessment=='HEALTHY' else ('Prioritize open executive exceptions and verify CAPA/benchmark/audit actions.' if assessment=='WATCH' else 'Escalate reliability, compliance, and operational-risk exceptions for management decision.')
    vals={'id':str(uuid4()),'o':o,'e':ei,'p':p,'rs':float(reliability),'mc':float(_num(cost,'total_maintenance_cost')),'dh':float(_num(cost,'breakdown_hours')),'oee':float(_num(cost,'oee_pct')),'eff':float(effs),'tm':float(target),'ad':float(adoption),'co':int(capopen),'ov':int(capov),'ci':int(_num(capa,'ineffective_capa_count')),'be':int(bex),'ae':int(aex),'as':float(audit_score),'cs':float(control_score),'hs':float(health),'a':assessment,'r':rec,'u':str(u.user_id)}
    with e.begin() as c:
        c.execute(text('''INSERT INTO maintenance_reliability_executive_command_snapshot(snapshot_id,organization_id,entity_id,period_key,reliability_score,maintenance_cost,breakdown_hours,oee_pct,effectiveness_score,target_met_pct,standard_adoption_pct,capa_open_count,capa_overdue_count,capa_ineffective_count,benchmark_exception_count,audit_open_exception_count,audit_compliance_score,control_score,executive_health_score,assessment,status,recommendation,created_by) VALUES(:id,:o,:e,:p,:rs,:mc,:dh,:oee,:eff,:tm,:ad,:co,:ov,:ci,:be,:ae,:as,:cs,:hs,:a,'OPEN',:r,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET reliability_score=:rs,maintenance_cost=:mc,breakdown_hours=:dh,oee_pct=:oee,effectiveness_score=:eff,target_met_pct=:tm,standard_adoption_pct=:ad,capa_open_count=:co,capa_overdue_count=:ov,capa_ineffective_count=:ci,benchmark_exception_count=:be,audit_open_exception_count=:ae,audit_compliance_score=:as,control_score=:cs,executive_health_score=:hs,assessment=:a,status='OPEN',recommendation=:r,created_by=:u,created_at=CURRENT_TIMESTAMP'''),vals)
        if aex:
            for typ,title,detail,action in [('AUDIT','Open reliability audit exceptions',f'{aex} open audit exception(s) remain.','Resolve audit exceptions with resolution and evidence.' )]:
                c.execute(text("INSERT INTO maintenance_reliability_executive_command_exception(exception_id,organization_id,entity_id,period_key,exception_type,severity,source_type,source_id,title,detail,required_action,created_by) SELECT :id,:o,:e,:p,:t,'CRITICAL','reliability_audit',NULL,:title,:detail,:act,:u WHERE NOT EXISTS (SELECT 1 FROM maintenance_reliability_executive_command_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND exception_type=:t AND status='OPEN')"),{'id':str(uuid4()),'o':o,'e':ei,'p':p,'t':typ,'title':title,'detail':detail,'act':action,'u':str(u.user_id)})
        if bex:
            c.execute(text("INSERT INTO maintenance_reliability_executive_command_exception(exception_id,organization_id,entity_id,period_key,exception_type,severity,source_type,title,detail,required_action,created_by) SELECT :id,:o,:e,:p,'BENCHMARK','HIGH','benchmark','Open benchmark exceptions',:detail,'Review peer gap and execute controlled improvement action.',:u WHERE NOT EXISTS (SELECT 1 FROM maintenance_reliability_executive_command_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND exception_type='BENCHMARK' AND status='OPEN')"),{'id':str(uuid4()),'o':o,'e':ei,'p':p,'detail':f'{bex} open benchmark exception(s) remain.','u':str(u.user_id)})
        row=c.execute(text('SELECT * FROM maintenance_reliability_executive_command_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).mappings().first()
    return dict(row)

def register_v90fe_routes(app:FastAPI,e):
    ensure_v90fe_schema(e)
    @app.post('/v90fe/maintenance/reliability-command/snapshot')
    def snapshot(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_command.manage'); o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not o or not ei or not p: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        _valid(p); row=_snapshot(e,o,ei,p,u)
        return {'snapshot':row,'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fe/maintenance/reliability-command/dashboard')
    def dashboard(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_command.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_executive_command_snapshot WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY executive_health_score ASC,entity_id'),par).mappings().all()
            ex=c.execute(text("SELECT * FROM maintenance_reliability_executive_command_exception WHERE organization_id=:o AND period_key=:p AND status='OPEN' ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END,created_at DESC"),{'o':organization_id,'p':period_key}).mappings().all()
        return {'organization_id':organization_id,'period_key':period_key,'entity_count':len(rows),'average_health_score':float(_d(sum((_d(r['executive_health_score']) for r in rows),Decimal('0'))/len(rows))) if rows else 0,'critical_count':sum(1 for r in rows if r['assessment']=='AT_RISK'),'rows':[dict(r) for r in rows],'open_exceptions':[dict(x) for x in ex],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fe/maintenance/reliability-command/exceptions')
    def exceptions(organization_id:str,period_key:str,request:Request,entity_id:str|None=None,status:str='OPEN'):
        _perm(e,request,'maintenance_reliability_command.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_executive_command_exception WHERE organization_id=:o AND period_key=:p AND status=:s'; par={'o':organization_id,'p':period_key,'s':status.upper()}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY created_at DESC'),par).mappings().all()
        return {'count':len(rows),'exceptions':[dict(x) for x in rows]}
    @app.post('/v90fe/maintenance/reliability-command/exceptions/{exception_id}/resolve')
    def resolve(exception_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_command.manage'); note=str(body.get('resolution_note') or '').strip(); evidence=str(body.get('evidence_note') or '').strip()
        if not note or not evidence: raise HTTPException(400,'resolution_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_executive_command_exception SET status='RESOLVED',resolution_note=:n,evidence_note=:ev,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE exception_id=:i AND status='OPEN' RETURNING exception_id"),{'n':note,'ev':evidence,'u':str(u.user_id),'i':exception_id}).first()
            if not r: raise HTTPException(404,'open executive exception not found')
        return {'exception_id':exception_id,'status':'RESOLVED','evidence_recorded':True}
    @app.post('/v90fe/maintenance/reliability-command/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_command.close'); _valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            ex=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_command_exception WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            if ex and not body.get('force'): raise HTTPException(409,f'{ex} open executive exception(s) remain; resolve or force=true')
            hs=c.execute(text('SELECT executive_health_score FROM maintenance_reliability_executive_command_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            c.execute(text('''INSERT INTO maintenance_reliability_executive_command_close(close_id,organization_id,entity_id,period_key,health_score,unresolved_exception_count,closed_by,closure_note) VALUES(:i,:o,:e,:p,:h,:x,:u,:n) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET health_score=:h,unresolved_exception_count=:x,closed_by=:u,closure_note=:n,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'h':float(hs),'x':int(ex),'u':str(u.user_id),'n':body.get('closure_note')})
            c.execute(text("UPDATE maintenance_reliability_executive_command_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key})
        return {'organization_id':o,'entity_id':ei,'period_key':period_key,'status':'CLOSED','health_score':float(hs),'unresolved_exception_count':int(ex),'forced':bool(body.get('force'))}
    @app.get('/ui/maintenance-reliability-command')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-command.html')
