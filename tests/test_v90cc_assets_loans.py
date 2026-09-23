import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text());assert d['release'].startswith('v90.') and d['schema_target']>=154
 assert TestClient(app).get('/ui/assets-loans').status_code==200
def test_asset_depreciation_disposal():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90cc/assets',json={'organization_id':o,'entity_id':e,'asset_code':'A-'+o[:6],'asset_name':'Machine','acquisition_date':'2026-09-01','acquisition_cost':120000,'useful_life_months':120},headers=h);assert r.status_code==200
 aid=r.json()['asset_id'];r=c.post(f'/v90cc/assets/{aid}/depreciate',json={'period_key':'2026-09'},headers=h);assert r.status_code==200 and r.json()['depreciation']==1000
 r=c.post(f'/v90cc/assets/{aid}/dispose',json={'disposal_date':'2027-01-01','proceeds':110000},headers=h);assert r.status_code==200 and r.json()['gain_loss']<0
def test_loan_schedule_and_payment():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90cc/loans',json={'organization_id':o,'entity_id':e,'loan_code':'L-'+o[:6],'lender_name':'Lender','principal':120000,'interest_rate':12,'tenure_months':12,'start_date':'2026-09-01'},headers=h);assert r.status_code==200
 lid=r.json()['loan_id'];r=c.get(f'/v90cc/loans/{lid}/schedule',headers=h);assert r.status_code==200 and len(r.json()['items'])==12
 amt=r.json()['items'][0]['total_due'];r=c.post(f'/v90cc/loans/{lid}/payments',json={'installment_no':1,'payment_date':'2026-10-01','amount':amt},headers=h);assert r.status_code==200 and r.json()['status']=='PAID'
