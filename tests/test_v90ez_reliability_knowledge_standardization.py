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
 assert TestClient(app).get('/ui/maintenance-reliability-knowledge').status_code==200
def test_knowledge_standard_approval():
 c,h=TestClient(app),auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4()); lid=str(uuid.uuid4())
 with engine.begin() as db:
  db.execute(text("INSERT INTO maintenance_reliability_continuous_improvement_snapshot(learning_id,organization_id,entity_id,period_key,improvement_assessment,current_effectiveness_score,recommendation,created_by) VALUES(:l,:o,:e,'2026-09','IMPROVING',82,'Retain successful PM practice','erpadmin')"),{'l':lid,'o':o,'e':e})
 r=c.post('/v90ez/maintenance/reliability-knowledge/generate',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200,r.text; kid=r.json()['knowledge'][0]['knowledge_id']
 r=c.post(f'/v90ez/maintenance/reliability-knowledge/{kid}/standard',json={'standard_text':'Use validated PM interval','standard_type':'PM_PRACTICE'},headers=h); assert r.status_code==200,r.text; sid=r.json()['standard_id']
 r=c.post(f'/v90ez/maintenance/reliability-knowledge/standards/{sid}/approve',headers=h); assert r.status_code==200 and r.json()['status']=='APPROVED'
 r=c.get('/v90ez/maintenance/reliability-knowledge/dashboard',params={'organization_id':o,'entity_id':e},headers=h); assert r.status_code==200 and r.json()['approved_standard_count']==1
