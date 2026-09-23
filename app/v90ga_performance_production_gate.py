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

PERM_VIEW='performance.production_gate.view'
PERM_MANAGE='performance.production_gate.manage'
STATUSES=('OPEN','PASS','FAIL','BLOCKED','WAIVED')
CHECKS=(
 ('SCALABILITY_READINESS','V90.fy scalability readiness is green with baseline, load, capacity and regression evidence'),
 ('OPTIMIZATION_CERTIFICATION','V90.fz optimization remediation and certification are complete'),
 ('OPERATIONAL_HEALTH','V90.fx operational health and SLA controls are healthy'),
 ('PERFORMANCE_EVIDENCE','Production performance-gate evidence is explicitly reviewed'),
 ('CAPACITY_HEADROOM','Production capacity headroom is explicitly reviewed'),
 ('REGRESSION_CONTROL','Performance regression control is explicitly reviewed'),
)

class GateIn(BaseModel):
    organization_id:str|None=None
    period_key:str=Field(min_length=4,max_length=40)
    release_version:str=Field(min_length=3,max_length=40)
    environment:str=Field(min_length=2,max_length=80)
    note:str=Field(min_length=1,max_length=3000)

class CheckIn(BaseModel):
    status:str=Field(pattern='^(OPEN|PASS|FAIL|BLOCKED|WAIVED)$')
    evidence_ref:str|None=None
    note:str=Field(min_length=1,max_length=3000)

class CertificationIn(BaseModel):
    result:str=Field(pattern='^(CERTIFIED|EXCEPTION|NOT_READY)$')
    certification_note:str=Field(min_length=1,max_length=3000)
    evidence_ref:str=Field(min_length=1,max_length=500)

class CloseIn(BaseModel):
    signoff_note:str=Field(min_length=1,max_length=3000)
    evidence_ref:str=Field(min_length=1,max_length=500)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,organization_id):
    try: assert_security_scope(e,u.user_id,organization_id=organization_id)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def _ev(status,evidence):
    if status in ('PASS','WAIVED') and not evidence: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')

