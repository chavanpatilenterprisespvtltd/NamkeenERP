import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app,engine
from sqlalchemy import text
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=266
 assert TestClient(app).get('/ui/maintenance-reliability-improvement').status_code==200
def test_cross_period_learning_and_close():
 c,h=TestClient(app),auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 with engine.begin() as db:
  for pk,score,eff,fail in [('2026-08',70,65,0),('2026-09',55,50,1)]:
   db.execute(text("INSERT INTO maintenance_reliability_executive_control_snapshot(control_id,organization_id,entity_id,period_key,effectiveness_score,target_met_pct,failed_change_count,repeat_failure_count,open_feedback_count,critical_exception_count,governance_score,control_score,assessment,created_by) VALUES(:id,:o,:e,:p,:ef,50,:f,0,0,0,50,:cs,'REVIEW_REQUIRED','erpadmin')"),{'id':str(uuid.uuid4()),'o':o,'e':e,'p':pk,'ef':eff,'f':fail,'cs':score})
 r=c.post('/v90ey/maintenance/reliability-improvement/learning/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','prior_period_key':'2026-08'},headers=h); assert r.status_code==200,r.text; assert r.json()['assessment']=='DETERIORATING'
 r=c.get('/v90ey/maintenance/reliability-improvement/dashboard',params={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200
 r=c.post('/v90ey/maintenance/reliability-improvement/2026-09/close',json={'organization_id':o,'entity_id':e,'closure_note':'Reviewed','force':True},headers=h); assert r.status_code==200 and r.json()['status']=='CLOSED'
