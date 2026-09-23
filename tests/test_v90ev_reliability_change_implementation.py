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
 assert TestClient(app).get('/ui/maintenance-reliability-change').status_code==200

def test_controlled_change_lifecycle():
 c,h=TestClient(app),auth(); o,ei,w=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()); pid=str(uuid.uuid4())
 with engine.begin() as db:
  db.execute(text("INSERT INTO maintenance_reliability_change_proposal(proposal_id,organization_id,entity_id,period_key,work_center_id,change_type,proposed_change,rationale,status,created_by) VALUES(:i,:o,:e,'2026-09',:w,'PM_PLAN_REVIEW','Reduce PM interval','Repeated breakdowns','APPROVED','erpadmin')"),{'i':pid,'o':o,'e':ei,'w':w})
 r=c.post('/v90ev/maintenance/reliability-change/requests',json={'proposal_id':pid,'organization_id':o,'entity_id':ei,'period_key':'2026-09','work_center_id':w},headers=h); assert r.status_code==200,r.text
 # Fetch implementation id from DB because request response intentionally exposes the stable proposal linkage.
 with engine.connect() as db: iid=db.execute(text('SELECT implementation_id FROM maintenance_reliability_change_implementation WHERE proposal_id=:p'),{'p':pid}).scalar_one()
 r=c.post(f'/v90ev/maintenance/reliability-change/{iid}/status',json={'implementation_status':'IN_PROGRESS','implementation_note':'Started'},headers=h); assert r.status_code==200,r.text
 r=c.post(f'/v90ev/maintenance/reliability-change/{iid}/plan-revision',json={'organization_id':o,'entity_id':ei,'period_key':'2026-09','work_center_id':w,'change_reason':'Approved reliability improvement','proposed_frequency_type':'DAYS','proposed_frequency_value':7},headers=h); assert r.status_code==200,r.text
 r=c.post(f'/v90ev/maintenance/reliability-change/{iid}/status',json={'implementation_status':'IMPLEMENTED','evidence_note':'Controlled implementation evidence recorded'},headers=h); assert r.status_code==200,r.text
 r=c.post(f'/v90ev/maintenance/reliability-change/{iid}/benefit',json={'organization_id':o,'entity_id':ei,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h); assert r.status_code==200,r.text and r.json()['causal_attribution'] is False
 r=c.get('/v90ev/maintenance/reliability-change/dashboard',params={'organization_id':o,'entity_id':ei,'period_key':'2026-09'},headers=h); assert r.status_code==200 and r.json()['implemented_count']==1
