from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_env():
    uid=str(uuid4()); uname='ap_'+uid[:8]
    create_user(engine,uid,uname,'pw','AP Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    ids={k:str(uuid4()) for k in ['e','l','w','sup','inv1','inv2']}; org=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AP','legal_entity',1)"),{'e':ids['e'],'ec':'AP'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AP','site',1)"),{'l':ids['l'],'e':ids['e'],'lc':'APL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AP','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'wc':'APW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:s,:o,'SUPPLIER',:e,1,'{}')"),{'s':ids['sup'],'o':org,'e':ids['e']})
    return c,ids,org


def invoice(c,ids,org,number='PINV1',amount=118,due='2026-09-20'):
    r=c.post('/v90ap/supplier-invoices',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'supplier_id':ids['sup'],'invoice_no':number,'invoice_date':'2026-09-01','due_date':due,'subtotal':amount-18,'tax_amount':18,'grand_total':amount})
    assert r.status_code==200,r.text
    return r.json()['supplier_invoice_id']


def payment(c,ids,org,amount=118,ref=None):
    ref=ref or 'SPAY-'+str(uuid4())[:8]
    r=c.post('/v90ap/supplier-payments',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'supplier_id':ids['sup'],'amount':amount,'mode':'BANK_TRANSFER','payment_date':'2026-09-06','reference_no':ref})
    assert r.status_code==200,r.text
    return r.json()['supplier_payment_id']


def test_supplier_invoice_is_created_and_appears_in_aging():
    c,ids,org=setup_env(); invoice(c,ids,org)
    r=c.get(f'/v90ap/suppliers/{ids["sup"]}/aging',params={'entity_id':ids['e'],'as_of_date':'2026-09-10'})
    assert r.status_code==200
    assert r.json()['summary']['total_outstanding']==118
    assert r.json()['buckets']['CURRENT']==118


def test_supplier_payment_allocates_and_reduces_outstanding():
    c,ids,org=setup_env(); iid=invoice(c,ids,org); pid=payment(c,ids,org,50)
    r=c.post(f'/v90ap/supplier-payments/{pid}/allocate',json={'invoice_id':iid,'amount':50})
    assert r.status_code==200 and r.json()['unallocated_amount']==0 and r.json()['invoice_outstanding']==68


def test_supplier_payment_cannot_overallocate_invoice():
    c,ids,org=setup_env(); iid=invoice(c,ids,org,amount=100); pid=payment(c,ids,org,150)
    r=c.post(f'/v90ap/supplier-payments/{pid}/allocate',json={'invoice_id':iid,'amount':101})
    assert r.status_code==409


def test_supplier_invoice_aged_into_correct_bucket():
    c,ids,org=setup_env(); invoice(c,ids,org,due='2026-07-01')
    r=c.get(f'/v90ap/suppliers/{ids["sup"]}/aging',params={'entity_id':ids['e'],'as_of_date':'2026-09-01'})
    assert r.status_code==200 and r.json()['buckets']['61_90']==118


def test_supplier_overdue_endpoint_lists_overdue_invoice():
    c,ids,org=setup_env(); invoice(c,ids,org,due='2026-07-01')
    r=c.get('/v90ap/overdue',params={'entity_id':ids['e'],'as_of_date':'2026-09-01','min_days_overdue':1})
    assert r.status_code==200 and r.json()['count']==1 and r.json()['total_overdue']==118


def test_supplier_duplicate_invoice_number_is_blocked():
    c,ids,org=setup_env(); invoice(c,ids,org,number='DUP1')
    r=c.post('/v90ap/supplier-invoices',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'supplier_id':ids['sup'],'invoice_no':'DUP1','invoice_date':'2026-09-02','subtotal':10,'tax_amount':1.8,'grand_total':11.8})
    assert r.status_code==409
