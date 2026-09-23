from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_production_readiness_gate_requires_all_explicit_checks():
    c=TestClient(app); h=_admin(c); org='gb-'+str(uuid4())[:8]
    r=c.post('/v90gb/performance/production-readiness/gates',headers=h,json={'organization_id':org,'period_key':'2026-09','release_version':'v90.gb','environment':'staging','note':'gate'}); assert r.status_code==200; gid=r.json()['gate_id']
    r=c.get(f'/v90gb/performance/production-readiness/gates/{gid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_production'] is False
    r=c.post(f'/v90gb/performance/production-readiness/gates/{gid}/certify',headers=h,json={'evidence_ref':'CERT','note':'should fail'}); assert r.status_code==409
    for code in ('PERFORMANCE_GATE','UAT_CERTIFICATION','DEPLOYMENT_CUTOVER','BACKUP_DR','OBSERVABILITY','NO_CRITICAL_ALERTS'):
        r=c.post(f'/v90gb/performance/production-readiness/gates/{gid}/checks/{code}',headers=h,json={'status':'PASS','evidence_ref':'EV-'+code,'note':'reviewed'}); assert r.status_code==200
    r=c.get(f'/v90gb/performance/production-readiness/gates/{gid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_production'] is False

def test_pass_or_waived_requires_evidence_and_unknown_check_rejected():
    c=TestClient(app); h=_admin(c); org='gb2-'+str(uuid4())[:8]
    r=c.post('/v90gb/performance/production-readiness/gates',headers=h,json={'organization_id':org,'period_key':'2026-10','release_version':'v90.gb','environment':'staging','note':'gate'}); assert r.status_code==200; gid=r.json()['gate_id']
    r=c.post(f'/v90gb/performance/production-readiness/gates/{gid}/checks/PERFORMANCE_GATE',headers=h,json={'status':'PASS','note':'missing evidence'}); assert r.status_code==422
    r=c.post(f'/v90gb/performance/production-readiness/gates/{gid}/checks/UNKNOWN',headers=h,json={'status':'FAIL','note':'bad'}); assert r.status_code==422

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
