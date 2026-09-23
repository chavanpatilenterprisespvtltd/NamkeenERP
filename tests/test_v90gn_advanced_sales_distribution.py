from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
import json

def env(role='manager'):
    uid=str(uuid4()); uname='gn_'+uid[:8]; create_user(engine,uid,uname,'pw','GN Tester',role)
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'GN Tester',role))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4()); cust=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GN','legal_entity',1)"),{'e':e,'c':'GN'+e[:5]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GN','site',1)"),{'l':l,'e':e,'c':'GNL'+l[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,data,active,version_no) VALUES(:m,:o,'CUSTOMER',:e,:d,1,1)"),{'m':cust,'o':org,'e':e,'d':json.dumps({'name':'Dealer GN','channel':'DEALER','territory_id':'T-GN','salesperson_user_id':uid})})
        so=str(uuid4()); db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at) VALUES(:id,:o,:e,:l,:w,:c,:n,'APPROVED','CHECKED','CHECKED','READY',1000,0,1000,180,1180,:u,'2026-09-10T10:00:00')"),{'id':so,'o':org,'e':e,'l':l,'w':str(uuid4()),'c':cust,'n':'GN-'+str(uuid4())[:6],'u':uid})
        inv=str(uuid4()); db.execute(text("INSERT INTO sales_invoices(invoice_id,organization_id,entity_id,location_id,sales_order_id,dispatch_id,invoice_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at) VALUES(:i,:o,:e,:l,:s,:d,:n,'POSTED',1000,0,1000,180,1180,:u,'2026-09-10T11:00:00')"),{'i':inv,'o':org,'e':e,'l':l,'s':so,'d':str(uuid4()),'n':'INV-'+str(uuid4())[:6],'u':uid})
    return c,org,e,l,cust

def test_performance_and_snapshot():
    c,o,e,l,_=env(); q={'organization_id':o,'entity_id':e,'location_id':l,'from_date':'2026-09-10','to_date':'2026-09-10'}
    r=c.get('/v90gn/sales-distribution',params=q); assert r.status_code==200,r.text; assert r.json()['net_sales']==1180.0
    s=c.post('/v90gn/sales-distribution/snapshots',json=q); assert s.status_code==200,s.text; assert s.json()['snapshot_id']
    r=c.get('/v90gn/sales-distribution/snapshots',params={'organization_id':o,'entity_id':e,'location_id':l}); assert r.status_code==200 and r.json()['snapshots']

def test_action_and_permission():
    c,o,e,l,_=env(); b={'organization_id':o,'entity_id':e,'location_id':l,'dimension_type':'TERRITORY','dimension_key':'T-GN','action_type':'FOLLOW_UP','priority':'HIGH','reason':'Review underperforming route'}
    r=c.post('/v90gn/actions',json=b); assert r.status_code==200
    r=c.get('/v90gn/actions',params={'organization_id':o,'entity_id':e,'location_id':l}); assert r.status_code==200 and r.json()['actions']
    s,_,ee,ll,_=env('salesperson'); r=s.post('/v90gn/actions',json={**b,'entity_id':ee,'location_id':ll}); assert r.status_code==403

def test_date_validation():
    c,o,e,l,_=env(); r=c.get('/v90gn/sales-distribution',params={'organization_id':o,'entity_id':e,'location_id':l,'from_date':'2026-09-11','to_date':'2026-09-10'}); assert r.status_code==422
