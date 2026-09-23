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

PERM_VIEW='performance.optimization.view'
PERM_MANAGE='performance.optimization.manage'
RESULTS=('PASS','FAIL','BLOCKED','WAIVED')
ACTION_STATUSES=('PROPOSED','APPROVED','IN_PROGRESS','COMPLETED','CANCELLED','BLOCKED')
CERT_RESULTS=('CERTIFIED','EXCEPTION','NOT_READY')

class ActionIn(BaseModel):
    organization_id:str|None=None
    finding_ref:str=Field(min_length=2,max_length=300)
    action_type:str=Field(min_length=2,max_length=80)
    title:str=Field(min_length=2,max_length=300)
    owner_user_id:str|None=None
    due_date:str|None=None
    expected_latency_delta_pct:float|None=None
    expected_throughput_delta_pct:float|None=None
    expected_error_rate_delta_pct:float|None=None
    status:str=Field(pattern='^(PROPOSED|APPROVED|IN_PROGRESS|COMPLETED|CANCELLED|BLOCKED)$')
    evidence_ref:str|None=None
    notes:str=Field(min_length=1,max_length=3000)

class ActionUpdate(BaseModel):
    organization_id:str|None=None
    status:str=Field(pattern='^(PROPOSED|APPROVED|IN_PROGRESS|COMPLETED|CANCELLED|BLOCKED)$')
    evidence_ref:str|None=None
    result_note:str|None=None

class CapacityRemediationIn(BaseModel):
    organization_id:str|None=None
    finding_ref:str=Field(min_length=2,max_length=300)
    resource_type:str=Field(min_length=2,max_length=80)
    current_value:float=Field(ge=0)
    target_value:float=Field(ge=0)
    unit:str=Field(min_length=1,max_length=40)
    action_ref:str=Field(min_length=2,max_length=300)
    status:str=Field(pattern='^(PROPOSED|APPROVED|IN_PROGRESS|COMPLETED|CANCELLED|BLOCKED)$')
    evidence_ref:str|None=None
    notes:str=Field(min_length=1,max_length=3000)

class OptimizationResultIn(BaseModel):
    organization_id:str|None=None
    action_ref:str=Field(min_length=2,max_length=300)
    baseline_ref:str=Field(min_length=2,max_length=300)
    post_change_ref:str=Field(min_length=2,max_length=300)
    latency_delta_pct:float
    throughput_delta_pct:float
    error_rate_delta_pct:float
    result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$')
    evidence_ref:str|None=None
    notes:str=Field(min_length=1,max_length=3000)

class CertificationIn(BaseModel):
    certification_note:str=Field(min_length=1,max_length=3000)
    evidence_ref:str=Field(min_length=1,max_length=500)
    result:str=Field(pattern='^(CERTIFIED|EXCEPTION|NOT_READY)$')

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

def _evidence(result,evidence):
    if result in ('PASS','WAIVED','CERTIFIED','EXCEPTION') and not evidence:
        raise HTTPException(422,'evidence_ref required for successful/exception certification')

