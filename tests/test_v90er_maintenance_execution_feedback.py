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
 assert TestClient(app).get('/ui/maintenance-execution-feedback').status_code==200

def test_execution_feedback_learning_loop():
 c,h=TestClient(app),auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 for day in ['2026-09-02','2026-09-03','2026-09-04','2026-09-06']:
  r=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'BREAKDOWN','scheduled_date':day},headers=h); assert r.status_code==200,r.text
  r=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':day+' 08:00:00','duration_minutes':120},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90dc/maintenance/orders',json={'organization_id':o,'entity_id':e,'work_center_id':w,'order_type':'PREVENTIVE','scheduled_date':'2026-09-05'},headers=h); assert r.status_code==200,r.text
 oid=r.json()['order_id']
 r=c.post('/v90ep/maintenance/risk/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','baseline_period_key':'2026-08','work_center_id':w},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90eq/maintenance/queue/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'PM_COMPLETED','event_at':'2026-09-05 14:00:00','maintenance_order_id':oid},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90dc/maintenance/events',json={'organization_id':o,'entity_id':e,'work_center_id':w,'event_type':'BREAKDOWN','event_at':'2026-09-12 09:00:00','duration_minutes':60},headers=h); assert r.status_code==200,r.text
 r=c.post('/v90er/maintenance/execution-feedback/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','sla_hours':24,'outcome_window_days':30},headers=h); assert r.status_code==200,r.text
 j=r.json(); assert j['count']==1; row=j['rows'][0]; assert row['responded_orders']==1 and row['breakdowns_after_intervention']>=1 and row['risk_hits']>=1
 d=c.get('/v90er/maintenance/execution-feedback/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json(); assert d['count']==1 and d['risk_hits']>=1
 cal=c.get('/v90er/maintenance/execution-feedback/calibration',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json(); assert cal['calibration_is_observational'] is True
 assert c.get('/v90er/maintenance/execution-feedback/trend',params={'organization_id':o,'entity_id':e},headers=h).status_code==200
 assert c.post('/v90er/maintenance/execution-feedback/2026-09/close',json={'organization_id':o,'entity_id':e},headers=h).status_code==200
 assert c.post('/v90er/maintenance/execution-feedback/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).status_code==409
