import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app,engine
from sqlalchemy import text
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}

def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=266
 assert TestClient(app).get('/ui/maintenance-reliability-governance-control').status_code==200

def test_control_exception_resolution_and_close():
 c,h=TestClient(app),auth(); o,ei,w=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()); pid,iid=str(uuid.uuid4()),str(uuid.uuid4())
 with engine.begin() as db:
  db.execute(text("INSERT INTO maintenance_reliability_governance_snapshot(governance_id,organization_id,entity_id,period_key,target_effectiveness_score,governance_score,created_by) VALUES(:g,:o,:e,'2026-09',70,55,'erpadmin')"),{'g':str(uuid.uuid4()),'o':o,'e':ei})
  db.execute(text("INSERT INTO maintenance_reliability_change_effectiveness_snapshot(effectiveness_id,implementation_id,proposal_id,organization_id,entity_id,period_key,work_center_id,target_effectiveness_score,actual_effectiveness_score,target_met,failure_flag,repeat_failure_count,recommendation,created_by) VALUES(:ef,:i,:p,:o,:e,'2026-09',:w,70,40,0,1,1,'Review repeat failure','erpadmin')"),{'ef':str(uuid.uuid4()),'i':iid,'p':pid,'o':o,'e':ei,'w':w})
 r=c.post('/v90ex/maintenance/reliability-governance/control/snapshot',json={'organization_id':o,'entity_id':ei,'period_key':'2026-09'},headers=h); assert r.status_code==200,r.text; assert r.json()['assessment']=='ESCALATE' and r.json()['critical_exception_count']==1
 r=c.get('/v90ex/maintenance/reliability-governance/control/dashboard',params={'organization_id':o,'entity_id':ei,'period_key':'2026-09'},headers=h); assert r.status_code==200 and len(r.json()['exceptions'])==1
 ex=r.json()['exceptions'][0]['exception_id']
 r=c.post(f'/v90ex/maintenance/reliability-governance/control/exceptions/{ex}/resolve',json={'resolution_note':'Reviewed and assigned corrective action'},headers=h); assert r.status_code==200
 r=c.post('/v90ex/maintenance/reliability-governance/2026-09/close',json={'organization_id':o,'entity_id':ei,'closure_note':'Management review complete'},headers=h); assert r.status_code==200,r.text and r.json()['status']=='CLOSED'
