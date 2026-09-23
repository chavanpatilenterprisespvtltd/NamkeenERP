import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app,engine
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=172
 assert TestClient(app).get('/ui/procurement-commercial').status_code==200
def test_ppv_score_rebate_budget():
 c=TestClient(app); h=auth(); o,e,s,m=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90cu/procurement/ppv',json={'organization_id':o,'entity_id':e,'supplier_id':s,'item_master_id':m,'qty':100,'baseline_rate':20,'actual_rate':22},headers=h); assert r.status_code==200 and r.json()['variance_value']==200
 r=c.post('/v90cu/procurement/supplier-scorecard',json={'organization_id':o,'entity_id':e,'supplier_id':s,'period_key':'2026-09','on_time_pct':90,'quality_accept_pct':95,'price_score':80,'service_score':85},headers=h); assert r.status_code==200 and r.json()['overall_score']==87.5
 r=c.post('/v90cu/procurement/rebate-settlement',json={'organization_id':o,'entity_id':e,'supplier_id':s,'period_key':'2026-09','eligible_qty':1000,'rebate_pct':2,'eligible_value':50000},headers=h); assert r.status_code==200 and r.json()['rebate_value']==1000
 rid=r.json()['settlement_id']; assert c.post(f'/v90cu/procurement/rebate-settlement/{rid}/approve',headers=h).json()['status']=='APPROVED'
 r=c.post('/v90cu/procurement/budget-control',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','budget_value':100000,'committed_value':30000,'actual_value':20000},headers=h); assert r.status_code==200 and r.json()['available_value']==50000
