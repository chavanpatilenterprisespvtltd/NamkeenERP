from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
import json

def env():
    uid=str(uuid4()); uname='at_'+uid[:8]
    create_user(engine,uid,uname,'pw','AT Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4()); cust=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AT','legal_entity',1)"),{'e':e,'c':'AT'+e[:5]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AT','site',1)"),{'l':l,'e':e,'c':'ATL'+l[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,data,active,version_no) VALUES(:m,:o,'CUSTOMER',:e,:d,1,1)"),{'m':cust,'o':org,'e':e,'d':json.dumps({'name':'Dealer A','channel':'DEALER','territory_id':'T1','territory_name':'Kolhapur','salesperson_user_id':uid,'credit_limit':10000})})
        so=str(uuid4())
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at) VALUES(:id,:o,:e,:l,:w,:c,:order_no,'APPROVED','CHECKED','CHECKED','READY',1000,0,1000,120,1120,:u,'2026-09-07T10:00:00')"),{'id':so,'o':org,'e':e,'l':l,'w':str(uuid4()),'c':cust,'u':uid,'order_no':'AT-'+str(uuid4())[:8]})
    return c,org,e,l,cust

def test_sales_mis_breakdown_and_snapshot():
    c,org,e,l,_=env(); q={'organization_id':org,'entity_id':e,'location_id':l,'from_date':'2026-09-07','to_date':'2026-09-07'}
    r=c.get('/v90at/sales-mis',params=q); assert r.status_code==200,r.text
    j=r.json(); assert j['order_count']==1 and j['customer_count']==1
    assert j['by_territory'][0]['key']=='T1' and j['by_channel'][0]['key']=='DEALER'
    s=c.post('/v90at/sales-mis/snapshots',json=q); assert s.status_code==200,s.text
    sid=s.json()['snapshot_id']; r=c.get('/v90at/sales-mis/snapshots',params={'organization_id':org,'entity_id':e,'location_id':l}); assert any(x['snapshot_id']==sid for x in r.json()['snapshots'])

def test_sales_mis_date_validation():
    c,org,e,l,_=env(); r=c.get('/v90at/sales-mis',params={'organization_id':org,'entity_id':e,'location_id':l,'from_date':'2026-09-08','to_date':'2026-09-07'}); assert r.status_code==422

def test_sales_mis_permission_denied():
    uid=str(uuid4()); uname='at_no_'+uid[:8]; create_user(engine,uid,uname,'pw','No MIS','salesperson')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'salesperson'))})
    # salesperson receives view permission but not edit; snapshot creation must fail.
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AT2','legal_entity',1)"),{'e':e,'c':'AT2'+e[:4]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AT2','site',1)"),{'l':l,'e':e,'c':'ATL2'+l[:4]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
    r=c.post('/v90at/sales-mis/snapshots',json={'organization_id':org,'entity_id':e,'location_id':l,'from_date':'2026-09-07','to_date':'2026-09-07'}); assert r.status_code==403
