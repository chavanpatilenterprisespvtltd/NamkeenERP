import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=167; assert TestClient(app).get('/ui/tally-hardening').status_code==200
def test_validation_ack():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4()); assert c.post('/v90co/tally/companies',json={'organization_id':o,'entity_id':e,'tally_company':'Demo'},headers=h).status_code==200
 a=c.post('/v90ca/accounting/post',json={'organization_id':o,'entity_id':e,'source_type':'TEST','source_id':str(uuid.uuid4()),'voucher_no':'CP1','posting_date':'2026-04-01','taxable_value':100,'tax_value':0},headers=h); assert a.status_code==200
 p=a.json()['posting_id']; assert c.post('/v90ca/tally/'+p+'/export',headers=h).status_code in (200,201); q=c.post('/v90co/tally/queue/'+p,headers=h); s=q.json()['sync_id']; v=c.post('/v90cp/tally/validate/'+s,headers=h); assert v.status_code==200; assert c.post('/v90cp/tally/ack/'+s,json={'tally_status':'ACCEPTED','external_reference':'T1'},headers=h).status_code==200; assert c.get('/v90cp/tally/health',params={'organization_id':o,'entity_id':e},headers=h).json()['queue']['acknowledged']==1
