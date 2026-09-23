from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_deployment_catalog_and_start():
    c=TestClient(app); h=_admin(c)
    r=c.post('/v90fv/deployments',headers=h,json={'organization_id':'fv-'+str(uuid4())[:8],'environment':'STAGING','release_version':'v90.fw','migration_target':247,'change_note':'cutover rehearsal'})
    assert r.status_code==200,r.text; did=r.json()['deployment_id']; assert len(r.json()['control_catalog'])==8
    assert c.post(f'/v90fv/deployments/{did}/start',headers=h).status_code==200

def test_control_requires_evidence():
    c=TestClient(app); h=_admin(c)
    did=c.post('/v90fv/deployments',headers=h,json={'environment':'STAGING','release_version':'v90.fw','migration_target':247,'change_note':'x'}).json()['deployment_id']; c.post(f'/v90fv/deployments/{did}/start',headers=h)
    assert c.post(f'/v90fv/deployments/{did}/controls/ARTIFACT',headers=h,json={'status':'PASS','note':'missing'}).status_code==422

def test_readiness_requires_all_controls_and_rollback():
    c=TestClient(app); h=_admin(c); did=c.post('/v90fv/deployments',headers=h,json={'environment':'STAGING','release_version':'v90.fw','migration_target':247,'change_note':'x'}).json()['deployment_id']; c.post(f'/v90fv/deployments/{did}/start',headers=h)
    s=c.get(f'/v90fv/deployments/{did}/readiness',headers=h).json(); assert s['ready_for_cutover'] is False
    assert c.post(f'/v90fv/deployments/{did}/close',headers=h,json={'signoff_note':'x','evidence_ref':'x'}).status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
