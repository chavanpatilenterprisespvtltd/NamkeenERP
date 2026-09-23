import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=175
 assert TestClient(app).get('/ui/manufacturing-loss-yield').status_code==200
def test_variance_byproduct_benchmark():
 c=TestClient(app); h=auth(); o,e,b,p,g=[str(uuid.uuid4()) for _ in range(5)]
 r=c.post('/v90cx/manufacturing/consumption-variance',json={'organization_id':o,'entity_id':e,'batch_id':b,'product_id':p,'ingredient_id':g,'standard_qty':100,'actual_qty':106,'unit_cost':50},headers=h)
 assert r.status_code==200 and r.json()['variance_qty']==6 and r.json()['variance_value']==300
 vid=r.json()['variance_id']; assert c.post(f'/v90cx/manufacturing/variance/{vid}/approve',headers=h).json()['status']=='APPROVED'
 r=c.post('/v90cx/manufacturing/byproduct',json={'organization_id':o,'entity_id':e,'batch_id':b,'product_id':p,'byproduct_item_id':g,'quantity':4,'valuation_rate':25},headers=h)
 assert r.status_code==200 and r.json()['valuation_value']==100
 r=c.post('/v90cw/manufacturing/batch-cost',json={'organization_id':o,'entity_id':e,'batch_id':b,'product_id':p,'period_key':'2026-09','planned_qty':100,'good_qty':90,'wastage_qty':10,'material_cost':4500,'standard_cost':5000},headers=h); assert r.status_code==200
 r=c.post('/v90cx/manufacturing/yield-benchmark/rebuild',json={'organization_id':o,'entity_id':e,'product_id':p,'period_key':'2026-09'},headers=h)
 assert r.status_code==200 and r.json()['batch_count']==1 and round(r.json()['avg_yield_pct'],2)==90
