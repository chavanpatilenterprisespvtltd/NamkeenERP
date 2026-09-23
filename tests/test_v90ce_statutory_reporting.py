import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=156
 assert TestClient(app).get('/ui/statutory').status_code==200
def test_gst_hsn_and_validation():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90by/hsn',json={'organization_id':o,'hsn_code':'TEST-HSN'},headers=h); assert r.status_code==200
 r=c.post('/v90by/tax/transactions',json={'organization_id':o,'entity_id':e,'source_type':'TEST','source_id':str(uuid.uuid4()),'taxable_value':1000,'gst_rate':18,'intra_state':True,'hsn_code':'TEST-HSN'},headers=h); assert r.status_code==200
 r=c.get('/v90ce/statutory/gst-summary',params={'organization_id':o,'period_key':'2026-09'},headers=h); assert r.status_code==200 and r.json()['totals']['total_tax']==180.0
 r=c.get('/v90ce/statutory/hsn-summary',params={'organization_id':o,'period_key':'2026-09'},headers=h); assert r.status_code==200 and r.json()['items'][0]['hsn_code']=='TEST-HSN'
 r=c.post('/v90ce/statutory/validate',json={'organization_id':o,'period_key':'2026-09','entity_id':e},headers=h); assert r.status_code==200 and r.json()['exceptions_found']==0
def test_period_close_blocks_open_exception():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 c.post('/v90by/tax/transactions',json={'organization_id':o,'entity_id':e,'source_type':'TEST','source_id':'EX1','taxable_value':100,'gst_rate':18,'intra_state':True},headers=h)
 r=c.post('/v90ce/statutory/validate',json={'organization_id':o,'period_key':'2026-09','entity_id':e},headers=h); assert r.status_code==200 and r.json()['exceptions_found']==1
 r=c.post('/v90ce/statutory/periods/2026-09/close',json={'organization_id':o},headers=h); assert r.status_code==400
