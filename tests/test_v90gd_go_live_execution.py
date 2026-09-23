from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_go_live_requires_gc_and_uat_prerequisites():
    c=TestClient(app); h=_admin(c); org='gd-'+str(uuid4())[:8]
    r=c.post('/v90gd/go-live/executions',headers=h,json={'organization_id':org,'period_key':'2026-09','release_version':'v90.gd','environment':'PRODUCTION','business_owner':'Owner','note':'go-live'}); assert r.status_code==200,r.text; gid=r.json()['go_live_id']
    r=c.post(f'/v90gd/go-live/executions/{gid}/approve',headers=h,json={'evidence_ref':'APP','note':'must fail'}); assert r.status_code==409
    for code in ('RELEASE_CERTIFICATION','END_TO_END_UAT','PRODUCTION_CUTOVER','ROLLBACK_DECISION','OPERATIONAL_ACCEPTANCE'):
        r=c.post(f'/v90gd/go-live/executions/{gid}/controls/{code}',headers=h,json={'status':'PASS','evidence_ref':'EV-'+code,'note':'reviewed'}); assert r.status_code==200,r.text
    r=c.post(f'/v90gd/go-live/executions/{gid}/controls/BUSINESS_SIGNOFF',headers=h,json={'status':'PASS','evidence_ref':'OWNER','note':'signed'}); assert r.status_code==200
    r=c.get(f'/v90gd/go-live/executions/{gid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_go_live'] is False

def test_evidence_and_close_gate():
    c=TestClient(app); h=_admin(c); org='gd2-'+str(uuid4())[:8]
    r=c.post('/v90gd/go-live/executions',headers=h,json={'organization_id':org,'period_key':'2026-10','release_version':'v90.gd','environment':'PRODUCTION','business_owner':'Owner','note':'go-live'}); gid=r.json()['go_live_id']
    r=c.post(f'/v90gd/go-live/executions/{gid}/controls/PRODUCTION_CUTOVER',headers=h,json={'status':'PASS','note':'missing evidence'}); assert r.status_code==422
    r=c.post(f'/v90gd/go-live/executions/{gid}/close',headers=h,json={'evidence_ref':'CLOSE','note':'not approved'}); assert r.status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
