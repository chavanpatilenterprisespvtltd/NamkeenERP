import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=185
 assert TestClient(app).get('/ui/hr-workforce-advanced').status_code==200
def test_advanced_workforce_flow():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 emp=c.post('/v90dg/hr/employees',json={'organization_id':o,'entity_id':e,'employee_code':'E-DH','employee_name':'Worker DH','hourly_cost':100},headers=h); assert emp.status_code==200
 eid=emp.json()['employee_id']
 sh=c.post('/v90dg/hr/shifts',json={'organization_id':o,'entity_id':e,'shift_code':'D','shift_name':'Day','start_time':'08:00','end_time':'16:00'},headers=h); assert sh.status_code==200
 sid=sh.json()['shift_id']
 assert c.post('/v90dh/hr/roster',json={'organization_id':o,'entity_id':e,'employee_id':eid,'shift_id':sid,'work_date':'2026-09-08'},headers=h).status_code==200
 v=c.post('/v90dh/hr/labour-variance',json={'organization_id':o,'entity_id':e,'batch_id':'B-DH','work_date':'2026-09-08','standard_hours':8,'actual_hours':10,'standard_cost':800,'actual_cost':1000},headers=h); assert v.status_code==200 and v.json()['cost_variance']==200
 assert c.post(f"/v90dh/hr/labour-variance/{v.json()['variance_id']}/approve",headers=h).status_code==200
