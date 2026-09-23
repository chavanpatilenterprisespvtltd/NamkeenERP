from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def login(uid='aeadmin', username='aeadmin', role='manager', password='pw'):
    try: create_user(engine, uid, username, password, 'AE Admin', role)
    except Exception: pass
    return {'Authorization':'Bearer '+make_access_token(UserRecord(uid,username,role))}


def seed():
    ids={k:str(uuid4()) for k in ['e','l','w','cust','sku','lot','line']}; org=str(uuid4()); oid=None
    with engine.begin() as c:
        c.execute(text("INSERT OR IGNORE INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,'AEE','AE Entity','legal_entity',1)"),ids)
        c.execute(text("INSERT OR IGNORE INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,'AEL','AE Location','site',1)"),ids)
        c.execute(text("INSERT OR IGNORE INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,'AEW','AE WH','general',1)"),ids)
        for t,k in [('CUSTOMER','cust'),('SKU','sku')]:
            c.execute(text("INSERT OR IGNORE INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:id,:o,:t,:e,1,'{}')"),{'id':ids[k],'o':org,'t':t,'e':ids['e']})
        c.execute(text("INSERT OR IGNORE INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':'aeadmin','e':ids['e']})
        c.execute(text("INSERT OR IGNORE INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':'aeadmin','l':ids['l']})
        c.execute(text("INSERT OR IGNORE INTO erp_warehouse_user_access(user_id,warehouse_id) VALUES(:u,:w)"),{'u':'aeadmin','w':ids['w']})
        run_id=str(uuid4())
        c.execute(text("INSERT INTO packing_run(packing_run_id,organization_id,entity_id,location_id,warehouse_id,source_fg_lot_id,sku_id,run_no,source_qty,created_by) VALUES(:r,:o,:e,:l,:w,:src,:sku,'AE-RUN-'||substr(:r,1,8),50,:by)"),{'r':run_id,'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'src':str(uuid4()),'sku':ids['sku'],'by':'aeadmin'})
        c.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:lot,:o,:e,:l,:w,:r,:src,:sku,'AE-LOT-1',50,50,50,'kg','2026-09-01','2099-12-31','AVAILABLE','RELEASED','aeadmin')"),{'lot':ids['lot'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'r':run_id,'src':str(uuid4()),'sku':ids['sku']})
    c=TestClient(app); h=login()
    r=c.post('/v90z/sales/orders',headers=h,json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'warehouse_id':ids['w'],'customer_id':ids['cust'],'order_no':'AE-'+ids['e'][:8],'lines':[{'sku_id':ids['sku'],'quantity':20,'unit_price':10}]})
    assert r.status_code==200, r.text
    oid=r.json()['sales_order_id']
    c.post(f'/v90z/sales/orders/{oid}/submit',headers=h)
    with engine.begin() as cdb:
        cdb.execute(text("UPDATE sales_orders SET status='APPROVED',pricing_status='CHECKED',credit_status='CHECKED',stock_status='READY' WHERE sales_order_id=:id"),{'id':oid})
    return org,ids,oid,h


def test_allocate_approved_order_fefo_and_line_bridge():
    c=TestClient(app); org,ids,oid,h=seed()
    r=c.post(f'/v90ae/sales/orders/{oid}/allocate',headers=h)
    assert r.status_code==200,r.text; assert r.json()['status']=='ALLOCATED'
    g=c.get(f'/v90ae/sales/orders/{oid}/allocation',headers=h)
    assert g.status_code==200 and len(g.json()['items'])==1 and float(g.json()['items'][0]['quantity'])==20


def test_allocation_reduces_free_fefo_and_repeat_does_not_double_allocate():
    c=TestClient(app); org,ids,oid,h=seed();
    assert c.post(f'/v90ae/sales/orders/{oid}/allocate',headers=h).status_code==200
    r=c.get('/v90y/fg/fefo-preview',headers=h,params={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'warehouse_id':ids['w'],'sku_id':ids['sku'],'quantity':40})
    assert r.status_code==200 and r.json()['allocated_qty']==30
    r=c.post(f'/v90ae/sales/orders/{oid}/allocate',headers=h); assert r.status_code==200 and r.json()['allocated_lines']==[]


def test_allocation_blocks_unapproved_and_handles_shortage():
    c=TestClient(app); org,ids,oid,h=seed()
    with engine.begin() as db: db.execute(text("UPDATE sales_orders SET status='SUBMITTED' WHERE sales_order_id=:id"),{'id':oid})
    assert c.post(f'/v90ae/sales/orders/{oid}/allocate',headers=h).status_code==409
    with engine.begin() as db:
        db.execute(text("UPDATE sales_orders SET status='APPROVED' WHERE sales_order_id=:id"),{'id':oid})
        db.execute(text("UPDATE packed_fg_lot SET available_qty=5 WHERE packed_fg_lot_id=:id"),{'id':ids['lot']})
    r=c.post(f'/v90ae/sales/orders/{oid}/allocate',headers=h); assert r.status_code==200 and r.json()['status']=='PARTIAL'


def test_release_clears_order_allocations():
    c=TestClient(app); org,ids,oid,h=seed(); assert c.post(f'/v90ae/sales/orders/{oid}/allocate',headers=h).status_code==200
    r=c.post(f'/v90ae/sales/orders/{oid}/allocation/release',headers=h,params={'reason':'cancelled'}); assert r.status_code==200
    assert c.get(f'/v90ae/sales/orders/{oid}/allocation',headers=h).json()['items'][0]['status']=='RELEASED'
    pr=c.get('/v90y/fg/fefo-preview',headers=h,params={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'warehouse_id':ids['w'],'sku_id':ids['sku'],'quantity':20})
    assert pr.json()['allocated_qty']==20


def test_scope_and_permission_guards():
    c=TestClient(app); org,ids,oid,h=seed()
    # different user without access
    try: create_user(engine,'aeforbid','aeforbid','pw','Forbidden','manager')
    except Exception: pass
    hh={'Authorization':'Bearer '+make_access_token(UserRecord('aeforbid','aeforbid','manager'))}
    assert c.post(f'/v90ae/sales/orders/{oid}/allocate',headers=hh).status_code==403


def test_migration_and_build_metadata():
    c=TestClient(app); h=login();
    # migration manifest is validated on import; assert target and build marker
    v=c.get('/version',headers=h); assert v.status_code==200 and int(v.json()['schema_target'])>=104
    b=c.get('/build',headers=h).json(); assert b['sales_order_allocation']=='approved_order_fg_fefo_allocation_release'
