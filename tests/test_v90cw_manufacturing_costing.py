import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=174
 assert TestClient(app).get('/ui/manufacturing-costing').status_code==200
def test_batch_cost_and_adjustment():
 c=TestClient(app); h=auth(); o,e,b,p=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90cw/manufacturing/batch-cost',json={'organization_id':o,'entity_id':e,'batch_id':b,'product_id':p,'period_key':'2026-09','planned_qty':100,'good_qty':90,'rework_qty':5,'wastage_qty':5,'byproduct_qty':2,'material_cost':5000,'packaging_cost':500,'labor_cost':800,'overhead_cost':700,'rework_cost':100,'standard_cost':7000},headers=h)
 assert r.status_code==200 and round(r.json()['total_cost'],2)==7100 and round(r.json()['yield_pct'],2)==90
 r=c.get('/v90cw/manufacturing/batch-cost',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200 and len(r.json()['batch_costs'])==1
 r=c.post('/v90cw/manufacturing/adjustment',json={'organization_id':o,'entity_id':e,'batch_id':b,'adjustment_type':'WASTAGE_RECLASS','amount':125,'reason':'verified process loss'},headers=h); assert r.status_code==200
 aid=r.json()['adjustment_id']; assert c.post(f'/v90cw/manufacturing/adjustment/{aid}/approve',headers=h).json()['status']=='APPROVED'
