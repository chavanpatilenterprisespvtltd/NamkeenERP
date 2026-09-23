from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4


def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_sla_policy_breach_lifecycle_and_dashboard():
    c=TestClient(app); h=_admin(c); org='gh-'+str(uuid4())[:8]
    r=c.post('/v90gh/sla/policies',headers=h,json={'organization_id':org,'policy_code':'INC-CRIT-30','service_area':'Operations','target_minutes':30,'severity':'CRITICAL','note':'critical incident target'}); assert r.status_code==200,r.text; pid=r.json()['policy_id']
    r=c.post('/v90gh/sla/breaches',headers=h,params={'organization_id':org},json={'policy_id':pid,'reference_type':'INCIDENT','reference_id':'INC-1','opened_at':'2026-09-10T10:00:00','due_at':'2999-01-01T10:30:00','severity':'CRITICAL','description':'test breach'}); assert r.status_code==200,r.text; bid=r.json()['breach_id']
    d=c.get('/v90gh/sla/dashboard',headers=h,params={'organization_id':org}); assert d.status_code==200 and d.json()['critical_open_breaches']==1
    assert c.post(f'/v90gh/sla/breaches/{bid}/status',headers=h,json={'status':'CLOSED','note':'early'}).status_code==422
    assert c.post(f'/v90gh/sla/breaches/{bid}/status',headers=h,json={'status':'CLOSED','evidence_ref':'EARLY','note':'early'}).status_code==409
    assert c.post(f'/v90gh/sla/breaches/{bid}/status',headers=h,json={'status':'MITIGATED','note':'mitigated'}).status_code==200
    assert c.post(f'/v90gh/sla/breaches/{bid}/status',headers=h,json={'status':'CLOSED','note':'closed'}).status_code==422
    assert c.post(f'/v90gh/sla/breaches/{bid}/status',headers=h,json={'status':'CLOSED','evidence_ref':'EV-1','note':'closed with evidence'}).status_code==200
    d=c.get('/v90gh/sla/dashboard',headers=h,params={'organization_id':org}); assert d.json()['critical_open_breaches']==0


def test_sla_review_records_target_and_duplicate_is_blocked():
    c=TestClient(app); h=_admin(c); org='gh2-'+str(uuid4())[:8]
    payload={'period_key':'2026-09','organization_id':org,'service_area':'Support','target_compliance_pct':95,'actual_compliance_pct':92,'evidence_ref':'REV-1','note':'target miss'}
    r=c.post('/v90gh/sla/reviews',headers=h,json=payload); assert r.status_code==200 and r.json()['within_target'] is False
    assert c.post('/v90gh/sla/reviews',headers=h,json=payload).status_code==409


def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
