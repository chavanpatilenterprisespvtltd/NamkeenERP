from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope

PERM_VIEW='performance.production_readiness.view'
PERM_MANAGE='performance.production_readiness.manage'
CHECKS=(
 ('PERFORMANCE_GATE','V90.ga performance production gate is certified and closed'),
 ('UAT_CERTIFICATION','V90.ft UAT production-readiness plan is certified'),
 ('DEPLOYMENT_CUTOVER','V90.fv deployment controls and rollback drill are ready'),
 ('BACKUP_DR','V90.fw backup, restore and DR readiness is green'),
 ('OBSERVABILITY','V90.fx operational health has all required checks healthy'),
 ('NO_CRITICAL_ALERTS','V90.fx has no open critical alerts or unresolved incidents'),
)

class GateIn(BaseModel):
    organization_id:str|None=None
    period_key:str=Field(min_length=4,max_length=40)
    release_version:str=Field(min_length=3,max_length=40)
    environment:str=Field(min_length=2,max_length=80)
    note:str=Field(min_length=1,max_length=3000)
class CheckIn(BaseModel):
    status:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED|OPEN)$')
    evidence_ref:str|None=None
    note:str=Field(min_length=1,max_length=3000)
class CertifyIn(BaseModel):
    evidence_ref:str=Field(min_length=1,max_length=500)
    note:str=Field(min_length=1,max_length=3000)
class CloseIn(BaseModel):
    evidence_ref:str=Field(min_length=1,max_length=500)
    note:str=Field(min_length=1,max_length=3000)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o):
    try: assert_security_scope(e,u.user_id,organization_id=o)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def _ev(status,ref):
    if status in ('PASS','WAIVED') and not ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')

