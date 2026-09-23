from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_certification_requires_all_prerequisites_and_explicit_controls():
    c=TestClient(app); h=_admin(c); org='gc-'+str(uuid4())[:8]
    r=c.post('/v90gc/production-release/certifications',headers=h,json={'organization_id':org,'period_key':'2026-09','release_version':'v90.gd','environment':'PRODUCTION','business_owner':'Owner','note':'release'}); assert r.status_code==200,r.text; cid=r.json()['certification_id']
    r=c.get(f'/v90gc/production-release/certifications/{cid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_certification'] is False
    r=c.post(f'/v90gc/production-release/certifications/{cid}/certify',headers=h,json={'evidence_ref':'CERT','note':'should fail'}); assert r.status_code==409
    for code in ('PERFORMANCE_READINESS','UAT_CERTIFICATION','DEPLOYMENT_READINESS','BACKUP_DR','OPERATIONAL_HEALTH'):
        r=c.post(f'/v90gc/production-release/certifications/{cid}/controls/{code}',headers=h,json={'status':'PASS','evidence_ref':'EV-'+code,'note':'reviewed'}); assert r.status_code==200,r.text
    r=c.post(f'/v90gc/production-release/certifications/{cid}/business-signoff',headers=h,json={'evidence_ref':'OWNER-SIGN','note':'approved'}); assert r.status_code==200
    r=c.get(f'/v90gc/production-release/certifications/{cid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_certification'] is False

def test_evidence_and_unknown_control():
    c=TestClient(app); h=_admin(c); org='gc2-'+str(uuid4())[:8]
    r=c.post('/v90gc/production-release/certifications',headers=h,json={'organization_id':org,'period_key':'2026-10','release_version':'v90.gd','environment':'PRODUCTION','business_owner':'Owner','note':'release'}); cid=r.json()['certification_id']
    r=c.post(f'/v90gc/production-release/certifications/{cid}/controls/PERFORMANCE_READINESS',headers=h,json={'status':'PASS','note':'missing'}); assert r.status_code==422
    r=c.post(f'/v90gc/production-release/certifications/{cid}/controls/UNKNOWN',headers=h,json={'status':'FAIL','note':'bad'}); assert r.status_code==422

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
