from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_final_closure_requires_post_go_live_and_controls():
    c=TestClient(app); h=_admin(c); org='gf-'+str(uuid4())[:8]
    r=c.post('/v90gf/go-live-closures',headers=h,json={'organization_id':org,'period_key':'2026-09','release_version':'v90.gg','environment':'PRODUCTION','business_owner':'Owner','support_owner':'Ops','note':'final'}); assert r.status_code==200,r.text; cid=r.json()['closure_id']
    r=c.post(f'/v90gf/go-live-closures/{cid}/accept',headers=h,json={'evidence_ref':'ACC','note':'should fail'}); assert r.status_code==409
    for code in ('POST_GO_LIVE_CLOSED','OPEN_CRITICALS','DEFECT_EXCEPTION_REGISTER','ROLLBACK_WINDOW_CLOSED','OPERATIONS_HANDOVER','BUSINESS_ACCEPTANCE'):
        r=c.post(f'/v90gf/go-live-closures/{cid}/controls/{code}',headers=h,json={'status':'PASS','evidence_ref':'EV-'+code,'note':'reviewed'}); assert r.status_code==200,r.text
    r=c.get(f'/v90gf/go-live-closures/{cid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_final_closure'] is False

def test_defect_requires_evidence_and_close_order():
    c=TestClient(app); h=_admin(c); org='gf2-'+str(uuid4())[:8]
    r=c.post('/v90gf/go-live-closures',headers=h,json={'organization_id':org,'period_key':'2026-10','release_version':'v90.gg','environment':'PRODUCTION','business_owner':'Owner','support_owner':'Ops','note':'final'}); cid=r.json()['closure_id']
    r=c.post(f'/v90gf/go-live-closures/{cid}/defects',headers=h,json={'defect_ref':'D-1','severity':'HIGH','disposition':'DEFERRED','evidence_ref':'E1','note':'approved exception evidence'}); assert r.status_code==200
    r=c.post(f'/v90gf/go-live-closures/{cid}/close',headers=h,json={'evidence_ref':'CLOSE','note':'not accepted'}); assert r.status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
