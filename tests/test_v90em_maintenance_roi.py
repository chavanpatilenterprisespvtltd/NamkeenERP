import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=230
 assert TestClient(app).get('/ui/maintenance-roi').status_code==200
def test_roi_snapshot_and_close():
 c,h=TestClient(app),auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 # baseline: 400 breakdown cost, 4h breakdown
 oid=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'BREAKDOWN','scheduled_date':'2026-08-10'},headers=h).json()['order_id']
 c.post('/v90ei/maintenance/labour-charges',json={'organization_id':o,'entity_id':e,'maintenance_order_id':oid,'work_center_id':w,'labour_category':'TECH','charge_date':'2026-08-10','regular_hours':4,'regular_rate':100},headers=h)
 c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':'2026-08-10 10:00:00','duration_minutes':240},headers=h)
 # current: 200 preventive cost, 100 breakdown cost, 1h breakdown
 po=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'PREVENTIVE','scheduled_date':'2026-09-10'},headers=h).json()['order_id']
 c.post('/v90ei/maintenance/labour-charges',json={'organization_id':o,'entity_id':e,'maintenance_order_id':po,'work_center_id':w,'labour_category':'TECH','charge_date':'2026-09-10','regular_hours':2,'regular_rate':100},headers=h)
 bo=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'BREAKDOWN','scheduled_date':'2026-09-12'},headers=h).json()['order_id']
 c.post('/v90ei/maintenance/labour-charges',json={'organization_id':o,'entity_id':e,'maintenance_order_id':bo,'work_center_id':w,'labour_category':'TECH','charge_date':'2026-09-12','regular_hours':1,'regular_rate':100},headers=h)
 c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':'2026-09-10 10:00:00','duration_minutes':60},headers=h)
 r=c.post('/v90em/maintenance/roi/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h)
 assert r.status_code==200,r.text; j=r.json(); assert j['avoided_breakdown_cost']==300.0 and j['breakdown_hours_reduction_pct']==75.0 and j['preventive_roi_pct']==50.0
 assert c.get('/v90em/maintenance/roi/compare',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).status_code==200
 assert c.post('/v90em/maintenance/roi/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h).status_code==200
 assert c.post('/v90em/maintenance/roi/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).status_code==409
