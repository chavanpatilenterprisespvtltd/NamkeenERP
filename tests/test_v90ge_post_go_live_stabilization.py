from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_acceptance_requires_closed_go_live_and_all_controls():
    c=TestClient(app); h=_admin(c); org='ge-'+str(uuid4())[:8]
    r=c.post('/v90ge/post-go-live/stabilizations',headers=h,json={'organization_id':org,'period_key':'2026-09','release_version':'v90.gg','environment':'PRODUCTION','business_owner':'Owner','note':'stabilize'}); assert r.status_code==200,r.text; sid=r.json()['stabilization_id']
    r=c.post(f'/v90ge/post-go-live/stabilizations/{sid}/accept',headers=h,json={'evidence_ref':'ACC','note':'should fail'}); assert r.status_code==409
    for code in ('POST_GO_LIVE_HEALTH','CRITICAL_INCIDENTS','DEFECT_DISPOSITION','ROLLBACK_WINDOW_CLOSURE','OPERATIONS_HANDOVER','FINAL_ACCEPTANCE'):
        r=c.post(f'/v90ge/post-go-live/stabilizations/{sid}/controls/{code}',headers=h,json={'status':'PASS','evidence_ref':'EV-'+code,'note':'reviewed'}); assert r.status_code==200,r.text
    r=c.get(f'/v90ge/post-go-live/stabilizations/{sid}/readiness',headers=h); assert r.status_code==200 and r.json()['ready_for_acceptance'] is False

def test_evidence_and_close_gate():
    c=TestClient(app); h=_admin(c); org='ge2-'+str(uuid4())[:8]
    r=c.post('/v90ge/post-go-live/stabilizations',headers=h,json={'organization_id':org,'period_key':'2026-10','release_version':'v90.gg','environment':'PRODUCTION','business_owner':'Owner','note':'stabilize'}); sid=r.json()['stabilization_id']
    r=c.post(f'/v90ge/post-go-live/stabilizations/{sid}/controls/FINAL_ACCEPTANCE',headers=h,json={'status':'PASS','note':'missing'}); assert r.status_code==422
    r=c.post(f'/v90ge/post-go-live/stabilizations/{sid}/close',headers=h,json={'evidence_ref':'CLOSE','note':'not accepted'}); assert r.status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
