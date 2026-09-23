from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_performance_readiness_gates_and_evidence():
    c=TestClient(app); h=_admin(c); org='fy-'+str(uuid4())[:8]
    r=c.get('/v90fy/performance/readiness',headers=h,params={'organization_id':org}); assert r.status_code==200 and r.json()['ready'] is False
    r=c.post('/v90fy/performance/baselines',headers=h,json={'organization_id':org,'endpoint':'/sales/orders','environment':'STAGING','p50_ms':20,'p95_ms':45,'p99_ms':80,'throughput_rps':120,'error_rate_pct':0.4,'concurrency':25,'result':'PASS','notes':'baseline'}); assert r.status_code==422
    r=c.post('/v90fy/performance/baselines',headers=h,json={'organization_id':org,'endpoint':'/sales/orders','environment':'STAGING','p50_ms':20,'p95_ms':45,'p99_ms':80,'throughput_rps':120,'error_rate_pct':0.4,'concurrency':25,'result':'PASS','evidence_ref':'BASE-1','notes':'baseline'}); assert r.status_code==200
    r=c.post('/v90fy/performance/load-runs',headers=h,json={'organization_id':org,'scenario':'peak orders','environment':'STAGING','concurrency':50,'duration_seconds':300,'requests':10000,'failures':20,'p95_ms':70,'throughput_rps':33.3,'error_rate_pct':0.2,'result':'PASS','evidence_ref':'LOAD-1','notes':'load evidence'}); assert r.status_code==200
    r=c.post('/v90fy/performance/hotspots',headers=h,json={'organization_id':org,'query_fingerprint':'Q-001','duration_ms':450,'calls':2000,'severity':'HIGH','status':'OPEN'}); assert r.status_code==200; hid=r.json()['hotspot_id']
    r=c.post('/v90fy/performance/capacity',headers=h,json={'organization_id':org,'environment':'STAGING','cpu_utilization_pct':62,'memory_utilization_pct':58,'db_connections':40,'db_connection_limit':100,'worker_count':4,'worker_limit':8,'result':'PASS','evidence_ref':'CAP-1','notes':'capacity'}); assert r.status_code==200
    r=c.post('/v90fy/performance/regressions',headers=h,json={'organization_id':org,'comparison_name':'baseline-vs-current','baseline_ref':'BASE-1','current_ref':'LOAD-1','latency_delta_pct':2.0,'throughput_delta_pct':-1.5,'error_rate_delta_pct':0.1,'result':'PASS','evidence_ref':'REG-1','notes':'comparison'}); assert r.status_code==200
    r=c.get('/v90fy/performance/readiness',headers=h,params={'organization_id':org}); assert r.status_code==200 and r.json()['ready'] is False and r.json()['gates']['hotspots'] is False
    assert c.post(f'/v90fy/performance/hotspots/{hid}/status',headers=h,json={'organization_id':org,'query_fingerprint':'Q-001','duration_ms':450,'calls':2000,'severity':'HIGH','status':'RESOLVED','evidence_ref':'HOT-1','remediation_note':'index added'}).status_code==200
    r=c.get('/v90fy/performance/readiness',headers=h,params={'organization_id':org}); assert r.status_code==200 and r.json()['ready'] is True
    assert c.post(f'/v90fy/performance/2026-09/close',headers=h,params={'organization_id':org},json={'signoff_note':'ready','evidence_ref':'CLOSE-1'}).status_code==200

def test_validation_and_manifest():
    c=TestClient(app); h=_admin(c); org='fy2-'+str(uuid4())
    assert c.post('/v90fy/performance/load-runs',headers=h,json={'organization_id':org,'scenario':'x','environment':'STAGING','concurrency':1,'duration_seconds':10,'requests':1,'failures':2,'p95_ms':1,'throughput_rps':1,'error_rate_pct':0,'result':'PASS','evidence_ref':'X','notes':'x'}).status_code==422
    assert c.post('/v90fy/performance/capacity',headers=h,json={'organization_id':org,'environment':'STAGING','db_connections':120,'db_connection_limit':100,'result':'PASS','evidence_ref':'X','notes':'x'}).status_code==422
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
