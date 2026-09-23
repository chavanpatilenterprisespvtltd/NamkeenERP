from fastapi.testclient import TestClient
from app.__main__ import app, engine
from sqlalchemy import text
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_scan_creates_coverage_gaps():
    c=TestClient(app); h=_admin(c); org='fr-'+str(uuid4())[:8]
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by) VALUES('erpadmin',:o,1,'erpadmin') ON CONFLICT(user_id,organization_id) DO UPDATE SET active=1"),{'o':org})
    r=c.post('/v90fr/governance/coverage/scan',headers=h,params={'organization_id':org}); assert r.status_code==200,r.text
    d=r.json(); assert d['total_actions']==12 and d['open_gaps']>=1 and d['coverage_percent']<100

def test_gap_resolution_requires_evidence():
    c=TestClient(app); h=_admin(c); org='frx-'+str(uuid4())[:8]
    r=c.post('/v90fr/governance/coverage/scan',headers=h,params={'organization_id':org}); assert r.status_code==200
    gap=c.get('/v90fr/governance/coverage/gaps',headers=h,params={'organization_id':org}).json()['gaps'][0]['gap_id']
    assert c.post(f'/v90fr/governance/coverage/gaps/{gap}/resolve',headers=h,json={'resolution_note':'fixed'}).status_code==422
    assert c.post(f'/v90fr/governance/coverage/gaps/{gap}/resolve',headers=h,json={'resolution_note':'policy and certification restored','evidence_ref':'UT-FR-1'}).status_code==200

def test_dashboard_and_ui():
    c=TestClient(app); h=_admin(c); assert c.get('/v90fr/governance/coverage/dashboard',headers=h).status_code==200; assert c.get('/ui/governance-coverage-remediation').status_code==200

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
