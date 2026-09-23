import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=177
 assert TestClient(app).get('/ui/manufacturing-scheduling').status_code==200
def test_capacity_exception_and_resolution():
 c=TestClient(app); h=auth(); o,e,w,p=[str(uuid.uuid4()) for _ in range(4)]
 r=c.post('/v90cz/manufacturing/work-centers',json={'organization_id':o,'entity_id':e,'code':'F1','name':'Fryer 1','capacity_per_shift':8,'efficiency_pct':100},headers=h); assert r.status_code==200; wid=r.json()['work_center_id']
 r=c.post('/v90cz/manufacturing/schedule',json={'organization_id':o,'entity_id':e,'production_order_id':str(uuid.uuid4()),'product_id':p,'work_center_id':wid,'schedule_date':'2026-09-08','shift_code':'A','planned_qty':100,'required_hours':10},headers=h); assert r.status_code==200 and r.json()['exception_count']>=1
 sid=r.json()['schedule_id']; assert c.post(f'/v90cz/manufacturing/schedule/{sid}/approve',headers=h).status_code==409
 ex=c.get('/v90cz/manufacturing/dashboard',params={'organization_id':o,'entity_id':e,'start_date':'2026-09-08','end_date':'2026-09-08'},headers=h).json()['open_exceptions']; assert any(x['exception_type']=='CAPACITY_OVERLOAD' for x in ex)
