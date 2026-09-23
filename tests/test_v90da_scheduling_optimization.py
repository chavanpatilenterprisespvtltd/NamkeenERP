import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=178
 assert TestClient(app).get('/ui/manufacturing-scheduling-optimization').status_code==200
def test_routing_optimization_and_capacity_exception():
 c=TestClient(app); h=auth(); o,e,p,w=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90da/manufacturing/routings',json={'organization_id':o,'entity_id':e,'product_id':p,'version_code':'1'},headers=h); assert r.status_code==200; rid=r.json()['routing_id']
 r=c.post(f'/v90da/manufacturing/routings/{rid}/operations',json={'sequence_no':10,'operation_code':'FRY','operation_name':'Frying','work_center_id':w,'setup_hours':1,'run_hours_per_unit':.1},headers=h); assert r.status_code==200
 r=c.post('/v90cz/manufacturing/work-centers',json={'organization_id':o,'entity_id':e,'code':'FRY-1','name':'Fryer','capacity_per_shift':2,'efficiency_pct':100},headers=h); assert r.status_code==200; wc=r.json()['work_center_id']
 # Reuse routing operation's work-center identity by creating compatibility on actual wc and a second operation on it.
 r=c.post(f'/v90da/manufacturing/routings/{rid}/operations',json={'sequence_no':20,'operation_code':'PACK','operation_name':'Packing','work_center_id':wc,'setup_hours':0.5,'run_hours_per_unit':.1},headers=h); assert r.status_code==200
 r=c.post('/v90da/manufacturing/optimize',json={'organization_id':o,'entity_id':e,'production_order_id':str(uuid.uuid4()),'product_id':p,'planned_qty':100,'scheduled_date':'2026-09-08','due_date':'2026-09-09','shift_code':'A'},headers=h); assert r.status_code==200 and r.json()['operation_count']==2 and r.json()['exception_count']>=1
