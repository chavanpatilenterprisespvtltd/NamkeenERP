import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 r=json.loads((ROOT/'config/release_manifest.json').read_text()); assert r['release'].startswith('v90.') and int(r['schema_target'])>=151
 assert TestClient(app).get('/ui/accounting').status_code==200
def test_mapping_and_batch():
 import uuid
 c=TestClient(app);h=auth();o=str(uuid.uuid4())
 r=c.post('/v90bz/accounting/maps',json={'organization_id':o,'source_key':'GST_OUTPUT','ledger_code':'GST-OUT'},headers=h);assert r.status_code==200
 r=c.post('/v90bz/accounting/batches',json={'organization_id':o,'period_key':'2026-09','export_format':'TALLY_XML'},headers=h);assert r.status_code==200
 bid=r.json()['batch_id'];r=c.post(f'/v90bz/accounting/batches/{bid}/generate',headers=h);assert r.status_code==200 and r.json()['status']=='GENERATED'
 r=c.post(f'/v90bz/accounting/batches/{bid}/export',headers=h);assert r.status_code==200 and r.json()['status']=='EXPORTED'
