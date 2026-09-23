from uuid import uuid4
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_env():
    uid=str(uuid4()); uname='al_'+uid[:8]
    create_user(engine,uid,uname,'pw','AL Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    e,l,w,cust,so,inv=[str(uuid4()) for _ in range(6)]; org=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AL','legal_entity',1)"),{'e':e,'ec':'AL'+e[:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AL','site',1)"),{'l':l,'e':e,'lc':'ALL'+l[:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AL','general',1)"),{'w':w,'e':e,'l':l,'wc':'ALW'+w[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:c,:o,'CUSTOMER',:e,1,'{}')"),{'c':cust,'o':org,'e':e})
        db.execute(text("INSERT INTO customer_credit_policies(credit_policy_id,organization_id,entity_id,customer_id,credit_limit,credit_days,active,created_by) VALUES(:p,:o,:e,:c,1000,30,1,:u)"),{'p':str(uuid4()),'o':org,'e':e,'c':cust,'u':uid})
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at) VALUES(:so,:o,:e,:l,:w,:c,:n,'DISPATCHED','PASS','PASS','DISPATCHED',100,0,100,0,100,:u,'2026-07-01T00:00:00')"),{'so':so,'o':org,'e':e,'l':l,'w':w,'c':cust,'n':'SOAL'+e[:6],'u':uid})
        db.execute(text("INSERT INTO sales_invoices(invoice_id,organization_id,entity_id,location_id,sales_order_id,dispatch_id,invoice_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at,due_date) VALUES(:i,:o,:e,:l,:so,:d,:no,'POSTED',100,0,100,0,100,:u,'2026-07-01T00:00:00','2026-07-31')"),{'i':inv,'o':org,'e':e,'l':l,'so':so,'d':str(uuid4()),'no':'INVAL'+inv[:6],'u':uid})
    return c, {'e':e,'l':l,'w':w,'cust':cust,'inv':inv,'so':so}, org, uid


def test_customer_aging_and_credit_note_payment_reconciliation():
    c,ids,org,uid=setup_env()
    r=c.get(f'/v90al/customers/{ids["cust"]}/aging',params={'entity_id':ids['e'],'as_of_date':'2026-09-06'}); assert r.status_code==200,r.text
    assert r.json()['buckets']['31_60']==100
    with engine.begin() as db:
        db.execute(text("INSERT INTO payment_transactions(payment_id,organization_id,entity_id,location_id,customer_id,amount,mode,payment_date,status,created_by) VALUES(:p,:o,:e,:l,:c,40,'UPI','2026-08-20','VERIFIED',:u)"),{'p':str(uuid4()),'o':org,'e':ids['e'],'l':ids['l'],'c':ids['cust'],'u':uid})
        pid=db.execute(text("SELECT payment_id FROM payment_transactions WHERE customer_id=:c ORDER BY created_at DESC LIMIT 1"),{'c':ids['cust']}).scalar()
        db.execute(text("INSERT INTO payment_allocations(allocation_id,payment_id,invoice_id,customer_id,organization_id,entity_id,amount,status,created_by) VALUES(:a,:p,:i,:c,:o,:e,40,'POSTED',:u)"),{'a':str(uuid4()),'p':pid,'i':ids['inv'],'c':ids['cust'],'o':org,'e':ids['e'],'u':uid})
    r=c.get(f'/v90al/customers/{ids["cust"]}/aging',params={'entity_id':ids['e'],'as_of_date':'2026-09-06'}); assert r.json()['summary']['total_outstanding']==60


def test_credit_utilization_and_followup():
    c,ids,org,uid=setup_env()
    r=c.get(f'/v90al/customers/{ids["cust"]}/credit-utilization',params={'entity_id':ids['e'],'as_of_date':'2026-09-06'}); assert r.status_code==200
    assert r.json()['credit_limit']==1000 and r.json()['outstanding']==100
    r=c.post('/v90al/followups',json={'customer_id':ids['cust'],'entity_id':ids['e'],'location_id':ids['l'],'follow_up_date':'2026-09-07','mode':'PHONE','note':'Follow up for overdue invoice'}); assert r.status_code==200
    r=c.get(f'/v90al/customers/{ids["cust"]}/aging',params={'entity_id':ids['e'],'as_of_date':'2026-09-06'}); assert len(r.json()['followups'])==1
