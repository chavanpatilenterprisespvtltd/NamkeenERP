import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=166
 assert TestClient(app).get('/ui/tally-sync').status_code==200
def test_tally_company_queue_ack_retry():
 c=TestClient(app); h=auth(); org,ent=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90co/tally/companies',json={'organization_id':org,'entity_id':ent,'tally_company':'Demo Tally Co'},headers=h); assert r.status_code==200
 a=c.post('/v90ca/accounting/post',json={'organization_id':org,'entity_id':ent,'source_type':'TEST','source_id':str(uuid.uuid4()),'voucher_no':'T1','posting_date':'2026-04-01','taxable_value':100,'tax_value':0},headers=h); assert a.status_code==200
 pid=a.json()['posting_id']; e=c.post('/v90ca/tally/'+pid+'/export',headers=h); assert e.status_code in (200,201)
 q=c.post('/v90co/tally/queue/'+pid,headers=h); assert q.status_code==200; sid=q.json()['sync_id']
 ack=c.post('/v90co/tally/ack/'+sid,json={'status':'FAILED','error':'connection unavailable'},headers=h); assert ack.status_code==200
 rt=c.post('/v90co/tally/retry/'+sid,headers=h); assert rt.status_code==200 and rt.json()['status']=='QUEUED'
 ok=c.post('/v90co/tally/ack/'+sid,json={'status':'ACKNOWLEDGED','message':'accepted by Tally'},headers=h); assert ok.status_code==200
