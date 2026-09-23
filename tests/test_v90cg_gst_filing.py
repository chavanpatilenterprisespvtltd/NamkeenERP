import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=158
 assert TestClient(app).get('/ui/gst-filing').status_code==200
def test_snapshot_adjust_lock_export():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90by/tax/transactions',json={'organization_id':o,'entity_id':e,'source_type':'OUT','source_id':str(uuid.uuid4()),'taxable_value':1000,'gst_rate':18,'intra_state':True,'hsn_code':'1905','supply_type':'OUTWARD'},headers=h);assert r.status_code==200
 r=c.post('/v90by/tax/transactions',json={'organization_id':o,'entity_id':e,'source_type':'IN','source_id':str(uuid.uuid4()),'taxable_value':400,'gst_rate':18,'intra_state':True,'hsn_code':'1101','supply_type':'INWARD'},headers=h);assert r.status_code==200
 r=c.post('/v90cg/gst/filing/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h);assert r.status_code==200 and r.json()['net_tax']==108.0
 fid=r.json()['filing_id']
 r=c.post(f'/v90cg/gst/filing/{fid}/adjustment',json={'amount':2,'reason':'rounding'},headers=h);assert r.status_code==200
 r=c.post(f'/v90cg/gst/filing/{fid}/lock',headers=h);assert r.status_code==200
 r=c.get(f'/v90cg/gst/filing/{fid}/export',headers=h);assert r.status_code==200 and r.json()['net_tax']==110.0 and r.json()['status']=='LOCKED'
