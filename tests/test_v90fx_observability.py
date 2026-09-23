from fastapi.testclient import TestClient
from app.__main__ import app
from uuid import uuid4

def _admin(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_health_alert_incident_flow():
    c=TestClient(app); h=_admin(c); org='fx-'+str(uuid4())[:8]
    r=c.post('/v90fx/health-checks',headers=h,params={'organization_id':org},json={'check_code':'APP_HEALTH','result':'PASS','evidence_ref':'HC-1','notes':'healthy'}); assert r.status_code==200
    r=c.post('/v90fx/alerts',headers=h,json={'organization_id':org,'severity':'HIGH','alert_code':'LATENCY','message':'latency above threshold'}); assert r.status_code==200; aid=r.json()['alert_id']
    r=c.post('/v90fx/incidents',headers=h,json={'organization_id':org,'severity':'HIGH','title':'Latency incident','description':'Investigate','alert_id':aid}); assert r.status_code==200; iid=r.json()['incident_id']
    assert c.post(f'/v90fx/incidents/{iid}/status',headers=h,json={'status':'ACKNOWLEDGED'}).status_code==200
    assert c.post(f'/v90fx/incidents/{iid}/status',headers=h,json={'status':'RESOLVED','resolution_note':'fixed','evidence_ref':'INC-1'}).status_code==200
    assert c.post(f'/v90fx/incidents/{iid}/status',headers=h,json={'status':'CLOSED','evidence_ref':'INC-2'}).status_code==200

def test_evidence_and_close_gates():
    c=TestClient(app); h=_admin(c); org='fx2-'+str(uuid4())
    assert c.post('/v90fx/health-checks',headers=h,params={'organization_id':org},json={'check_code':'APP_HEALTH','result':'PASS','notes':'x'}).status_code==422
    r=c.get('/v90fx/dashboard',headers=h,params={'organization_id':org}); assert r.status_code==200 and r.json()['operationally_healthy'] is False
    assert c.post('/v90fx/2026-09/close',headers=h,params={'organization_id':org},json={'signoff_note':'x','evidence_ref':'x'}).status_code==409

def test_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==262 and m.filename=='262_v90gk_costing_profitability.sql' for m in ms) and ms[-1].version>=263
