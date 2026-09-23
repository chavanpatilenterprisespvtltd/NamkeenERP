import json, uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 r=json.loads((ROOT/'config/release_manifest.json').read_text()); assert r['release'].startswith('v90.') and int(r['schema_target'])>=153
 assert TestClient(app).get('/ui/accounting-posting').status_code==200
def test_balanced_outward_and_tally():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90ca/accounting/post',json={'organization_id':o,'entity_id':e,'source_type':'MANUAL_SALE','source_id':str(uuid.uuid4()),'voucher_no':'T-1','taxable_value':1000,'tax_value':180,'igst_value':180},headers=h);assert r.status_code==200
 pid=r.json()['posting_id'];r=c.get('/v90ca/accounting/postings',params={'organization_id':o},headers=h);assert r.status_code==200 and r.json()['items'][0]['debit_total']==1180.0
 r=c.post('/v90ca/tally/'+pid+'/export',headers=h);assert r.status_code==200 and '<VOUCHER' in r.json()['payload']
 r2=c.post('/v90ca/tally/'+pid+'/export',headers=h);assert r2.status_code==200 and r2.json()['idempotent'] is True
def test_duplicate_source_and_inward_balance():
 c=TestClient(app);h=auth();o,e,s=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4());body={'organization_id':o,'entity_id':e,'source_type':'PURCHASE','source_id':s,'taxable_value':500,'tax_value':90,'cgst_value':45,'sgst_value':45,'supply_type':'INWARD'}
 r=c.post('/v90ca/accounting/post',json=body,headers=h);assert r.status_code==200
 r=c.post('/v90ca/accounting/post',json=body,headers=h);assert r.status_code==409
 r=c.get('/v90ca/accounting/postings',params={'organization_id':o},headers=h);assert r.json()['items'][0]['debit_total']==590.0 and r.json()['items'][0]['credit_total']==590.0
