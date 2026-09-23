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
 assert TestClient(app).get('/ui/maintenance-reliability-capa').status_code==200
def test_generate_and_effectiveness():
 c,h=TestClient(app),auth(); o=str(uuid.uuid4()); eid=str(uuid.uuid4()); p='2026-09'; bid=str(uuid.uuid4())
 with engine.begin() as db:
  db.execute(text('''INSERT INTO maintenance_reliability_benchmark_snapshot(benchmark_id,organization_id,entity_id,period_key,scope_type,scope_id,scope_name,control_score,effectiveness_score,target_met_pct,adoption_pct,failed_change_count,repeat_failure_count,benchmark_score,benchmark_rank,peer_count,benchmark_gap,assessment,recommendation,status,created_by) VALUES(:b,:o,:e,:p,'ENTITY',:e,:e,40,40,40,40,0,3,40,2,2,20,'BENCHMARK_EXCEPTION','fix','OPEN','erpadmin')'''),{'b':bid,'o':o,'e':eid,'p':p})
 r=c.post('/v90fc/maintenance/reliability-capa/generate',json={'organization_id':o,'period_key':p},headers=h); assert r.status_code==200 and r.json()['created_count']==1
 cid=r.json()['capa_ids'][0]
 r=c.post(f'/v90fc/maintenance/reliability-capa/{cid}/effectiveness',json={'evidence':'Root cause fixed and recurrence monitored.','effective':True},headers=h); assert r.status_code==200 and r.json()['status']=='CLOSED'
