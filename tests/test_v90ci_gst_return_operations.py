import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=160
 assert TestClient(app).get('/ui/gst-return-operations').status_code==200
def test_return_operations():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90cg/gst/filing/snapshot',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h); assert r.status_code==200
 f=r.json()['filing_id']
 assert c.post(f'/v90ci/gst/returns/{f}/section',json={'section_code':'OUTWARD_B2B','supply_class':'OUTWARD','taxable_value':1000,'tax_value':180},headers=h).status_code==200
 assert c.post(f'/v90ci/gst/returns/{f}/payment',json={'payment_date':'2026-09-30','challan_no':'CH-1','amount':180},headers=h).status_code==200
 assert c.post(f'/v90ci/gst/returns/{f}/acknowledgement',json={'filing_reference':'REF-1','acknowledgement_no':'ACK-1','filed_at':'2026-10-01T10:00:00'},headers=h).status_code==200
 assert c.post(f'/v90ci/gst/returns/{f}/signoff',json={'status':'SIGNED','remarks':'reviewed'},headers=h).status_code==200
 x=c.get(f'/v90ci/gst/returns/{f}/export',headers=h); assert x.status_code==200 and x.json()['signoff']['status']=='SIGNED'
