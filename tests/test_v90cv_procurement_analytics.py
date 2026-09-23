import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=173
 assert TestClient(app).get('/ui/procurement-analytics').status_code==200
def test_analytics_recommendation():
 c=TestClient(app); h=auth(); o,e,s,m=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90cv/procurement/supplier-analytics',json={'organization_id':o,'entity_id':e,'supplier_id':s,'period_key':'2026-09','spend_value':100000,'ppv_value':-2500,'purchase_qty':5000,'contracted_rate':20,'actual_rate':20.5,'landed_cost':21,'otif_pct':95,'quality_rejection_pct':2,'dependency_pct':30,'savings_value':5000},headers=h); assert r.status_code==200 and r.json()['savings_value']==5000
 r=c.get('/v90cv/procurement/supplier-analytics',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200 and len(r.json()['analytics'])==1
 r=c.post('/v90cv/procurement/recommendation',json={'organization_id':o,'entity_id':e,'item_master_id':m,'supplier_id':s,'period_key':'2026-09','score':91},headers=h); assert r.status_code==200
 rid=r.json()['recommendation_id']; assert c.post(f'/v90cv/procurement/recommendation/{rid}/approve',headers=h).json()['status']=='APPROVED'
