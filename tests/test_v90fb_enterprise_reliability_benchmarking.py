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
 assert TestClient(app).get('/ui/maintenance-reliability-benchmark').status_code==200
def test_entity_benchmark_ranking_and_exception():
 c,h=TestClient(app),auth(); o=str(uuid.uuid4()); e1,e2=str(uuid.uuid4()),str(uuid.uuid4()); p='2026-09'
 with engine.begin() as db:
  for eid,cs,eff,tm in [(e1,90,88,95),(e2,45,40,35)]:
   db.execute(text('''INSERT INTO maintenance_reliability_executive_control_snapshot(control_id,organization_id,entity_id,period_key,effectiveness_score,target_met_pct,failed_change_count,repeat_failure_count,governance_score,control_score,assessment,created_by) VALUES(:id,:o,:e,:p,:ef,:tm,0,0,80,:cs,'REVIEW_REQUIRED','erpadmin') ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET control_score=:cs,effectiveness_score=:ef,target_met_pct=:tm'''),{'id':str(uuid.uuid4()),'o':o,'e':eid,'p':p,'ef':eff,'tm':tm,'cs':cs})
 r=c.post('/v90fb/maintenance/reliability-benchmark/snapshot',json={'organization_id':o,'period_key':p},headers=h); assert r.status_code==200,r.text and r.json()['entity_benchmark_count']==2
 r=c.get('/v90fb/maintenance/reliability-benchmark/ranking',params={'organization_id':o,'period_key':p,'scope_type':'ENTITY'},headers=h); assert r.status_code==200 and r.json()['ranking'][0]['benchmark_rank']==1
 r=c.get('/v90fb/maintenance/reliability-benchmark/exceptions',params={'organization_id':o,'period_key':p},headers=h); assert r.status_code==200 and r.json()['count']>=1
 xid=r.json()['exceptions'][0]['exception_id']; assert c.post(f'/v90fb/maintenance/reliability-benchmark/exceptions/{xid}/resolve',json={'resolution_note':'Reviewed and assigned improvement owner'},headers=h).json()['status']=='RESOLVED'
