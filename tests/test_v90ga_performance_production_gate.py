from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def _seed_dependencies(c,h,org):
    r=c.post('/v90fy/performance/baselines',headers=h,json={'organization_id':org,'endpoint':'/orders','environment':'prod','p50_ms':10,'p95_ms':20,'p99_ms':30,'throughput_rps':50,'error_rate_pct':0.5,'concurrency':20,'result':'PASS','evidence_ref':'FY-B','notes':'baseline'}); assert r.status_code==200
    r=c.post('/v90fy/performance/load-runs',headers=h,json={'organization_id':org,'scenario':'critical-api','environment':'prod','concurrency':20,'duration_seconds':60,'requests':3000,'failures':3,'p95_ms':25,'throughput_rps':50,'error_rate_pct':0.1,'result':'PASS','evidence_ref':'FY-L','notes':'load'}) ; assert r.status_code==200
    r=c.post('/v90fy/performance/capacity',headers=h,json={'organization_id':org,'environment':'prod','cpu_utilization_pct':65,'memory_utilization_pct':60,'db_connections':50,'db_connection_limit':100,'worker_count':4,'worker_limit':8,'result':'PASS','evidence_ref':'FY-C','notes':'capacity'}); assert r.status_code==200
    r=c.post('/v90fy/performance/regressions',headers=h,json={'organization_id':org,'comparison_name':'release baseline','baseline_ref':'B0','current_ref':'C1','latency_delta_pct':-5,'throughput_delta_pct':8,'error_rate_delta_pct':-0.2,'result':'PASS','evidence_ref':'FY-R','notes':'no regression'}); assert r.status_code==200
    r=c.post('/v90fz/performance/actions',headers=h,json={'organization_id':org,'finding_ref':'HOT-1','action_type':'INDEX','title':'Optimize hot query','status':'COMPLETED','evidence_ref':'FZ-A','notes':'done'}); assert r.status_code==200
    aid=r.json()['action_id']
    r=c.post('/v90fz/performance/capacity-remediations',headers=h,json={'organization_id':org,'finding_ref':'CAP-1','resource_type':'DB_CONNECTIONS','current_value':60,'target_value':100,'unit':'connections','action_ref':aid,'status':'COMPLETED','evidence_ref':'FZ-C','notes':'done'}); assert r.status_code==200
    r=c.post('/v90fz/performance/optimization-results',headers=h,json={'organization_id':org,'action_ref':aid,'baseline_ref':'FY-B','post_change_ref':'POST','latency_delta_pct':-10,'throughput_delta_pct':10,'error_rate_delta_pct':-0.1,'result':'PASS','evidence_ref':'FZ-R','notes':'improved'}); assert r.status_code==200
    r=c.post('/v90fz/performance/2026-09/certify',headers=h,params={'organization_id':org},json={'result':'CERTIFIED','certification_note':'complete','evidence_ref':'FZ-CERT'}); assert r.status_code==200
    for code in ['APP_HEALTH','DATABASE_HEALTH','BACKGROUND_JOBS','ALERTING','ESCALATION','PERFORMANCE','BACKUP_DR','SECURITY']:
        r=c.post('/v90fx/health-checks',headers=h,params={'organization_id':org},json={'check_code':code,'result':'PASS','notes':'verified','evidence_ref':'FX-'+code}); assert r.status_code==200

def test_gate_blocks_until_explicit_controls_and_dependencies_are_green():
    c=TestClient(app); h=_admin(c); org='ga-'+str(uuid4())[:8]
    _seed_dependencies(c,h,org)
    r=c.post('/v90ga/performance/gates',headers=h,json={'organization_id':org,'period_key':'2026-09','release_version':'v90.gb','environment':'production','note':'gate'}); assert r.status_code==200
    gid=r.json()['gate_id']
    r=c.get(f'/v90ga/performance/gates/{gid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_certification'] is False
    for code in ['PERFORMANCE_EVIDENCE','CAPACITY_HEADROOM','REGRESSION_CONTROL']:
        r=c.post(f'/v90ga/performance/gates/{gid}/checks/{code}',headers=h,json={'status':'PASS','evidence_ref':'GA-'+code,'note':'reviewed'}); assert r.status_code==200
    r=c.get(f'/v90ga/performance/gates/{gid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_certification'] is True
    r=c.post(f'/v90ga/performance/gates/{gid}/certify',headers=h,json={'result':'CERTIFIED','certification_note':'production performance gate certified','evidence_ref':'GA-CERT'}); assert r.status_code==200
    r=c.post(f'/v90ga/performance/gates/{gid}/close',headers=h,json={'signoff_note':'closed','evidence_ref':'GA-CLOSE'}); assert r.status_code==200

def test_evidence_and_operational_health_block_gate():
    c=TestClient(app); h=_admin(c); org='ga2-'+str(uuid4())[:8]
    r=c.post('/v90ga/performance/gates',headers=h,json={'organization_id':org,'period_key':'2026-10','release_version':'v90.gb','environment':'staging','note':'gate'}); assert r.status_code==200; gid=r.json()['gate_id']
    r=c.post(f'/v90ga/performance/gates/{gid}/checks/PERFORMANCE_EVIDENCE',headers=h,json={'status':'PASS','note':'missing evidence'}); assert r.status_code==422
    r=c.post('/v90fx/alerts',headers=h,params={'organization_id':org},json={'severity':'CRITICAL','alert_code':'PERF-1','message':'critical','status':'OPEN','notes':'x'}); assert r.status_code==200
    r=c.get(f'/v90ga/performance/gates/{gid}/readiness',headers=h); assert r.status_code==200 and r.json()['derived_gates']['OPERATIONAL_HEALTH'] is False

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
