import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=230
 assert TestClient(app).get('/ui/maintenance-risk').status_code==200
def test_predictive_risk_ranking_and_close():
 c,h=TestClient(app),auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 for day in ['2026-08-05','2026-08-15']:
  c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'BREAKDOWN','scheduled_date':day},headers=h)
 for day in ['2026-09-02','2026-09-05','2026-09-10','2026-09-15']:
  c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'BREAKDOWN','scheduled_date':day},headers=h)
 for day in ['2026-09-02','2026-09-10']:
  c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'PREVENTIVE','scheduled_date':day},headers=h)
 for day in ['2026-09-02','2026-09-05','2026-09-10','2026-09-15']:
  r=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':day+' 10:00:00','duration_minutes':120},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90ep/maintenance/risk/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h); assert r.status_code==200,r.text
 j=r.json(); assert j['breakdown_orders']==4 and j['prior_breakdown_orders']==2 and j['risk_level']=='CRITICAL'
 assert c.get('/v90ep/maintenance/risk/ranking',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).status_code==200
 assert c.get('/v90ep/maintenance/risk/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json()['critical_count']==1
 assert c.get('/v90ep/maintenance/risk/trend',params={'organization_id':o,'entity_id':e},headers=h).status_code==200
 assert c.post('/v90ep/maintenance/risk/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h).status_code==200
 assert c.post('/v90ep/maintenance/risk/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).status_code==409
