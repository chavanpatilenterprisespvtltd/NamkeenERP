import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=230
 assert TestClient(app).get('/ui/maintenance-reliability-governance').status_code==200
def test_governance_and_change_proposal():
 c,h=TestClient(app),auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 for day in ['2026-08-02','2026-08-04','2026-09-02']:
  r=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':day+' 08:00:00','duration_minutes':120},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90ep/maintenance/risk/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h); assert r.status_code==200,r.text
 # Seed an approved V90.es action through the existing cumulative table.
 from app.__main__ import engine
 aid=str(uuid.uuid4())
 from sqlalchemy import text
 with engine.begin() as db:
  db.execute(text("INSERT INTO maintenance_reliability_action(action_id,organization_id,entity_id,period_key,work_center_id,action_type,recommendation,rationale,confidence,status,created_by) VALUES(:i,:o,:e,:p,:w,'PM_STRATEGY','Review PM interval','Governance test','HIGH','APPROVED','erpadmin')"),{'i':aid,'o':o,'e':e,'p':'2026-09','w':w})
 r=c.post('/v90et/maintenance/reliability-actions/execute',json={'action_id':aid,'organization_id':o,'entity_id':e,'period_key':'2026-09','status':'COMPLETED'},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90et/maintenance/reliability-actions/benefit',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90eu/maintenance/reliability-governance/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','target_effectiveness_score':60},headers=h); assert r.status_code==200,r.text
 j=r.json(); assert 'governance_score' in j and j['causal_attribution'] is False
 r=c.post('/v90eu/maintenance/reliability-governance/change-proposals',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','change_type':'PM_PLAN_REVIEW','proposed_change':'Review PM interval for work center','rationale':'Governance review'},headers=h); assert r.status_code==200,r.text
 pid=r.json()['proposal_id']; r=c.post(f'/v90eu/maintenance/reliability-governance/change-proposals/{pid}/approve',json={'decision_note':'approved for controlled review'},headers=h); assert r.status_code==200,r.text
 r=c.get('/v90eu/maintenance/reliability-governance/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200 and len(r.json()['proposals'])==1
 r=c.post('/v90eu/maintenance/reliability-governance/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h); assert r.status_code==200
