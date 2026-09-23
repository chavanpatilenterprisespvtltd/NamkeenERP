import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]

def auth():
    from app.auth import make_access_token, UserRecord
    return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}

def test_release_and_tax_routes():
    rel=json.loads((ROOT/'config/release_manifest.json').read_text())
    assert rel['release'].startswith('v90.') and int(rel['schema_target'])>=150
    c=TestClient(app); h=auth()
    assert c.get('/ui/tax').status_code==200
    r=c.post('/v90by/tax/calculate',json={'taxable_value':1000,'gst_rate':18,'intra_state':True,'cess_rate':0},headers=h)
    assert r.status_code==200
    x=r.json(); assert x['cgst']==90 and x['sgst']==90 and x['igst']==0 and x['total_tax']==180

def test_hsn_and_rate_master_validation():
    import uuid
    c=TestClient(app); h=auth(); o=str(uuid.uuid4())
    r=c.post('/v90by/hsn',json={'organization_id':o,'hsn_code':'1905','description':'Prepared food'},headers=h)
    assert r.status_code==200
    hid=r.json()['hsn_id']
    r=c.post('/v90by/tax-rates',json={'organization_id':o,'hsn_id':hid,'gst_rate':18,'intra_state':False},headers=h)
    assert r.status_code==200 and r.json()['igst_rate']==18 and r.json()['cgst_rate']==0