def ensure_v90gb_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_perf_production_readiness_gate(gate_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,environment TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,certified_at TIMESTAMP NULL,certified_by TEXT NULL,certification_evidence_ref TEXT NULL,certification_note TEXT NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,close_evidence_ref TEXT NULL,close_note TEXT NULL,UNIQUE(organization_id,period_key,release_version,environment))''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_production_readiness_check(check_id TEXT PRIMARY KEY,gate_id TEXT NOT NULL,check_code TEXT NOT NULL,check_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(gate_id,check_code))''',
    'CREATE INDEX IF NOT EXISTS ix_perf_prod_readiness_scope ON erp_perf_production_readiness_gate(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_prod_readiness_check ON erp_perf_production_readiness_check(gate_id,status,check_code)',
    ]
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View ERP performance production-readiness integration'),(PERM_MANAGE,'Manage ERP performance production-readiness integration')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gb_routes(app:FastAPI,e:Engine):
    ensure_v90gb_schema(e)
    @app.post('/v90gb/performance/production-readiness/gates')
    def create_gate(b:GateIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); gid=str(uuid4())
        try:
            with e.begin() as c:
                c.execute(text('INSERT INTO erp_perf_production_readiness_gate(gate_id,organization_id,period_key,release_version,environment,note,created_by) VALUES(:g,:o,:p,:v,:e,:n,:u)'),{'g':gid,'o':b.organization_id,'p':b.period_key,'v':b.release_version,'e':b.environment,'n':b.note,'u':u.user_id})
                for code,name in CHECKS:c.execute(text('INSERT INTO erp_perf_production_readiness_check(check_id,gate_id,check_code,check_name,note,reviewed_by) VALUES(:i,:g,:c,:n,:x,:u)'),{'i':str(uuid4()),'g':gid,'c':code,'n':name,'x':'Pending explicit review','u':u.user_id})
        except Exception as ex: raise HTTPException(409,'production-readiness performance gate already exists for organization, period, release and environment') from ex
        return {'gate_id':gid,'status':'OPEN','required_checks':[x[0] for x in CHECKS]}

    @app.post('/v90gb/performance/production-readiness/gates/{gate_id}/checks/{code}')
    def update_check(gate_id:str,code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper(); _ev(b.status,b.evidence_ref)
        if not any(x[0]==code for x in CHECKS):raise HTTPException(422,'unknown production-readiness check')
        with e.begin() as c:
            g=c.execute(text('SELECT organization_id,status FROM erp_perf_production_readiness_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
            if not g:raise HTTPException(404,'production-readiness gate not found')
            _scope(e,u,g['organization_id'])
            if g['status']=='CLOSED':raise HTTPException(409,'production-readiness gate is closed')
            c.execute(text('UPDATE erp_perf_production_readiness_check SET status=:s,evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE gate_id=:g AND check_code=:c'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id,'g':gate_id,'c':code})
        return {'gate_id':gate_id,'check_code':code,'status':b.status}

    @app.get('/v90gb/performance/production-readiness/gates/{gate_id}/readiness')
    def readiness(gate_id:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            g=c.execute(text('SELECT * FROM erp_perf_production_readiness_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
            if not g:raise HTTPException(404,'production-readiness gate not found')
            checks=c.execute(text('SELECT check_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_perf_production_readiness_check WHERE gate_id=:g ORDER BY check_code'),{'g':gate_id}).mappings().all(); o=g['organization_id']; p=g['period_key']; v=g['release_version']; env=g['environment']
            ga=c.execute(text("SELECT COUNT(*) FROM erp_perf_production_gate WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND release_version=:v AND environment=:env AND status='CLOSED'"),{'o':o,'p':p,'v':v,'env':env}).scalar_one()
            uat=c.execute(text("SELECT COUNT(*) FROM erp_uat_plan WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND status='CERTIFIED'"),{'o':o,'p':p}).scalar_one()
            dep=c.execute(text("SELECT deployment_id FROM erp_deployment_cutover WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND release_version=:v AND environment=:env ORDER BY requested_at DESC"),{'o':o,'v':v,'env':env}).fetchall()
            dep_ok=False
            for d in dep:
                controls=c.execute(text("SELECT COUNT(*) FROM erp_deployment_control WHERE deployment_id=:d AND status IN ('PASS','WAIVED')"),{'d':d[0]}).scalar_one(); total=c.execute(text('SELECT COUNT(*) FROM erp_deployment_control WHERE deployment_id=:d'),{'d':d[0]}).scalar_one(); drill=c.execute(text("SELECT COUNT(*) FROM erp_rollback_drill WHERE deployment_id=:d AND result='PASS'"),{'d':d[0]}).scalar_one()
                if total>0 and controls==total and drill>0: dep_ok=True; break
            dr_b=c.execute(text("SELECT COUNT(*) FROM erp_backup_execution WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='SUCCESS'"),{'o':o}).scalar_one()
            dr_r=c.execute(text("SELECT COUNT(*) FROM erp_restore_validation rv JOIN erp_backup_execution b ON b.backup_id=rv.backup_id WHERE ((:o IS NULL AND b.organization_id IS NULL) OR b.organization_id=:o) AND rv.result='PASS'"),{'o':o}).scalar_one()
            dr_d=c.execute(text("SELECT COUNT(*) FROM erp_dr_recovery_drill WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result='PASS'"),{'o':o}).scalar_one()
            dr=(dr_b>0 and dr_r>0 and dr_d>0)
            fx=c.execute(text("SELECT check_code,result FROM erp_ops_health_check WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) ORDER BY checked_at DESC"),{'o':o}).mappings().all(); latest={}
            for x in fx:latest.setdefault(x['check_code'],x['result'])
            fx_ok=all(latest.get(x) in ('PASS','WAIVED') for x in ('APP_HEALTH','DATABASE_HEALTH','BACKGROUND_JOBS','ALERTING','ESCALATION','PERFORMANCE','BACKUP_DR','SECURITY'))
            alerts=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='OPEN' AND severity='CRITICAL'"),{'o':o}).scalar_one(); incidents=c.execute(text("SELECT COUNT(*) FROM erp_ops_incident WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status NOT IN ('CLOSED','RESOLVED')"),{'o':o}).scalar_one()
        explicit={x['check_code']:dict(x) for x in checks}; derived={'PERFORMANCE_GATE':ga>0,'UAT_CERTIFICATION':uat>0,'DEPLOYMENT_CUTOVER':dep_ok,'BACKUP_DR':dr,'OBSERVABILITY':fx_ok,'NO_CRITICAL_ALERTS':alerts==0 and incidents==0}
        ready=all(derived.values()) and all(explicit.get(x[0],{}).get('status') in ('PASS','WAIVED') for x in CHECKS)
        return {'gate':dict(g),'ready_for_production':ready,'derived_gates':derived,'explicit_checks':explicit,'references':{'ga_closed':int(ga),'uat_certified':int(uat),'deployment_ready':dep_ok,'dr_ready':dr,'critical_alerts':int(alerts),'open_incidents':int(incidents),'latest_fx_checks':latest},'note':'This gate integrates recorded ERP evidence; it does not claim that deployment, production execution, or external infrastructure was performed by this application.'}

    @app.post('/v90gb/performance/production-readiness/gates/{gate_id}/certify')
    def certify(gate_id:str,b:CertifyIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:g=c.execute(text('SELECT organization_id,status FROM erp_perf_production_readiness_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
        if not g:raise HTTPException(404,'production-readiness gate not found')
        _scope(e,u,g['organization_id']); s=readiness(gate_id,r)
        if not s['ready_for_production']:raise HTTPException(409,{'message':'production readiness performance gate failed','summary':s})
        with e.begin() as c:c.execute(text("UPDATE erp_perf_production_readiness_gate SET status='PASS',certified_at=CURRENT_TIMESTAMP,certified_by=:u,certification_evidence_ref=:e,certification_note=:n WHERE gate_id=:g"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'g':gate_id})
        return {'gate_id':gate_id,'status':'PASS'}

    @app.post('/v90gb/performance/production-readiness/gates/{gate_id}/close')
    def close(gate_id:str,b:CloseIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:g=c.execute(text('SELECT organization_id,status FROM erp_perf_production_readiness_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
        if not g:raise HTTPException(404,'production-readiness gate not found')
        _scope(e,u,g['organization_id']); s=readiness(gate_id,r)
        if g['status']!='PASS' or not s['ready_for_production']:raise HTTPException(409,'production readiness gate must be certified before close')
        with e.begin() as c:c.execute(text("UPDATE erp_perf_production_readiness_gate SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,close_evidence_ref=:e,close_note=:n WHERE gate_id=:g"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'g':gate_id})
        return {'gate_id':gate_id,'status':'CLOSED'}

    @app.get('/ui/performance-production-readiness')
    def ui():return FileResponse(Path(__file__).resolve().parents[1]/'web'/'performance_production_readiness.html')
    return {'allowed':True}