def ensure_v90fz_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_perf_optimization_action(action_id TEXT PRIMARY KEY,organization_id TEXT NULL,finding_ref TEXT NOT NULL,action_type TEXT NOT NULL,title TEXT NOT NULL,owner_user_id TEXT NULL,due_date TEXT NULL,expected_latency_delta_pct DOUBLE PRECISION NULL,expected_throughput_delta_pct DOUBLE PRECISION NULL,expected_error_rate_delta_pct DOUBLE PRECISION NULL,status TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_capacity_remediation(remediation_id TEXT PRIMARY KEY,organization_id TEXT NULL,finding_ref TEXT NOT NULL,resource_type TEXT NOT NULL,current_value DOUBLE PRECISION NOT NULL,target_value DOUBLE PRECISION NOT NULL,unit TEXT NOT NULL,action_ref TEXT NOT NULL,status TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_optimization_result(result_id TEXT PRIMARY KEY,organization_id TEXT NULL,action_ref TEXT NOT NULL,baseline_ref TEXT NOT NULL,post_change_ref TEXT NOT NULL,latency_delta_pct DOUBLE PRECISION NOT NULL,throughput_delta_pct DOUBLE PRECISION NOT NULL,error_rate_delta_pct DOUBLE PRECISION NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_scalability_certification(certification_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,result TEXT NOT NULL,certification_note TEXT NOT NULL,evidence_ref TEXT NOT NULL,certified_by TEXT NOT NULL,certified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,period_key))''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_optimization_period_close(close_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,signoff_note TEXT NOT NULL,evidence_ref TEXT NOT NULL,closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,period_key))''',
    'CREATE INDEX IF NOT EXISTS ix_perf_opt_action_scope ON erp_perf_optimization_action(organization_id,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_capacity_remediation_scope ON erp_perf_capacity_remediation(organization_id,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_opt_result_scope ON erp_perf_optimization_result(organization_id,result,recorded_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_cert_scope ON erp_perf_scalability_certification(organization_id,result,certified_at)'
    ]
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View performance optimization and scalability certification controls'),(PERM_MANAGE,'Manage performance optimization and scalability certification controls')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def _where(table, organization_id):
    return f"SELECT * FROM {table} WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o)", {'o':organization_id}

def register_v90fz_routes(app:FastAPI,e:Engine):
    ensure_v90fz_schema(e)

    @app.post('/v90fz/performance/actions')
    def create_action(b:ActionIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id)
        if b.status in ('COMPLETED',) and not b.evidence_ref: raise HTTPException(422,'evidence_ref required when action is COMPLETED')
        aid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_optimization_action(action_id,organization_id,finding_ref,action_type,title,owner_user_id,due_date,expected_latency_delta_pct,expected_throughput_delta_pct,expected_error_rate_delta_pct,status,evidence_ref,notes,created_by) VALUES(:i,:o,:finding_ref,:action_type,:title,:owner_user_id,:due_date,:expected_latency_delta_pct,:expected_throughput_delta_pct,:expected_error_rate_delta_pct,:status,:evidence_ref,:notes,:u)'),{**b.model_dump(),'i':aid,'o':b.organization_id,'u':u.user_id})
        return {'action_id':aid,'status':b.status}

    @app.get('/v90fz/performance/actions')
    def actions(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q,p=_where('erp_perf_optimization_action',organization_id)
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c:rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'actions':rows}

    @app.post('/v90fz/performance/actions/{action_id}/status')
    def update_action(action_id:str,b:ActionUpdate,r:Request):
        u=_u(e,r,PERM_MANAGE)
        if b.status=='COMPLETED' and not b.evidence_ref:raise HTTPException(422,'evidence_ref required when action is COMPLETED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_perf_optimization_action WHERE action_id=:i'),{'i':action_id}).mappings().first()
            if not row:raise HTTPException(404,'optimization action not found')
            _scope(e,u,row['organization_id'])
            c.execute(text('UPDATE erp_perf_optimization_action SET status=:s,evidence_ref=COALESCE(:e,evidence_ref),notes=CASE WHEN :n IS NULL THEN notes ELSE notes||\'\\n\'||:n END,updated_at=CURRENT_TIMESTAMP WHERE action_id=:i'),{'s':b.status,'e':b.evidence_ref,'n':b.result_note,'i':action_id})
        return {'action_id':action_id,'status':b.status}

    @app.post('/v90fz/performance/capacity-remediations')
    def capacity_remediation(b:CapacityRemediationIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id)
        if b.status=='COMPLETED' and not b.evidence_ref:raise HTTPException(422,'evidence_ref required when remediation is COMPLETED')
        rid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_capacity_remediation(remediation_id,organization_id,finding_ref,resource_type,current_value,target_value,unit,action_ref,status,evidence_ref,notes,created_by) VALUES(:i,:o,:finding_ref,:resource_type,:current_value,:target_value,:unit,:action_ref,:status,:evidence_ref,:notes,:u)'),{**b.model_dump(),'i':rid,'o':b.organization_id,'u':u.user_id})
        return {'remediation_id':rid,'status':b.status}

    @app.post('/v90fz/performance/capacity-remediations/{remediation_id}/status')
    def capacity_remediation_status(remediation_id:str,b:CapacityRemediationIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        if b.status not in ('PROPOSED','APPROVED','IN_PROGRESS','COMPLETED','CANCELLED','BLOCKED'): raise HTTPException(422,'invalid remediation status')
        if b.status=='COMPLETED' and not b.evidence_ref: raise HTTPException(422,'evidence_ref required when remediation is COMPLETED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id FROM erp_perf_capacity_remediation WHERE remediation_id=:i'),{'i':remediation_id}).mappings().first()
            if not row: raise HTTPException(404,'capacity remediation not found')
            _scope(e,u,row['organization_id'])
            c.execute(text("UPDATE erp_perf_capacity_remediation SET status=:s,evidence_ref=COALESCE(:e,evidence_ref),notes=CASE WHEN :n IS NULL THEN notes ELSE notes||\'\n\'||:n END,updated_at=CURRENT_TIMESTAMP WHERE remediation_id=:i"), {"s":b.status,"e":b.evidence_ref,"n":b.notes,"i":remediation_id})
        return {'remediation_id':remediation_id,'status':b.status}

    @app.get('/v90fz/performance/capacity-remediations')
    def capacity_remediations(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW);q,p=_where('erp_perf_capacity_remediation',organization_id)
        with e.connect() as c:rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'capacity_remediations':rows}

    @app.post('/v90fz/performance/optimization-results')
    def optimization_result(b:OptimizationResultIn,r:Request):
        u=_u(e,r,PERM_MANAGE);_scope(e,u,b.organization_id);_evidence(b.result,b.evidence_ref)
        oid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_optimization_result(result_id,organization_id,action_ref,baseline_ref,post_change_ref,latency_delta_pct,throughput_delta_pct,error_rate_delta_pct,result,evidence_ref,notes,recorded_by) VALUES(:i,:o,:action_ref,:baseline_ref,:post_change_ref,:latency_delta_pct,:throughput_delta_pct,:error_rate_delta_pct,:result,:evidence_ref,:notes,:u)'),{**b.model_dump(),'i':oid,'o':b.organization_id,'u':u.user_id})
        return {'result_id':oid,'status':b.result}

    @app.get('/v90fz/performance/optimization-results')
    def optimization_results(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW);q,p=_where('erp_perf_optimization_result',organization_id)
        with e.connect() as c:rows=[dict(x) for x in c.execute(text(q+' ORDER BY recorded_at DESC'),p).mappings().all()]
        return {'results':rows}

    @app.get('/v90fz/performance/certification-readiness')
    def readiness(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            open_actions=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_action WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status IN ('PROPOSED','APPROVED','IN_PROGRESS','BLOCKED')"),{'o':organization_id}).scalar_one()
            completed_actions=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_action WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='COMPLETED'"),{'o':organization_id}).scalar_one()
            open_capacity=c.execute(text("SELECT COUNT(*) FROM erp_perf_capacity_remediation WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status IN ('PROPOSED','APPROVED','IN_PROGRESS','BLOCKED')"),{'o':organization_id}).scalar_one()
            passing_results=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_result WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result IN ('PASS','WAIVED')"),{'o':organization_id}).scalar_one()
            failing_results=c.execute(text("SELECT COUNT(*) FROM erp_perf_optimization_result WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result='FAIL'"),{'o':organization_id}).scalar_one()
        gates={'actions_remediated':open_actions==0 and completed_actions>0,'capacity_remediated':open_capacity==0,'optimization_results':passing_results>0,'no_failed_post_change':failing_results==0}
        return {'ready':all(gates.values()),'gates':gates,'counts':{'open_optimization_actions':int(open_actions),'completed_optimization_actions':int(completed_actions),'open_capacity_remediations':int(open_capacity),'passing_optimization_results':int(passing_results),'failed_optimization_results':int(failing_results)},'note':'Certification readiness records control evidence; it does not claim that production performance changes were executed by the ERP.'}

    @app.post('/v90fz/performance/{period_key}/certify')
    def certify(period_key:str,b:CertificationIn,r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE);_scope(e,u,organization_id);_evidence(b.result,b.evidence_ref)
        s=readiness(r,organization_id)
        if b.result=='CERTIFIED' and not s['ready']:raise HTTPException(409,{'message':'performance optimization certification gate failed','summary':s})
        cid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_scalability_certification(certification_id,organization_id,period_key,result,certification_note,evidence_ref,certified_by) VALUES(:i,:o,:p,:r,:n,:e,:u) ON CONFLICT(organization_id,period_key) DO UPDATE SET result=:r,certification_note=:n,evidence_ref=:e,certified_by=:u,certified_at=CURRENT_TIMESTAMP'),{'i':cid,'o':organization_id,'p':period_key,'r':b.result,'n':b.certification_note,'e':b.evidence_ref,'u':u.user_id})
        return {'period_key':period_key,'result':b.result,'certification_id':cid}

    @app.get('/v90fz/performance/{period_key}/certification')
    def certification(period_key:str,r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:row=c.execute(text('SELECT * FROM erp_perf_scalability_certification WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p ORDER BY certified_at DESC'),{'o':organization_id,'p':period_key}).mappings().first()
        return {'certification':dict(row) if row else None}

    @app.post('/v90fz/performance/{period_key}/close')
    def close(period_key:str,b:CloseIn,r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE);_scope(e,u,organization_id)
        s=readiness(r,organization_id)
        if not s['ready']:raise HTTPException(409,{'message':'performance optimization close gate failed','summary':s})
        cert=certification(period_key,r,organization_id)['certification']
        if not cert or cert['result']!='CERTIFIED':raise HTTPException(409,'scalability certification is required before period close')
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_optimization_period_close(close_id,organization_id,period_key,signoff_note,evidence_ref,closed_by) VALUES(:i,:o,:p,:n,:e,:u)'),{'i':str(uuid4()),'o':organization_id,'p':period_key,'n':b.signoff_note,'e':b.evidence_ref,'u':u.user_id})
        return {'period_key':period_key,'status':'CLOSED','closed_by':u.user_id}

    @app.get('/ui/performance-optimization')
    def ui():return FileResponse(Path(__file__).resolve().parents[1]/'web'/'performance_optimization.html')
    return {'allowed':True}
