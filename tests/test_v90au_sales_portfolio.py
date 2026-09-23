from uuid import uuid4
import json
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env():
    uid=str(uuid4()); uname='au_'+uid[:8]; create_user(engine,uid,uname,'pw','AU Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    ids={k:str(uuid4()) for k in ['e','l','cust','sales']}; org=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AU','legal_entity',1)"),{'e':ids['e'],'c':'AU'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AU','site',1)"),{'l':ids['l'],'e':ids['e'],'c':'AUL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':ids['sales'],'e':ids['e']})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,data,active,version_no) VALUES(:m,:o,'CUSTOMER',:e,:d,1,1)"),{'m':ids['cust'],'o':org,'e':ids['e'],'d':json.dumps({'name':'Dealer AU','channel':'DEALER'})})
    return c,uid,ids,org

def test_territory_and_assignment_and_reassignment():
    c,uid,ids,org=env()
    r=c.post('/v90au/territories',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'territory_id':'T1','territory_name':'Kolhapur'})
    assert r.status_code==200,r.text
    r=c.post('/v90au/portfolio/assign',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'customer_id':ids['cust'],'customer_type':'DEALER','territory_id':'T1','salesperson_user_id':ids['sales'],'reason':'initial'})
    assert r.status_code==200,r.text and r.json()['reassigned'] is False
    r=c.post(f'/v90au/portfolio/customer/{ids["cust"]}/reassign',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'customer_type':'DISTRIBUTOR','territory_id':'T2','salesperson_user_id':None,'reason':'move'})
    assert r.status_code==200,r.text and r.json()['reassigned'] is True
    r=c.get(f'/v90au/portfolio/customer/{ids["cust"]}',params={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']})
    assert r.status_code==200 and r.json()['assignment']['territory_id']=='T2' and r.json()['customer']['customer_type']=='DISTRIBUTOR'
    r=c.get(f'/v90au/portfolio/audit/{ids["cust"]}',params={'organization_id':org,'entity_id':ids['e']})
    assert r.status_code==200 and len(r.json()['items'])==2

def test_customer_portfolio_scope_denied():
    c,uid,ids,org=env(); uid2=str(uuid4()); create_user(engine,uid2,'au_no_'+uid2[:8],'pw','AU No','salesperson')
    c2=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid2,'au_no_'+uid2[:8],'salesperson'))})
    r=c2.get(f'/v90au/portfolio/customer/{ids["cust"]}',params={'organization_id':org,'entity_id':ids['e']})
    assert r.status_code==403

def test_duplicate_territory_blocked():
    c,uid,ids,org=env(); payload={'organization_id':org,'entity_id':ids['e'],'territory_id':'T9','territory_name':'T'}
    assert c.post('/v90au/territories',json=payload).status_code==200
    assert c.post('/v90au/territories',json=payload).status_code==409
