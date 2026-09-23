import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=161
 assert TestClient(app).get('/ui/gst-settlement').status_code==200
def test_settlement_flow():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90cg/gst/filing/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200
 f=r.json()['filing_id']
 c.post(f'/v90ci/gst/returns/{f}/section',json={'section_code':'OUTWARD','supply_class':'OUTWARD','taxable_value':1000,'tax_value':180},headers=h)
 # snapshot liability is zero if tax transaction lines do not exist; settle zero safely, then reject/signoff guard is tested separately
 r=c.post(f'/v90cj/gst/settlement/{f}/run',headers=h); assert r.status_code==200 and r.json()['status']=='MATCHED'
 sid=r.json()['settlement_id']
 r=c.post(f'/v90cj/gst/settlement/{sid}/signoff',json={'status':'SIGNED','remarks':'reconciled'},headers=h); assert r.status_code==200
 r=c.get(f'/v90cj/gst/settlement/{f}/export',headers=h); assert r.status_code==200 and r.json()['signoff']['status']=='SIGNED'
