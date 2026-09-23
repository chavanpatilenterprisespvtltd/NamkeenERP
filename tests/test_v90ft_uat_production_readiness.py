from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_plan_catalog_and_execution():
    c=TestClient(app); h=_admin(c); org='ft-'+str(uuid4())[:8]
    r=c.post('/v90ft/uat/plans',headers=h,json={'organization_id':org,'period_key':'2026-09','name':'FT UAT'})
    assert r.status_code==200,r.text; pid=r.json()['plan_id']; assert len(r.json()['scenario_catalog'])==12
    assert c.post(f'/v90ft/uat/plans/{pid}/start',headers=h).status_code==200
    r=c.post(f'/v90ft/uat/plans/{pid}/execute',headers=h,json={'scenario_code':'SALES_TO_AR','result':'PASS','evidence_ref':'UAT-1','notes':'verified'})
    assert r.status_code==200,r.text

def test_pass_requires_evidence_and_unknown_scenario_rejected():
    c=TestClient(app); h=_admin(c); org='ft2-'+str(uuid4())
    pid=c.post('/v90ft/uat/plans',headers=h,json={'organization_id':org,'period_key':'2026-09','name':'Evidence'}).json()['plan_id']
    c.post(f'/v90ft/uat/plans/{pid}/start',headers=h)
    assert c.post(f'/v90ft/uat/plans/{pid}/execute',headers=h,json={'scenario_code':'SALES_TO_AR','result':'PASS','notes':'no evidence'}).status_code==422
    assert c.post(f'/v90ft/uat/plans/{pid}/execute',headers=h,json={'scenario_code':'NOPE','result':'FAIL','notes':'x'}).status_code==422

def test_readiness_requires_full_gate():
    c=TestClient(app); h=_admin(c); org='ft3-'+str(uuid4())
    pid=c.post('/v90ft/uat/plans',headers=h,json={'organization_id':org,'period_key':'2026-09','name':'Gate'}).json()['plan_id']; c.post(f'/v90ft/uat/plans/{pid}/start',headers=h)
    s=c.get(f'/v90ft/uat/plans/{pid}/production-readiness',headers=h); assert s.status_code==200 and s.json()['ready_for_certification'] is False
    assert c.post(f'/v90ft/uat/plans/{pid}/certify',headers=h,json={'signoff_note':'attempt','evidence_ref':'x'}).status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
