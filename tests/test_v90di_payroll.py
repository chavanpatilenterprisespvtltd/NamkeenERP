import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert str(d['release']).startswith('v90.') and d['schema_target']>=186
 assert TestClient(app).get('/ui/payroll').status_code==200
def test_payroll_flow():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 emp=c.post('/v90dg/hr/employees',json={'organization_id':o,'entity_id':e,'employee_code':'E-DI','employee_name':'Payroll Worker','hourly_cost':100},headers=h); assert emp.status_code==200
 eid=emp.json()['employee_id']
 assert c.post('/v90di/payroll/periods',json={'organization_id':o,'entity_id':e,'period_code':'2026-09','start_date':'2026-09-01','end_date':'2026-09-30'},headers=h).status_code==200
 pid=c.post('/v90di/payroll/periods',json={'organization_id':o,'entity_id':e,'period_code':'2026-10','start_date':'2026-10-01','end_date':'2026-10-31'},headers=h).json()['period_id']
 assert c.post('/v90di/payroll/compensation',json={'employee_id':eid,'organization_id':o,'entity_id':e,'basic_monthly':10000,'allowances_monthly':2000,'deductions_monthly':1000,'employer_cost_monthly':13000},headers=h).status_code==200
 r=c.post('/v90di/payroll/runs',json={'organization_id':o,'entity_id':e,'period_id':pid},headers=h); assert r.status_code==200; rid=r.json()['run_id']
 calc=c.post(f'/v90di/payroll/runs/{rid}/calculate',headers=h); assert calc.status_code==200 and calc.json()['net_total']==11000
 assert c.post(f'/v90di/payroll/runs/{rid}/approve',headers=h).status_code==200
 jb=c.post(f'/v90di/payroll/runs/{rid}/journal-boundary',headers=h); assert jb.status_code==200 and jb.json()['journal_boundary']=='READY'
