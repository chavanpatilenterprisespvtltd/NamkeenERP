import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=184
 assert TestClient(app).get('/ui/hr-workforce').status_code==200
def test_workforce_flow():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 emp=c.post('/v90dg/hr/employees',json={'organization_id':o,'entity_id':e,'employee_code':'E001','employee_name':'Worker 1','hourly_cost':120},headers=h); assert emp.status_code==200
 eid=emp.json()['employee_id']
 sh=c.post('/v90dg/hr/shifts',json={'organization_id':o,'entity_id':e,'shift_code':'A','shift_name':'Morning','start_time':'08:00','end_time':'16:00'},headers=h); assert sh.status_code==200
 att=c.post('/v90dg/hr/attendance',json={'organization_id':o,'entity_id':e,'employee_id':eid,'work_date':'2026-09-08','hours':8},headers=h); assert att.status_code==200
 al=c.post('/v90dg/hr/labour-allocations',json={'organization_id':o,'entity_id':e,'employee_id':eid,'batch_id':'B1','work_date':'2026-09-08','hours':3},headers=h); assert al.status_code==200 and al.json()['cost']==360
 aid=al.json()['allocation_id']; assert c.post(f'/v90dg/hr/labour-allocations/{aid}/approve',headers=h).status_code==200
 d=c.get('/v90dg/hr/dashboard',params={'organization_id':o,'entity_id':e},headers=h); assert d.status_code==200 and d.json()['active_employees']==1
