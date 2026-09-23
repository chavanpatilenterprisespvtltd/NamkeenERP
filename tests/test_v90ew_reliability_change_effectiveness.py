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
 assert TestClient(app).get('/ui/maintenance-reliability-change-effectiveness').status_code==200

def test_effectiveness_feedback_and_governance_link():
 c,h=TestClient(app),auth(); o,ei,w=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()); pid,iid=str(uuid.uuid4()),str(uuid.uuid4())
 with engine.begin() as db:
  db.execute(text("INSERT INTO maintenance_reliability_governance_snapshot(governance_id,organization_id,entity_id,period_key,target_effectiveness_score,target_breakdown_reduction_pct,target_downtime_reduction_hours,target_maintenance_cost_impact,created_by) VALUES(:g,:o,:e,'2026-09',60,20,2,100,'erpadmin')"),{'g':str(uuid.uuid4()),'o':o,'e':ei})
  db.execute(text("INSERT INTO maintenance_reliability_change_proposal(proposal_id,organization_id,entity_id,period_key,work_center_id,change_type,proposed_change,rationale,status,created_by) VALUES(:p,:o,:e,'2026-09',:w,'PM_PLAN_REVIEW','Tighten PM','Reliability','APPROVED','erpadmin')"),{'p':pid,'o':o,'e':ei,'w':w})
  db.execute(text("INSERT INTO maintenance_reliability_change_implementation(implementation_id,proposal_id,organization_id,entity_id,period_key,change_type,implementation_status,breakdown_reduction_pct,downtime_reduction_hours,maintenance_cost_impact,effectiveness_score,benefit_status,created_by) VALUES(:i,:p,:o,:e,'2026-09','PM_PLAN_REVIEW','IMPLEMENTED',10,1,50,40,'IMPROVEMENT_OBSERVED','erpadmin')"),{'i':iid,'p':pid,'o':o,'e':ei})
 r=c.post('/v90ew/maintenance/reliability-change/effectiveness/snapshot',json={'organization_id':o,'entity_id':ei,'period_key':'2026-09'},headers=h); assert r.status_code==200,r.text; assert r.json()['failed_change_count']==1
 with engine.connect() as db: ef=db.execute(text('SELECT effectiveness_id FROM maintenance_reliability_change_effectiveness_snapshot WHERE implementation_id=:i'),{'i':iid}).scalar_one()
 r=c.get('/v90ew/maintenance/reliability-change/effectiveness/dashboard',params={'organization_id':o,'entity_id':ei,'period_key':'2026-09'},headers=h); assert r.status_code==200 and r.json()['failed_change_count']==1
 r=c.post(f'/v90ew/maintenance/reliability-change/effectiveness/{ef}/feedback',json={'feedback_type':'MANAGEMENT_REVIEW','recommendation':'Review PM frequency','rationale':'Target was not met','priority':'HIGH'},headers=h); assert r.status_code==200,r.text
 with engine.connect() as db: fid=db.execute(text('SELECT feedback_id FROM maintenance_reliability_improvement_feedback WHERE effectiveness_id=:e AND feedback_type=:t'),{'e':ef,'t':'MANAGEMENT_REVIEW'}).scalar_one()
 r=c.post(f'/v90ew/maintenance/reliability-change/effectiveness/feedback/{fid}/governance-proposal',json={'target_value':70},headers=h); assert r.status_code==200,r.text; assert r.json()['governance_approval_required'] is True
 r=c.get('/v90ew/maintenance/reliability-change/effectiveness/queue',params={'organization_id':o,'entity_id':ei,'period_key':'2026-09'},headers=h); assert r.status_code==200 and r.json()['count']==1
