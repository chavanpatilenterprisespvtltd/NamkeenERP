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
 assert TestClient(app).get('/ui/year-end-close').status_code==200
def test_year_end_prepare_close_reopen():
 c=TestClient(app); h=auth(); org,ent=str(uuid.uuid4()),str(uuid.uuid4())
 # setup permanent and temporary ledgers and opening balances
 for code,typ in [('1100','ASSET'),('3000','EQUITY'),('4000','INCOME'),('5000','EXPENSE')]:
  assert c.post('/v90cl/accounts',json={'organization_id':org,'entity_id':ent,'ledger_code':code,'ledger_name':code,'account_type':typ},headers=h).status_code==200
 ob=c.post('/v90cl/opening-balances',json={'organization_id':org,'entity_id':ent,'period_key':'2026-04','lines':[{'ledger_code':'1100','debit':1000},{'ledger_code':'3000','credit':1000}]},headers=h); assert ob.status_code==200
 j=c.post('/v90cl/journals',json={'organization_id':org,'entity_id':ent,'journal_date':'2027-03-31','lines':[{'ledger_code':'1100','debit':250},{'ledger_code':'4000','credit':250}]},headers=h); assert j.status_code==200
 assert c.post('/v90cl/journals/'+j.json()['journal_id']+'/post',headers=h).status_code==200
 r=c.post('/v90cn/year-end/prepare',json={'organization_id':org,'entity_id':ent,'financial_year':'2026-27','start_date':'2026-04-01','end_date':'2027-03-31','retained_earnings_ledger':'3000'},headers=h); assert r.status_code==200 and r.json()['status']=='READY'
 cid=r.json()['close_id']; assert r.json()['net_profit_loss']==250
 x=c.post(f'/v90cn/year-end/{cid}/close',json={'next_period_key':'2027-04'},headers=h); assert x.status_code==200 and x.json()['status']=='CLOSED'
 g=c.get('/v90cn/year-end',params={'organization_id':org,'entity_id':ent,'financial_year':'2026-27'},headers=h).json(); assert g['close']['status']=='CLOSED' and any(z['ledger_code']=='1100' for z in g['carryforwards'])
 q=c.post(f'/v90cn/year-end/{cid}/reopen',json={'reason':'approved correction'},headers=h); assert q.status_code==200 and q.json()['status']=='REOPENED'
