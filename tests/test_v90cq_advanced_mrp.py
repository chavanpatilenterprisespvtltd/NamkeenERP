import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=168
 assert TestClient(app).get('/ui/mrp').status_code==200
def test_mrp_run_lifecycle_without_plan():
 c=TestClient(app); h=auth(); o,e,l=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90cq/mrp/runs',json={'organization_id':o,'entity_id':e,'location_id':l,'run_no':'MRP-001','planning_date':'2026-09-07'},headers=h)
 assert r.status_code==200
 rid=r.json()['mrp_run_id']; x=c.post(f'/v90cq/mrp/runs/{rid}/calculate',headers=h); assert x.status_code==200 and x.json()['status']=='CALCULATED'
 g=c.get(f'/v90cq/mrp/runs/{rid}',headers=h); assert g.status_code==200 and g.json()['run']['status']=='CALCULATED'
 a=c.post(f'/v90cq/mrp/runs/{rid}/approve',json={},headers=h); assert a.status_code==200 and a.json()['status']=='APPROVED'
