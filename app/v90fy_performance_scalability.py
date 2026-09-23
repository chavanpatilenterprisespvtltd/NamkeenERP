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

PERM_VIEW='performance.scalability.view'; PERM_MANAGE='performance.scalability.manage'
RESULTS=('PASS','FAIL','BLOCKED','WAIVED')
HOTSPOT_SEVERITIES=('LOW','MEDIUM','HIGH','CRITICAL')
HOTSPOT_STATUSES=('OPEN','RESOLVED','WAIVED')
CATALOG=(
 ('LATENCY_P50_MS','Latency p50 (ms)','Baseline latency p50 should remain within approved threshold'),
 ('LATENCY_P95_MS','Latency p95 (ms)','Baseline latency p95 should remain within approved threshold'),
 ('LATENCY_P99_MS','Latency p99 (ms)','Baseline latency p99 should remain within approved threshold'),
 ('THROUGHPUT_RPS','Throughput (req/s)','Throughput should remain above approved floor'),
 ('ERROR_RATE_PCT','Error rate (%)','Error rate should remain below approved ceiling'),
 ('CONCURRENCY','Concurrency','Validated concurrency should meet approved target'),
 ('LOAD_RUN','Load run','Load/stress validation must have an evidenced result'),
 ('DB_HOTSPOT','Database hotspot','High/critical unresolved database hotspots block readiness'),
 ('CAPACITY','Capacity assessment','Resource/connection/worker capacity must have an evidenced result'),
 ('REGRESSION','Performance regression','Regression comparison must have an evidenced result'),
)

class BaselineIn(BaseModel):
    organization_id:str|None=None; endpoint:str=Field(min_length=2,max_length=300); environment:str=Field(min_length=2,max_length=80)
    p50_ms:float=Field(ge=0); p95_ms:float=Field(ge=0); p99_ms:float=Field(ge=0); throughput_rps:float=Field(ge=0); error_rate_pct:float=Field(ge=0,le=100); concurrency:int=Field(ge=1)
    result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class LoadRunIn(BaseModel):
    organization_id:str|None=None; scenario:str=Field(min_length=2,max_length=200); environment:str=Field(min_length=2,max_length=80); concurrency:int=Field(ge=1); duration_seconds:int=Field(ge=1)
    requests:int=Field(ge=0); failures:int=Field(ge=0); p95_ms:float=Field(ge=0); throughput_rps:float=Field(ge=0); error_rate_pct:float=Field(ge=0,le=100)
    result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class HotspotIn(BaseModel):
    organization_id:str|None=None; query_fingerprint:str=Field(min_length=3,max_length=300); duration_ms:float=Field(ge=0); calls:int=Field(ge=0)
    severity:str=Field(pattern='^(LOW|MEDIUM|HIGH|CRITICAL)$'); status:str=Field(pattern='^(OPEN|RESOLVED|WAIVED)$'); evidence_ref:str|None=None; remediation_note:str|None=None
class CapacityIn(BaseModel):
    organization_id:str|None=None; environment:str=Field(min_length=2,max_length=80); cpu_utilization_pct:float|None=Field(default=None,ge=0,le=100); memory_utilization_pct:float|None=Field(default=None,ge=0,le=100)
    db_connections:int|None=Field(default=None,ge=0); db_connection_limit:int|None=Field(default=None,ge=1); worker_count:int|None=Field(default=None,ge=1); worker_limit:int|None=Field(default=None,ge=1)
    result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class RegressionIn(BaseModel):
    organization_id:str|None=None; comparison_name:str=Field(min_length=2,max_length=200); baseline_ref:str=Field(min_length=2,max_length=300); current_ref:str=Field(min_length=2,max_length=300)
    latency_delta_pct:float; throughput_delta_pct:float; error_rate_delta_pct:float; result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class ThresholdIn(BaseModel):
    organization_id:str|None=None; metric_code:str=Field(min_length=2,max_length=80); warning_threshold:float; fail_threshold:float; direction:str=Field(pattern='^(MAX|MIN)$'); evidence_ref:str|None=None
class CloseIn(BaseModel):
    signoff_note:str=Field(min_length=1,max_length=3000); evidence_ref:str=Field(min_length=1,max_length=500)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,organization_id):
    try: assert_security_scope(e,u.user_id,organization_id=organization_id)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def _write_evidence_required(result,evidence):
    if result in ('PASS','WAIVED') and not evidence: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')

