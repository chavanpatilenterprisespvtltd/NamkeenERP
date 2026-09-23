from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def setup_env():
    uid=str(uuid4()); uname='am_'+uid[:8]
    create_user(engine,uid,uname,'pw','AM Tester','accounts')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'accounts'))})
    e,l,cust,pay=[str(uuid4()) for _ in range(4)]; org=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AM','legal_entity',1)"),{'e':e,'ec':'AM'+e[:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AM','site',1)"),{'l':l,'e':e,'lc':'AML'+l[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO payment_transactions(payment_id,organization_id,entity_id,location_id,customer_id,amount,mode,reference_no,payment_date,status,created_by) VALUES(:p,:o,:e,:l,:c,250,'BANK_TRANSFER','UTR-AM','2026-09-07','VERIFIED',:u)"),{'p':pay,'o':org,'e':e,'l':l,'c':cust,'u':uid})
    return c, {'e':e,'l':l,'pay':pay,'org':org}, uid

def test_bank_import_match_reconcile_summary():
    c,ids,_=setup_env()
    payload={'organization_id':ids['org'],'entity_id':ids['e'],'location_id':ids['l'],'bank_name':'Test Bank','statement_date':'2026-09-07','statement_ref':'ST-AM-001','amount':250,'transaction_type':'CREDIT','bank_reference':'UTR-AM'}
    r=c.post('/v90am/bank-lines',json=payload); assert r.status_code==200,r.text
    bid=r.json()['bank_line_id']
    r=c.post(f'/v90am/bank-lines/{bid}/match',json={'payment_id':ids['pay']}); assert r.status_code==200,r.text and r.json()['status']=='MATCHED'
    r=c.post(f'/v90am/bank-lines/{bid}/reconcile',json={'notes':'statement checked'}); assert r.status_code==200 and r.json()['status']=='RECONCILED'
    r=c.get('/v90am/summary',params={'entity_id':ids['e']}); assert r.status_code==200 and r.json()['statuses']['RECONCILED']['count']==1

def test_duplicate_statement_and_amount_mismatch_are_blocked():
    c,ids,uid=setup_env()
    payload={'organization_id':ids['org'],'entity_id':ids['e'],'location_id':ids['l'],'bank_name':'Test Bank','statement_date':'2026-09-07','statement_ref':'ST-AM-002','amount':250,'transaction_type':'CREDIT'}
    r=c.post('/v90am/bank-lines',json=payload); assert r.status_code==200
    r=c.post('/v90am/bank-lines',json=payload); assert r.status_code==409
    r=c.get('/v90am/bank-lines',params={'entity_id':ids['e']}); assert r.status_code==200
    bid=[x['bank_line_id'] for x in r.json()['items'] if x['statement_ref']=='ST-AM-002'][0]
    pid=str(uuid4())
    with engine.begin() as db:
        org=ids['org']
        db.execute(text("INSERT INTO payment_transactions(payment_id,organization_id,entity_id,location_id,customer_id,amount,mode,reference_no,payment_date,status,created_by) VALUES(:p,:o,:e,:l,:c,300,'BANK_TRANSFER','UTR-AM2','2026-09-07','VERIFIED',:u)"),{'p':pid,'o':org,'e':ids['e'],'l':ids['l'],'c':str(uuid4()),'u':uid})
    r=c.post(f'/v90am/bank-lines/{bid}/match',json={'payment_id':pid}); assert r.status_code==409
