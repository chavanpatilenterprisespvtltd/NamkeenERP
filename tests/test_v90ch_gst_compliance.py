import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=159
 assert TestClient(app).get('/ui/gst-compliance').status_code==200
def test_prepare_document_file():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90cg/gst/filing/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200
 fid=r.json()['filing_id']
 r=c.post(f'/v90ch/gst/compliance/{fid}/prepare',json={'return_type':'GSTR1'},headers=h); assert r.status_code==200 and r.json()['status']=='PREPARED'
 r=c.post(f'/v90ch/gst/compliance/{fid}/document',json={'document_type':'CREDIT_NOTE','document_ref':'CN-1','taxable_value':100,'tax_value':18},headers=h); assert r.status_code==200
 r=c.post(f'/v90ch/gst/compliance/{fid}/file',json={'filing_reference':'ACK-1'},headers=h); assert r.status_code==200 and r.json()['status']=='FILED'