def ensure_v90fy_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_perf_threshold(perf_threshold_id TEXT PRIMARY KEY,organization_id TEXT NULL,metric_code TEXT NOT NULL,warning_threshold DOUBLE PRECISION NOT NULL,fail_threshold DOUBLE PRECISION NOT NULL,direction TEXT NOT NULL,evidence_ref TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,metric_code))''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_baseline(baseline_id TEXT PRIMARY KEY,organization_id TEXT NULL,endpoint TEXT NOT NULL,environment TEXT NOT NULL,p50_ms DOUBLE PRECISION NOT NULL,p95_ms DOUBLE PRECISION NOT NULL,p99_ms DOUBLE PRECISION NOT NULL,throughput_rps DOUBLE PRECISION NOT NULL,error_rate_pct DOUBLE PRECISION NOT NULL,concurrency INTEGER NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_load_run(load_run_id TEXT PRIMARY KEY,organization_id TEXT NULL,scenario TEXT NOT NULL,environment TEXT NOT NULL,concurrency INTEGER NOT NULL,duration_seconds INTEGER NOT NULL,requests INTEGER NOT NULL,failures INTEGER NOT NULL,p95_ms DOUBLE PRECISION NOT NULL,throughput_rps DOUBLE PRECISION NOT NULL,error_rate_pct DOUBLE PRECISION NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_hotspot(hotspot_id TEXT PRIMARY KEY,organization_id TEXT NULL,query_fingerprint TEXT NOT NULL,duration_ms DOUBLE PRECISION NOT NULL,calls INTEGER NOT NULL,severity TEXT NOT NULL,status TEXT NOT NULL,evidence_ref TEXT NULL,remediation_note TEXT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_capacity(capacity_id TEXT PRIMARY KEY,organization_id TEXT NULL,environment TEXT NOT NULL,cpu_utilization_pct DOUBLE PRECISION NULL,memory_utilization_pct DOUBLE PRECISION NULL,db_connections INTEGER NULL,db_connection_limit INTEGER NULL,worker_count INTEGER NULL,worker_limit INTEGER NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_regression(regression_id TEXT PRIMARY KEY,organization_id TEXT NULL,comparison_name TEXT NOT NULL,baseline_ref TEXT NOT NULL,current_ref TEXT NOT NULL,latency_delta_pct DOUBLE PRECISION NOT NULL,throughput_delta_pct DOUBLE PRECISION NOT NULL,error_rate_delta_pct DOUBLE PRECISION NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_perf_period_close(close_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,signoff_note TEXT NOT NULL,evidence_ref TEXT NOT NULL,closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,period_key))''',
    'CREATE INDEX IF NOT EXISTS ix_perf_baseline_scope ON erp_perf_baseline(organization_id,result,recorded_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_load_scope ON erp_perf_load_run(organization_id,result,recorded_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_hotspot_scope ON erp_perf_hotspot(organization_id,status,severity,recorded_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_capacity_scope ON erp_perf_capacity(organization_id,result,recorded_at)',
    'CREATE INDEX IF NOT EXISTS ix_perf_regression_scope ON erp_perf_regression(organization_id,result,recorded_at)']
    with e.begin() as c:
        for s in stmts: c.execute(text(s))
        for p,n in [(PERM_VIEW,'View performance, load testing and scalability controls'),(PERM_MANAGE,'Manage performance, load testing and scalability controls')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def _where_scope(table, organization_id):
    return (f"SELECT * FROM {table} WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o)", {'o':organization_id})

def register_v90fy_routes(app:FastAPI,e:Engine):
    ensure_v90fy_schema(e)
    @app.get('/v90fy/performance/catalog')
    def catalog(r:Request): _u(e,r,PERM_VIEW); return {'catalog':CATALOG}
    @app.post('/v90fy/performance/thresholds')
    def threshold(b:ThresholdIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id)
        if b.direction=='MAX' and b.warning_threshold>b.fail_threshold: raise HTTPException(422,'MAX thresholds require warning <= fail')
        if b.direction=='MIN' and b.warning_threshold<b.fail_threshold: raise HTTPException(422,'MIN thresholds require warning >= fail')
        tid=str(uuid4())
        with e.begin() as c:
            c.execute(text('INSERT INTO erp_perf_threshold(perf_threshold_id,organization_id,metric_code,warning_threshold,fail_threshold,direction,evidence_ref,created_by) VALUES(:i,:o,:m,:w,:f,:d,:e,:u) ON CONFLICT(organization_id,metric_code) DO UPDATE SET warning_threshold=:w,fail_threshold=:f,direction=:d,evidence_ref=:e,created_by=:u'),{**b.model_dump(), 'o':b.organization_id, 'i':tid, 'u':u.user_id})
        return {'perf_threshold_id':tid,'status':'SAVED'}
    @app.get('/v90fy/performance/thresholds')
    def thresholds(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW); q,p=_where_scope('erp_perf_threshold',organization_id)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY metric_code'),p).mappings().all()]
        return {'thresholds':rows}
    @app.post('/v90fy/performance/baselines')
    def baseline(b:BaselineIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); _write_evidence_required(b.result,b.evidence_ref)
        if not (b.p50_ms<=b.p95_ms<=b.p99_ms): raise HTTPException(422,'latency metrics must satisfy p50 <= p95 <= p99')
        bid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_baseline(baseline_id,organization_id,endpoint,environment,p50_ms,p95_ms,p99_ms,throughput_rps,error_rate_pct,concurrency,result,evidence_ref,notes,recorded_by) VALUES(:i,:o,:endpoint,:environment,:p50_ms,:p95_ms,:p99_ms,:throughput_rps,:error_rate_pct,:concurrency,:result,:evidence_ref,:notes,:u)'),{**b.model_dump(), 'o':b.organization_id, 'i':bid, 'u':u.user_id})
        return {'baseline_id':bid,'status':b.result}
    @app.get('/v90fy/performance/baselines')
    def baselines(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW); q,p=_where_scope('erp_perf_baseline',organization_id)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY recorded_at DESC'),p).mappings().all()]
        return {'baselines':rows}
    @app.post('/v90fy/performance/load-runs')
    def load_run(b:LoadRunIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); _write_evidence_required(b.result,b.evidence_ref)
        if b.failures>b.requests: raise HTTPException(422,'failures cannot exceed requests')
        lrid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_load_run(load_run_id,organization_id,scenario,environment,concurrency,duration_seconds,requests,failures,p95_ms,throughput_rps,error_rate_pct,result,evidence_ref,notes,recorded_by) VALUES(:i,:o,:scenario,:environment,:concurrency,:duration_seconds,:requests,:failures,:p95_ms,:throughput_rps,:error_rate_pct,:result,:evidence_ref,:notes,:u)'),{**b.model_dump(), 'o':b.organization_id, 'i':lrid, 'u':u.user_id})
        return {'load_run_id':lrid,'status':b.result}
    @app.get('/v90fy/performance/load-runs')
    def load_runs(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW); q,p=_where_scope('erp_perf_load_run',organization_id)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY recorded_at DESC'),p).mappings().all()]
        return {'load_runs':rows}
    @app.post('/v90fy/performance/hotspots')
    def hotspot(b:HotspotIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id)
        if b.status in ('RESOLVED','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for RESOLVED or WAIVED')
        hid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_hotspot(hotspot_id,organization_id,query_fingerprint,duration_ms,calls,severity,status,evidence_ref,remediation_note,recorded_by) VALUES(:i,:o,:query_fingerprint,:duration_ms,:calls,:severity,:status,:evidence_ref,:remediation_note,:u)'),{**b.model_dump(), 'o':b.organization_id, 'i':hid, 'u':u.user_id})
        return {'hotspot_id':hid,'status':b.status}
    @app.post('/v90fy/performance/hotspots/{hotspot_id}/status')
    def hotspot_status(hotspot_id:str,b:HotspotIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        if b.status not in ('RESOLVED','WAIVED'): raise HTTPException(422,'status update must be RESOLVED or WAIVED')
        if not b.evidence_ref: raise HTTPException(422,'evidence_ref required for RESOLVED or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id FROM erp_perf_hotspot WHERE hotspot_id=:i'),{'i':hotspot_id}).mappings().first()
            if not row: raise HTTPException(404,'hotspot not found')
            _scope(e,u,row['organization_id'])
            c.execute(text('UPDATE erp_perf_hotspot SET status=:s,evidence_ref=:e,remediation_note=:n WHERE hotspot_id=:i'),{'s':b.status,'e':b.evidence_ref,'n':b.remediation_note,'i':hotspot_id})
        return {'hotspot_id':hotspot_id,'status':b.status}
    @app.get('/v90fy/performance/hotspots')
    def hotspots(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW); q,p=_where_scope('erp_perf_hotspot',organization_id)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY recorded_at DESC'),p).mappings().all()]
        return {'hotspots':rows}
    @app.post('/v90fy/performance/capacity')
    def capacity(b:CapacityIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); _write_evidence_required(b.result,b.evidence_ref)
        if b.db_connections is not None and b.db_connection_limit is not None and b.db_connections>b.db_connection_limit: raise HTTPException(422,'db_connections cannot exceed db_connection_limit')
        if b.worker_count is not None and b.worker_limit is not None and b.worker_count>b.worker_limit: raise HTTPException(422,'worker_count cannot exceed worker_limit')
        cid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_capacity(capacity_id,organization_id,environment,cpu_utilization_pct,memory_utilization_pct,db_connections,db_connection_limit,worker_count,worker_limit,result,evidence_ref,notes,recorded_by) VALUES(:i,:o,:environment,:cpu_utilization_pct,:memory_utilization_pct,:db_connections,:db_connection_limit,:worker_count,:worker_limit,:result,:evidence_ref,:notes,:u)'),{**b.model_dump(), 'o':b.organization_id, 'i':cid, 'u':u.user_id})
        return {'capacity_id':cid,'status':b.result}
    @app.get('/v90fy/performance/capacity')
    def capacities(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW); q,p=_where_scope('erp_perf_capacity',organization_id)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY recorded_at DESC'),p).mappings().all()]
        return {'capacity':rows}
    @app.post('/v90fy/performance/regressions')
    def regression(b:RegressionIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); _write_evidence_required(b.result,b.evidence_ref)
        rid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_regression(regression_id,organization_id,comparison_name,baseline_ref,current_ref,latency_delta_pct,throughput_delta_pct,error_rate_delta_pct,result,evidence_ref,notes,recorded_by) VALUES(:i,:o,:comparison_name,:baseline_ref,:current_ref,:latency_delta_pct,:throughput_delta_pct,:error_rate_delta_pct,:result,:evidence_ref,:notes,:u)'),{**b.model_dump(), 'o':b.organization_id, 'i':rid, 'u':u.user_id})
        return {'regression_id':rid,'status':b.result}
    @app.get('/v90fy/performance/regressions')
    def regressions(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW); q,p=_where_scope('erp_perf_regression',organization_id)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY recorded_at DESC'),p).mappings().all()]
        return {'regressions':rows}
    @app.get('/v90fy/performance/readiness')
    def readiness(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            base=c.execute(text("SELECT COUNT(*) FROM erp_perf_baseline WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result IN ('PASS','WAIVED')"),{'o':organization_id}).scalar_one()
            load=c.execute(text("SELECT COUNT(*) FROM erp_perf_load_run WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result IN ('PASS','WAIVED')"),{'o':organization_id}).scalar_one()
            hot=c.execute(text("SELECT COUNT(*) FROM erp_perf_hotspot WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='OPEN' AND severity IN ('HIGH','CRITICAL')"),{'o':organization_id}).scalar_one()
            cap=c.execute(text("SELECT COUNT(*) FROM erp_perf_capacity WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result IN ('PASS','WAIVED')"),{'o':organization_id}).scalar_one()
            reg=c.execute(text("SELECT COUNT(*) FROM erp_perf_regression WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result IN ('PASS','WAIVED')"),{'o':organization_id}).scalar_one()
            latest=c.execute(text("SELECT result FROM erp_perf_load_run WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) ORDER BY recorded_at DESC LIMIT 1"),{'o':organization_id}).scalar()
        gates={'baseline':base>0,'load_run':load>0,'hotspots':hot==0,'capacity':cap>0,'regression':reg>0}
        return {'ready':all(gates.values()),'gates':gates,'counts':{'passing_baselines':int(base),'passing_load_runs':int(load),'open_high_critical_hotspots':int(hot),'passing_capacity_assessments':int(cap),'passing_regressions':int(reg)},'latest_load_run_result':latest,'evidence_required':'PASS/WAIVED controls require evidence; readiness does not mean a load test was run by the ERP'}
    @app.post('/v90fy/performance/{period_key}/close')
    def close(period_key:str,b:CloseIn,r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,organization_id); s=readiness(r,organization_id)
        if not s['ready']: raise HTTPException(409,{'message':'performance scalability readiness gate failed','summary':s})
        with e.begin() as c:c.execute(text('INSERT INTO erp_perf_period_close(close_id,organization_id,period_key,signoff_note,evidence_ref,closed_by) VALUES(:i,:o,:p,:n,:e,:u)'),{'i':str(uuid4()),'o':organization_id,'p':period_key,'n':b.signoff_note,'e':b.evidence_ref,'u':u.user_id})
        return {'period_key':period_key,'status':'CLOSED','closed_by':u.user_id}
    @app.get('/ui/performance-scalability')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'performance_scalability.html')
    return {'allowed':True}
