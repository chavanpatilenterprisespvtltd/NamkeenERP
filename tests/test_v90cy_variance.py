import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=176
 assert TestClient(app).get('/ui/manufacturing-variance').status_code==200
def test_variance_shift_dashboard():
 c=TestClient(app); h=auth(); o,e,b,p=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90cy/manufacturing/variance',json={'organization_id':o,'entity_id':e,'batch_id':b,'product_id':p,'period_key':'2026-09','variance_type':'MATERIAL','standard_value':5000,'actual_value':5300,'reason':'excess consumption'},headers=h)
 assert r.status_code==200 and r.json()['variance_value']==300 and round(r.json()['variance_pct'],2)==6
 vid=r.json()['variance_id']; assert c.post(f'/v90cy/manufacturing/variance/{vid}/approve',headers=h).json()['status']=='APPROVED'
 r=c.post('/v90cy/manufacturing/shift-performance',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','shift_code':'A','batch_count':3,'good_qty':950,'wastage_qty':50,'total_variance_value':300},headers=h)
 assert r.status_code==200 and round(r.json()['avg_yield_pct'],2)==95
 r=c.get('/v90cy/manufacturing/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h)
 assert r.status_code==200 and r.json()['variance_summary'][0]['variance_type']=='MATERIAL'
