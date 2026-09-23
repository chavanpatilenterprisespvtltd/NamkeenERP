import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=158
 assert TestClient(app).get('/ui/gst-reconciliation').status_code==200
def test_reconciliation_and_export():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90by/tax/transactions',json={'organization_id':o,'entity_id':e,'source_type':'TEST','source_id':str(uuid.uuid4()),'taxable_value':1000,'gst_rate':18,'intra_state':True,'hsn_code':'1905'},headers=h); assert r.status_code==200
 r=c.post('/v90cf/gst/reconciliation/run',json={'organization_id':o,'period_key':'2026-09','entity_id':e},headers=h); assert r.status_code==200 and r.json()['status']=='MISMATCH' and r.json()['variance']==180.0
 r=c.get('/v90cf/gst/exceptions',params={'organization_id':o,'period_key':'2026-09','entity_id':e},headers=h); assert r.status_code==200 and r.json()['count']==1
 ex=r.json()['items'][0]['exception_id']; r=c.post(f'/v90cf/gst/exceptions/{ex}/resolve',json={},headers=h); assert r.status_code==200
 r=c.get('/v90cf/gst/export',params={'organization_id':o,'period_key':'2026-09','entity_id':e},headers=h); assert r.status_code==200 and r.json()['rows'][0]['hsn_code']=='1905'
