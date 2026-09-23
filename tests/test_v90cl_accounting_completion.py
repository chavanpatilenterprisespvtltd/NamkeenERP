import json,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_and_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=163
 assert TestClient(app).get('/ui/accounting-completion').status_code==200
def test_accounts_journal_gl_and_close():
 c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
 assert c.post('/v90cl/accounts',json={'organization_id':o,'entity_id':e,'ledger_code':'CASH','ledger_name':'Cash','account_type':'ASSET'},headers=h).status_code==200
 j=c.post('/v90cl/journals',json={'organization_id':o,'entity_id':e,'journal_date':'2026-09-07','lines':[{'ledger_code':'CASH','debit':100,'credit':0},{'ledger_code':'SALES','debit':0,'credit':100}]},headers=h); assert j.status_code==200
 jid=j.json()['journal_id']; assert c.post(f'/v90cl/journals/{jid}/post',headers=h).json()['status']=='POSTED'
 g=c.get('/v90cl/gl',params={'organization_id':o,'entity_id':e,'ledger_code':'CASH'},headers=h); assert g.json()['closing_balance']==100
 op=c.post('/v90cl/opening-balances',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','lines':[{'ledger_code':'CASH','debit':50},{'ledger_code':'SALES','credit':50}]},headers=h); assert op.status_code==200
 assert c.post('/v90cl/financial-close',json={'organization_id':o,'entity_id':e,'period_key':'2026-09'},headers=h).json()['status']=='CLOSED'
 assert c.post('/v90cl/financial-close/reopen',json={'organization_id':o,'entity_id':e,'period_key':'2026-09','reason':'authorized adjustment'},headers=h).json()['status']=='OPEN'
