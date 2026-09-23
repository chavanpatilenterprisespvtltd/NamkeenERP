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
 assert TestClient(app).get('/ui/maintenance-reliability-standard-deployment').status_code==200
def test_deploy_approve_activate_adoption_exception_resolution():
 c,h=TestClient(app),auth(); o,e,s=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4())
 with engine.begin() as db:
  db.execute(text("INSERT INTO maintenance_reliability_standard_recommendation(standard_id,knowledge_id,organization_id,entity_id,standard_type,standard_text,rationale,status,created_by) VALUES(:s,:k,:o,:e,'PM_PRACTICE','Validated PM interval','Evidence','APPROVED','erpadmin')"),{'s':s,'k':str(uuid.uuid4()),'o':o,'e':e})
 r=c.post(f'/v90fa/maintenance/reliability-standards/{s}/deploy',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200,r.text; did=r.json()['deployment_id']
 assert c.post(f'/v90fa/maintenance/reliability-standards/deployments/{did}/approve',headers=h).json()['status']=='APPROVED'
 assert c.post(f'/v90fa/maintenance/reliability-standards/deployments/{did}/activate',headers=h).json()['status']=='ACTIVE'
 r=c.post(f'/v90fa/maintenance/reliability-standards/deployments/{did}/adoption',json={'subject_type':'USER','subject_id':'u1','status':'ACKNOWLEDGED'},headers=h); assert r.status_code==200 and r.json()['adoption_pct']==100
 r=c.post(f'/v90fa/maintenance/reliability-standards/deployments/{did}/adoption',json={'subject_type':'USER','subject_id':'u2','status':'EXCEPTION','exception_reason':'Training pending'},headers=h); assert r.status_code==200 and r.json()['exception_count']>=1
 with engine.connect() as db: xid=db.execute(text("SELECT exception_id FROM maintenance_reliability_standard_exception WHERE deployment_id=:d"),{'d':did}).scalar_one()
 assert c.post(f'/v90fa/maintenance/reliability-standards/exceptions/{xid}/resolve',json={'resolution_note':'Training completed'},headers=h).json()['status']=='RESOLVED'
 r=c.get('/v90fa/maintenance/reliability-standards/dashboard',params={'organization_id':o,'entity_id':e},headers=h); assert r.status_code==200 and r.json()['active_deployment_count']==1
