import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 r=json.loads((ROOT/'config/release_manifest.json').read_text());assert r['release'].startswith('v90.') and int(r['schema_target'])>=153
 assert TestClient(app).get('/ui/accounting-controls').status_code==200
def test_reports_and_period_close():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90ca/accounting/post',json={'organization_id':o,'entity_id':e,'source_type':'CB_SALE','source_id':str(uuid.uuid4()),'voucher_no':'CB-1','posting_date':'2026-09-01','taxable_value':1000,'tax_value':180,'igst_value':180},headers=h);assert r.status_code==200
 r=c.get('/v90cb/accounting/trial-balance',params={'organization_id':o},headers=h);assert r.status_code==200 and r.json()['balanced']
 r=c.get('/v90cb/accounting/general-ledger',params={'organization_id':o},headers=h);assert r.status_code==200 and len(r.json()['items'])==3
 r=c.post('/v90cb/accounting/periods',json={'organization_id':o,'period_key':'2026-09','start_date':'2026-09-01','end_date':'2026-09-30'},headers=h);assert r.status_code==200
 pid=r.json()['period_id'];r=c.post('/v90cb/accounting/periods/'+pid+'/close',json={},headers=h);assert r.status_code==200 and r.json()['status']=='CLOSED'
 r=c.post('/v90cb/accounting/periods/'+pid+'/close',json={},headers=h);assert r.status_code==200 and r.json()['idempotent']
def test_gst_reconciliation():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90by/tax/transactions',json={'organization_id':o,'entity_id':e,'source_type':'CB','source_id':str(uuid.uuid4()),'taxable_value':500,'gst_rate':18,'intra_state':True},headers=h);assert r.status_code==200
 r=c.get('/v90cb/accounting/gst-reconciliation',params={'organization_id':o},headers=h);assert r.status_code==200 and r.json()['items'][0]['tax']==90.0
