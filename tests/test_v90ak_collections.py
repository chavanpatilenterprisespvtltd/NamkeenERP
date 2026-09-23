from uuid import uuid4
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_env():
    uid=str(uuid4()); uname='ak_'+uid[:8]
    create_user(engine,uid,uname,'pw','AK Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    ids={k:str(uuid4()) for k in ['e','l','w','cust','sku','inv']}; org=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AK','legal_entity',1)"),{'e':ids['e'],'ec':'AK'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AK','site',1)"),{'l':ids['l'],'e':ids['e'],'lc':'AKL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AK','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'wc':'AKW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:c,:o,'CUSTOMER',:e,1,'{}'),(:s,:o,'SKU',:e,1,'{}')"),{'c':ids['cust'],'s':ids['sku'],'o':org,'e':ids['e']})
        so_base=str(uuid4())
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:so,:o,:e,:l,:w,:c,:n,'DISPATCHED','PASS','PASS','DISPATCHED',100,0,100,18,118,:u)"),{'so':so_base,'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'c':ids['cust'],'n':'SO-AK-'+ids['inv'][:7],'u':uid})
        db.execute(text("INSERT INTO sales_invoices(invoice_id,organization_id,entity_id,location_id,sales_order_id,dispatch_id,invoice_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:i,:o,:e,:l,:so,:d,:no,'POSTED',100,0,100,18,118,:u)"),{'i':ids['inv'],'o':org,'e':ids['e'],'l':ids['l'],'so':so_base,'d':str(uuid4()),'no':'INV-AK-'+ids['inv'][:7],'u':uid})
    return c,ids,org


def payment(c,ids,org,mode='UPI',amount=118,proof='pf'):
    r=c.post('/v90ac/payments',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'customer_id':ids['cust'],'amount':amount,'mode':mode,'payment_date':'2026-09-06','reference_no':'REF-AK','cheque_no':'CHQ1' if mode=='CHEQUE' else None,'proof_file_id':proof})
    assert r.status_code==200,r.text
    return r.json()['payment_id']


def test_verified_payment_allocates_to_invoice():
    c,ids,org=setup_env(); pid=payment(c,ids,org); assert c.post(f'/v90ac/payments/{pid}/verify').status_code==200
    r=c.post(f'/v90ak/payments/{pid}/allocate',json={'invoice_id':ids['inv'],'amount':118}); assert r.status_code==200,r.text
    assert r.json()['status']=='ALLOCATED'
    with engine.connect() as db: assert float(db.execute(text('SELECT SUM(amount) FROM payment_allocations WHERE payment_id=:p'),{'p':pid}).scalar())==118


def test_allocation_overpayment_blocked():
    c,ids,org=setup_env(); pid=payment(c,ids,org,amount=150); c.post(f'/v90ac/payments/{pid}/verify')
    r=c.post(f'/v90ak/payments/{pid}/allocate',json={'invoice_id':ids['inv'],'amount':150}); assert r.status_code==409


def test_cash_evidence_deposit_verify_flow():
    c,ids,org=setup_env(); pid=payment(c,ids,org,'CASH',100,'cashproof')
    assert c.post(f'/v90ak/payments/{pid}/cash/evidence').status_code==200
    assert c.post(f'/v90ak/payments/{pid}/cash/deposit',json={'deposit_ref':'DEP1','deposit_date':'2026-09-06'}).status_code==200
    r=c.post(f'/v90ak/payments/{pid}/deposit/verify'); assert r.status_code==200 and r.json()['status']=='VERIFIED'


def test_cheque_direct_verify_is_blocked_then_clearance_required():
    c,ids,org=setup_env(); pid=payment(c,ids,org,'CHEQUE',100)
    r=c.post(f'/v90ac/payments/{pid}/verify'); assert r.status_code==409
    r=c.post(f'/v90ak/payments/{pid}/cheque/clear',json={'clearance_ref':'BANK-CLR-1','cleared_date':'2026-09-06'}); assert r.status_code==200 and r.json()['status']=='VERIFIED'


def test_partial_payment_can_be_allocated_across_invoices():
    c,ids,org=setup_env(); pid=payment(c,ids,org,'UPI',150); assert c.post(f'/v90ac/payments/{pid}/verify').status_code==200
    r=c.post(f'/v90ak/payments/{pid}/allocate',json={'invoice_id':ids['inv'],'amount':50}); assert r.status_code==200 and r.json()['status']=='PARTIALLY_ALLOCATED'
    ids2={'inv':str(uuid4()),'so':str(uuid4())}
    with engine.begin() as db:
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:so,:o,:e,:l,:w,:c,:n,'DISPATCHED','PASS','PASS','DISPATCHED',80,0,80,0,80,:u)"), {'so':ids2['so'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'c':ids['cust'],'n':'SO2-'+ids2['so'][:6],'u':'AK'})
        db.execute(text("INSERT INTO sales_invoices(invoice_id,organization_id,entity_id,location_id,sales_order_id,dispatch_id,invoice_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:i,:o,:e,:l,:so,:d,:no,'POSTED',80,0,80,0,80,'AK')"), {'i':ids2['inv'],'o':org,'e':ids['e'],'l':ids['l'],'so':ids2['so'],'d':str(uuid4()),'no':'INV2-AK-'+ids2['inv'][:7]})
    r=c.post(f'/v90ak/payments/{pid}/allocate',json={'invoice_id':ids2['inv'],'amount':80}); assert r.status_code==200 and r.json()['status']=='PARTIALLY_ALLOCATED'
    assert r.json()['unallocated_amount']==20


def test_customer_collection_statement():
    c,ids,org=setup_env(); pid=payment(c,ids,org,'UPI',118); c.post(f'/v90ac/payments/{pid}/verify'); c.post(f'/v90ak/payments/{pid}/allocate',json={'invoice_id':ids['inv'],'amount':118})
    r=c.get(f'/v90ak/customers/{ids["cust"]}/statement',params={'entity_id':ids['e']}); assert r.status_code==200
    assert r.json()['summary']['net_outstanding']==0
