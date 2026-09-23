import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=162
 assert TestClient(app).get('/ui/gst-statutory-close').status_code==200
def test_close_gate_and_reopen():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 f=c.post('/v90cg/gst/filing/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json()['filing_id']
 # zero-liability fixture can satisfy settlement; add filed compliance and acknowledgement.
 c.post(f'/v90ci/gst/returns/{f}/acknowledgement',json={'filing_reference':'REF-'+f[:8]},headers=h)
 c.post(f'/v90ch/gst/compliance/{f}/prepare',json={'return_type':'GST_RETURN'},headers=h)
 c.post(f'/v90ch/gst/compliance/{f}/file',json={'filing_reference':'REF-'+f[:8]},headers=h)
 c.post(f'/v90cj/gst/settlement/{f}/run',headers=h)
 sid=c.post(f'/v90cj/gst/settlement/{f}/run',headers=h).json()['settlement_id']
 c.post(f'/v90cj/gst/settlement/{sid}/signoff',json={'status':'SIGNED'},headers=h)
 r=c.post(f'/v90ck/gst/close/{f}/evaluate',headers=h); assert r.status_code==200 and r.json()['status']=='READY'
 r=c.post(f'/v90ck/gst/close/{f}/finalize',json={'remarks':'final compliance close'},headers=h); assert r.status_code==200 and r.json()['status']=='LOCKED'
 r=c.post(f'/v90ck/gst/close/{f}/reopen',json={'reason':'authorized correction'},headers=h); assert r.status_code==200 and r.json()['status']=='OPEN'
