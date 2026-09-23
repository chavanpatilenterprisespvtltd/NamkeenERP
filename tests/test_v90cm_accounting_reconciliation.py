import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=164
 assert TestClient(app).get('/ui/accounting-reconciliation').status_code==200
def test_reconcile_and_signoff():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 r=c.post('/v90cm/reconcile',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','reconciliation_type':'SALES_RECEIVABLES','source_total':100,'ledger_total':100},headers=h)
 assert r.status_code==200 and r.json()['status']=='MATCHED'
 rid=r.json()['run_id']; assert c.post(f'/v90cm/reconcile/{rid}/signoff',headers=h).json()['status']=='SIGNED'
 x=c.post('/v90cm/reconcile',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','reconciliation_type':'BANK','source_total':100,'ledger_total':90},headers=h)
 assert x.json()['status']=='EXCEPTION'
