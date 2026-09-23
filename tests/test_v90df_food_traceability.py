import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=183
 assert TestClient(app).get('/ui/food-traceability').status_code==200
def test_traceability_flow():
 c=TestClient(app); h=auth(); o,e,b=[str(uuid.uuid4()) for _ in range(3)]
 assert c.post('/v90df/traceability/shelf-life',json={'organization_id':o,'entity_id':e,'product_id':'P1','shelf_days':180},headers=h).status_code==200
 assert c.post(f'/v90df/traceability/batches/{b}/shelf-life',json={'organization_id':o,'entity_id':e,'product_id':'P1','manufactured_on':'2026-09-08'},headers=h).status_code==200
 coa=c.post('/v90df/traceability/coas',json={'organization_id':o,'entity_id':e,'batch_id':b,'coa_no':'COA-1'},headers=h).json()['coa_id']
 assert c.post(f'/v90df/traceability/coas/{coa}/issue',headers=h).status_code==200
 assert c.post(f'/v90df/traceability/batches/{b}/allergens/propagate',json={'organization_id':o,'entity_id':e,'allergen_codes':['PEANUT','MILK']},headers=h).json()['propagated']==2
 assert c.post('/v90df/traceability/recall-impact',json={'organization_id':o,'entity_id':e,'batch_id':b,'reason':'quality review','affected_qty':25},headers=h).status_code==200
 d=c.get('/v90df/traceability/dashboard',params={'organization_id':o,'entity_id':e},headers=h); assert d.status_code==200 and d.json()['open_recall_impacts']==1
