import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=180
 assert TestClient(app).get('/ui/maintenance').status_code==200
def test_maintenance_flow():
 c=TestClient(app); h=auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 r=c.post('/v90dc/maintenance/plans',json={'organization_id':o,'entity_id':e,'work_center_id':w,'plan_name':'Monthly PM','frequency_type':'CALENDAR','frequency_value':1,'next_due_date':'2026-09-08'},headers=h); assert r.status_code==200
 oid=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'scheduled_date':'2026-09-09','downtime_hours':2},headers=h).json()['order_id']
 assert c.post(f'/v90dc/maintenance/orders/{oid}/approve',headers=h).status_code==200
 assert c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','duration_minutes':30},headers=h).status_code==200
 assert c.post('/v90dc/maintenance/spares',json={'organization_id':o,'entity_id':e,'work_center_id':w,'material_id':'SPARE-1','quantity':2,'unit_cost':50},headers=h).status_code==200
 d=c.get('/v90dc/maintenance/dashboard',params={'organization_id':o,'entity_id':e},headers=h); assert d.status_code==200 and d.json()['breakdown_minutes']==30 and d.json()['maintenance_cost']==100
