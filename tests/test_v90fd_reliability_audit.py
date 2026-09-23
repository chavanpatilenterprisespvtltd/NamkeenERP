import json, uuid
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and int(d['schema_target'])>=266
 assert TestClient(app).get('/ui/maintenance-reliability-audit').status_code==200
def test_audit_detects_approval_and_capa_evidence_gaps():
 c,h=TestClient(app),auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4()); p='2026-09'; proposal,impl,capa=[str(uuid.uuid4()) for _ in range(3)]
 with engine.begin() as db:
  db.execute(text("INSERT INTO maintenance_reliability_change_implementation(implementation_id,proposal_id,organization_id,entity_id,period_key,change_type,created_by) VALUES(:i,:p,:o,:e,:k,'PM_STRATEGY','erpadmin')"),{'i':impl,'p':proposal,'o':o,'e':e,'k':p})
  db.execute(text("INSERT INTO quality_capa(capa_id,nc_id,organization_id,entity_id,root_cause,corrective_action,due_date,status,created_by) VALUES(:i,:n,:o,:e,'rc','ca','2026-12-31','OPEN','erpadmin')"),{'i':capa,'n':'RELIABILITY:'+capa,'o':o,'e':e})
 r=c.post('/v90fd/maintenance/reliability-audit/snapshot',json={'organization_id':o,'entity_id':e,'period_key':p},headers=h); assert r.status_code==200
 d=r.json(); assert d['snapshot']['approval_gap_count']>=1 and d['snapshot']['capa_evidence_gap_count']>=1
 assert d['unauthorized_change_detection'].startswith('workflow-integrity')
