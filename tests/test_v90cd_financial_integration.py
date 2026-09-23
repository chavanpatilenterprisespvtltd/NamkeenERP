import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_report_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert str(d['release']).startswith('v90.') and d['schema_target']>=155
 assert TestClient(app).get('/ui/financial-reports').status_code==200
def test_asset_depreciation_accounting_post():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4()); r=c.post('/v90cc/assets',json={'organization_id':o,'entity_id':e,'asset_code':'CD-'+o[:5],'asset_name':'Plant','acquisition_date':'2026-09-01','acquisition_cost':12000,'useful_life_months':12},headers=h); aid=r.json()['asset_id']; c.post(f'/v90cc/assets/{aid}/depreciate',json={'period_key':'2026-09'},headers=h); r=c.post(f'/v90cd/accounting/assets/{aid}/depreciation-post',json={'period_key':'2026-09'},headers=h); assert r.status_code==200 and r.json()['status']=='POSTED'
def test_loan_interest_and_pnl():
 c=TestClient(app);h=auth();o,e=str(uuid.uuid4()),str(uuid.uuid4()); r=c.post('/v90cc/loans',json={'organization_id':o,'entity_id':e,'loan_code':'CDL-'+o[:5],'lender_name':'L','principal':12000,'interest_rate':12,'tenure_months':12,'start_date':'2026-09-01'},headers=h); lid=r.json()['loan_id']; r=c.post(f'/v90cd/accounting/loans/{lid}/interest-post',json={'installment_no':1},headers=h); assert r.status_code==200; r=c.get('/v90cd/accounting/profit-loss',params={'organization_id':o},headers=h); assert r.status_code==200 and 'net_profit' in r.json()
