import json, uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=230
 assert TestClient(app).get('/ui/maintenance-reliability-actions').status_code==200

def test_reliability_action_execution_and_benefit():
 c,h=TestClient(app),auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 for day in ['2026-08-02','2026-08-04','2026-09-02']:
  r=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':day+' 08:00:00','duration_minutes':120},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'PREVENTIVE','scheduled_date':'2026-09-03'},headers=h); assert r.status_code==200
 r=c.post('/v90ep/maintenance/risk/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90eq/maintenance/queue/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90es/maintenance/outcome-optimization/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200,r.text
 acts=c.get('/v90es/maintenance/outcome-optimization/actions',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json()['actions']; assert acts
 aid=acts[0]['action_id']
 # Both proposals must be explicitly approved before execution.
 r=c.post(f'/v90es/maintenance/outcome-optimization/actions/{aid}/approve',json={},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90et/maintenance/reliability-actions/execute',json={'action_id':aid,'organization_id':o,'entity_id':e,'period_key':'2026-09','status':'COMPLETED','execution_note':'test execution'},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90et/maintenance/reliability-actions/benefit',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h); assert r.status_code==200,r.text
 j=r.json(); assert j['causal_attribution'] is False; assert 'effectiveness_score' in j
 d=c.get('/v90et/maintenance/reliability-actions/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json(); assert d['completed_count']==1 and d['benefit_count']==1
 assert c.get('/v90et/maintenance/reliability-actions/benefits',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).status_code==200
 assert c.post('/v90et/maintenance/reliability-actions/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h).status_code==200