def ensure_v90ga_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_perf_production_gate(gate_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,environment TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,certified_at TIMESTAMP NULL,certified_by TEXT NULL,certification_note TEXT NULL,certification_evidence_ref TEXT NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,close_note TEXT NULL,close_evidence_ref TEXT NULL,UNIQUE(organization_id,period_key,release_version,environment))''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_production_gate_check(check_id TEXT PRIMARY KEY,gate_id TEXT NOT NULL,check_code TEXT NOT NULL,check_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(gate_id,check_code))''',
    'CREATE INDEX IF NOT EXISTS ix_perf_prod_gate_scope ON erp_perf_production_gate(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_prod_gate_check ON erp_perf_production_gate_check(gate_id,status,check_code)',
    ]
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View ERP performance production gate'),(PERM_MANAGE,'Manage ERP performance production gate')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def _org_clause(alias=''):
    a=(alias+'.') if alias else ''
    return f"(({a}organization_id IS NULL AND :o IS NULL) OR {a}organization_id=:o)"

def register_v90ga_routes(app:FastAPI,e:Engine):
    ensure_v90ga_schema(e)

    @app.post('/v90ga/performance/gates')
    def create_gate(b:GateIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id)
        gid=str(uuid4())
        try:
            with e.begin() as c:
                c.execute(text('INSERT INTO erp_perf_production_gate(gate_id,organization_id,period_key,release_version,environment,note,created_by) VALUES(:g,:o,:p,:v,:env,:n,:u)'),{'g':gid,'o':b.organization_id,'p':b.period_key,'v':b.release_version,'env':b.environment,'n':b.note,'u':u.user_id})
                for code,name in CHECKS:
                    c.execute(text('INSERT INTO erp_perf_production_gate_check(check_id,gate_id,check_code,check_name,note,reviewed_by) VALUES(:i,:g,:c,:n,:note,:u)'),{'i':str(uuid4()),'g':gid,'c':code,'n':name,'note':'Pending explicit review','u':u.user_id})
        except Exception as ex:
            raise HTTPException(409,'performance production gate already exists for organization, period, release and environment') from ex
        return {'gate_id':gid,'status':'OPEN','required_checks':[x[0] for x in CHECKS]}

    @app.post('/v90ga/performance/gates/{gate_id}/checks/{check_code}')
    def update_check(gate_id:str,check_code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=check_code.upper()
        check=next((x for x in CHECKS if x[0]==code),None)
        if not check: raise HTTPException(422,'unknown performance production gate check')
        _ev(b.status,b.evidence_ref)
        with e.begin() as c:
            gate=c.execute(text('SELECT organization_id,status FROM erp_perf_production_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
            if not gate: raise HTTPException(404,'performance production gate not found')
            _scope(e,u,gate['organization_id'])
            if gate['status']=='CLOSED': raise HTTPException(409,'performance production gate is closed')
            c.execute(text('UPDATE erp_perf_production_gate_check SET status=:s,evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE gate_id=:g AND check_code=:c'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id,'g':gate_id,'c':code})
        return {'gate_id':gate_id,'check_code':code,'status':b.status}

    @app.get('/v90ga/performance/gates')
    def list_gates(r:Request,organization_id:str|None=None,period_key:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            q='SELECT * FROM erp_perf_production_gate WHERE '+_org_clause()
            p={'o':organization_id}
            if period_key:q+=' AND period_key=:p';p['p']=period_key
            rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'gates':rows}

    def readiness_summary(gate_id:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            gate=c.execute(text('SELECT * FROM erp_perf_production_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
            if not gate: raise HTTPException(404,'performance production gate not found')
            checks=c.execute(text('SELECT check_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_perf_production_gate_check WHERE gate_id=:g ORDER BY check_code'),{'g':gate_id}).mappings().all()
            o=gate['organization_id']
            fy=c.execute(text("SELECT COUNT(*) FROM erp_perf_baseline WHERE "+_org_clause()+" AND result IN ('PASS','WAIVED')"),{'o':o}).scalar_one()
            fl=c.execute(text("SELECT COUNT(*) FROM erp_perf_load_run WHERE "+_org_clause()+" AND result IN ('PASS','WAIVED')"),{'o':o}).scalar_one()
            fh=c.execute(text("SELECT COUNT(*) FROM erp_perf_hotspot WHERE "+_org_clause()+" AND status='OPEN' AND severity IN ('HIGH','CRITICAL')"),{'o':o}).scalar_one()
            fc=c.execute(text("SELECT COUNT(*) FROM erp_perf_capacity WHERE "+_org_clause()+" AND result IN ('PASS','WAIVED')"),{'o':o}).scalar_one()
            fr=c.execute(text("SELECT COUNT(*) FROM erp_perf_regression WHERE "+_org_clause()+" AND result IN ('PASS','WAIVED')"),{'o':o}).scalar_one()
            fz_a=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_action WHERE "+_org_clause()+" AND status IN ('PROPOSED','APPROVED','IN_PROGRESS','BLOCKED')"),{'o':o}).scalar_one()
            fz_c=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_action WHERE "+_org_clause()+" AND status='COMPLETED'"),{'o':o}).scalar_one()
            fz_cap=c.execute(text("SELECT COUNT(*) FROM erp_perf_capacity_remediation WHERE "+_org_clause()+" AND status IN ('PROPOSED','APPROVED','IN_PROGRESS','BLOCKED')"),{'o':o}).scalar_one()
            fz_pass=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_result WHERE "+_org_clause()+" AND result IN ('PASS','WAIVED')"),{'o':o}).scalar_one()
            fz_fail=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_result WHERE "+_org_clause()+" AND result='FAIL'"),{'o':o}).scalar_one()
            fz_cert=c.execute(text("SELECT COUNT(*) FROM erp_perf_scalability_certification WHERE "+_org_clause('erp_perf_scalability_certification')+" AND result='CERTIFIED'"),{'o':o}).scalar_one()
            fx_checks=c.execute(text("SELECT check_code,result FROM erp_ops_health_check WHERE "+_org_clause()+" ORDER BY checked_at DESC"),{'o':o}).mappings().all()
            latest_fx={}
            for row in fx_checks: latest_fx.setdefault(row['check_code'],row['result'])
            fx_ok=all(latest_fx.get(code) in ('PASS','WAIVED') for code in ('APP_HEALTH','DATABASE_HEALTH','BACKGROUND_JOBS','ALERTING','ESCALATION','PERFORMANCE','BACKUP_DR','SECURITY'))
            fx_crit=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE "+_org_clause()+" AND status='OPEN' AND severity='CRITICAL'"),{'o':o}).scalar_one()
            fx_inc=c.execute(text("SELECT COUNT(*) FROM erp_ops_incident WHERE "+_org_clause()+" AND status NOT IN ('CLOSED','RESOLVED')"),{'o':o}).scalar_one()
        explicit={x['check_code']:dict(x) for x in checks}
        derived={
          'SCALABILITY_READINESS': fy>0 and fl>0 and fh==0 and fc>0 and fr>0,
          'OPTIMIZATION_CERTIFICATION': fz_a==0 and fz_cap==0 and fz_c>0 and fz_pass>0 and fz_fail==0 and fz_cert>0,
          'OPERATIONAL_HEALTH': fx_ok and fx_crit==0 and fx_inc==0,
          'PERFORMANCE_EVIDENCE': explicit.get('PERFORMANCE_EVIDENCE',{}).get('status') in ('PASS','WAIVED'),
          'CAPACITY_HEADROOM': explicit.get('CAPACITY_HEADROOM',{}).get('status') in ('PASS','WAIVED'),
          'REGRESSION_CONTROL': explicit.get('REGRESSION_CONTROL',{}).get('status') in ('PASS','WAIVED'),
        }
        ready=all(derived.values()) and all(explicit.get(x[0],{}).get('status') in ('PASS','WAIVED') or x[0] in ('SCALABILITY_READINESS','OPTIMIZATION_CERTIFICATION','OPERATIONAL_HEALTH') for x in CHECKS)
        return {'gate':dict(gate),'ready_for_certification':ready,'derived_gates':derived,'explicit_checks':explicit,'performance_counts':{'fy_passing_baselines':int(fy),'fy_passing_load_runs':int(fl),'fy_open_high_critical_hotspots':int(fh),'fy_passing_capacity':int(fc),'fy_passing_regressions':int(fr),'fz_open_actions':int(fz_a),'fz_completed_actions':int(fz_c),'fz_open_capacity_remediations':int(fz_cap),'fz_passing_results':int(fz_pass),'fz_failed_results':int(fz_fail),'fz_certified_records':int(fz_cert)},'fx':{'healthy':fx_ok,'critical_open_alerts':int(fx_crit),'open_incidents':int(fx_inc),'latest_checks':latest_fx},'note':'Production performance certification aggregates recorded evidence from V90.fy, V90.fz and V90.fx; it does not claim that external load/APM or production execution was performed by the ERP.'}

    @app.get('/v90ga/performance/gates/{gate_id}/readiness')
    def readiness(gate_id:str,r:Request):
        return readiness_summary(gate_id,r)

    @app.post('/v90ga/performance/gates/{gate_id}/certify')
    def certify(gate_id:str,b:CertificationIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _ev('PASS' if b.result=='CERTIFIED' else 'WAIVED',b.evidence_ref)
        with e.connect() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_perf_production_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
        if not row: raise HTTPException(404,'performance production gate not found')
        _scope(e,u,row['organization_id'])
        s=readiness_summary(gate_id,r)
        if b.result=='CERTIFIED' and not s['ready_for_certification']: raise HTTPException(409,{'message':'production performance certification gate failed','summary':s})
        with e.begin() as c:
            c.execute(text("UPDATE erp_perf_production_gate SET status=:s,certified_at=CURRENT_TIMESTAMP,certified_by=:u,certification_note=:n,certification_evidence_ref=:e WHERE gate_id=:g"),{'s':'PASS' if b.result=='CERTIFIED' else ('FAIL' if b.result=='NOT_READY' else 'BLOCKED'),'u':u.user_id,'n':b.certification_note,'e':b.evidence_ref,'g':gate_id})
        return {'gate_id':gate_id,'result':b.result}

    @app.post('/v90ga/performance/gates/{gate_id}/close')
    def close(gate_id:str,b:CloseIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:row=c.execute(text('SELECT organization_id,status FROM erp_perf_production_gate WHERE gate_id=:g'),{'g':gate_id}).mappings().first()
        if not row: raise HTTPException(404,'performance production gate not found')
        _scope(e,u,row['organization_id'])
        s=readiness_summary(gate_id,r)
        if not s['ready_for_certification']: raise HTTPException(409,{'message':'performance production close gate failed','summary':s})
        if row['status']!='PASS': raise HTTPException(409,'production performance gate must be certified before close')
        with e.begin() as c:c.execute(text("UPDATE erp_perf_production_gate SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,close_note=:n,close_evidence_ref=:e WHERE gate_id=:g"),{'u':u.user_id,'n':b.signoff_note,'e':b.evidence_ref,'g':gate_id})
        return {'gate_id':gate_id,'status':'CLOSED','closed_by':u.user_id}

    @app.get('/ui/performance-production-gate')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'performance_production_gate.html')
    return {'allowed':True}
