import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=169
 assert TestClient(app).get('/ui/replenishment').status_code==200
def test_policy_and_empty_suggest():
 c=TestClient(app); h=auth(); o,e,l,m=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90cr/replenishment/policies',json={'organization_id':o,'entity_id':e,'location_id':l,'material_master_id':m,'uom':'KG','min_qty':100,'max_qty':500,'reorder_point':150,'safety_stock':50,'lead_time_days':7,'order_multiple':25},headers=h); assert r.status_code==200
 s=c.post('/v90cr/replenishment/suggest',json={'organization_id':o,'entity_id':e,'location_id':l},headers=h); assert s.status_code==200
 g=c.get('/v90cr/replenishment/suggestions',params={'organization_id':o,'entity_id':e,'location_id':l},headers=h); assert g.status_code==200
