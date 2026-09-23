from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def login(uid='afadmin', role='manager'):
    try: create_user(engine, uid, uid, 'pw', 'AF Admin', role)
    except Exception: pass
    with engine.begin() as c:
        for perm in ['dispatch.view','dispatch.edit']:
            c.execute(text('INSERT OR IGNORE INTO erp_permissions(permission_id,permission_name) VALUES(:id,:n)'), {'id':str(uuid4()),'n':perm})
        # identity helper roles are permissive for test baseline; add grants for this user role if absent
    return {'Authorization':'Bearer '+make_access_token(UserRecord(uid,uid,role))}

def seed():
    h=login(); ids={k:str(uuid4()) for k in ['e','l','w','cust','sku','lot','line']}; org=str(uuid4()); so=str(uuid4()); run=str(uuid4())
    with engine.begin() as c:
        c.execute(text("INSERT OR IGNORE INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,'AFE','AF Entity','legal_entity',1)"),ids)
        c.execute(text("INSERT OR IGNORE INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,'AFL','AF Location','site',1)"),ids)
        c.execute(text("INSERT OR IGNORE INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,'AFW','AF WH','general',1)"),ids)
        for t,k in [('CUSTOMER','cust'),('SKU','sku')]:
            c.execute(text("INSERT OR IGNORE INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:id,:o,:t,:e,1,'{}')"), {'id':ids[k],'o':org,'t':t,'e':ids['e']})
        c.execute(text("INSERT OR IGNORE INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"), {'u':'afadmin','e':ids['e']})
        c.execute(text("INSERT OR IGNORE INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"), {'u':'afadmin','l':ids['l']})
        c.execute(text("INSERT OR IGNORE INTO erp_warehouse_user_access(user_id,warehouse_id) VALUES(:u,:w)"), {'u':'afadmin','w':ids['w']})
        c.execute(text("INSERT INTO packing_run(packing_run_id,organization_id,entity_id,location_id,warehouse_id,source_fg_lot_id,sku_id,run_no,source_qty,created_by) VALUES(:r,:o,:e,:l,:w,:src,:sku,'AF-RUN-'||substr(:r,1,8),50,'afadmin')"), {'r':run,'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'src':str(uuid4()),'sku':ids['sku']})
        c.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:lot,:o,:e,:l,:w,:r,:src,:sku,'AF-LOT',50,50,50,'kg','2026-09-01','2099-12-31','AVAILABLE','RELEASED','afadmin')"), {'lot':ids['lot'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'r':run,'src':str(uuid4()),'sku':ids['sku']})
    c=TestClient(app)
    # create SO and force approved in same controlled way as prior stages
    r=c.post('/v90z/sales/orders',headers=h,json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'warehouse_id':ids['w'],'customer_id':ids['cust'],'order_no':'AF-'+ids['e'][:8],'lines':[{'sku_id':ids['sku'],'quantity':20,'unit_price':10}]})
    assert r.status_code==200,r.text; soid=r.json()['sales_order_id']
    with engine.connect() as cdb: lineid=str(cdb.execute(text("SELECT sales_order_line_id FROM sales_order_lines WHERE sales_order_id=:id ORDER BY sales_order_line_id LIMIT 1"), {'id':soid}).scalar_one())
    with engine.begin() as cdb: cdb.execute(text("UPDATE sales_orders SET status='APPROVED',pricing_status='CHECKED',credit_status='CHECKED',stock_status='READY' WHERE sales_order_id=:id"),{'id':soid})
    # bridge allocation directly to avoid dependence on role fixtures
    with engine.begin() as cdb:
        cdb.execute(text("INSERT INTO sales_order_allocations(sales_order_allocation_id,sales_order_id,sales_order_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,fg_allocation_group_id,status,created_by) VALUES(:a,:so,:line,:o,:e,:l,:w,:sku,:lot,'AF-LOT',20,:gid,'ALLOCATED','afadmin')"), {'a':str(uuid4()),'so':soid,'line':lineid,'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'sku':ids['sku'],'lot':ids['lot'],'gid':str(uuid4())})
    return c,h,soid,ids

def test_create_pick_list_and_get_detail():
    c,h,so,ids=seed(); r=c.post(f'/v90af/sales/orders/{so}/pick-list',headers=h); assert r.status_code==200,r.text
    pid=r.json()['pick_list_id']; g=c.get(f'/v90af/pick-lists/{pid}',headers=h); assert g.status_code==200 and len(g.json()['lines'])==1

def test_confirm_pick_updates_order_and_readiness():
    c,h,so,ids=seed(); pid=c.post(f'/v90af/sales/orders/{so}/pick-list',headers=h).json()['pick_list_id']; r=c.post(f'/v90af/pick-lists/{pid}/confirm',headers=h); assert r.status_code==200,r.text
    d=c.get(f'/v90af/sales/orders/{so}/dispatch-readiness',headers=h); assert d.status_code==200 and d.json()['dispatch_ready'] is True

def test_duplicate_open_pick_list_blocked():
    c,h,so,ids=seed(); assert c.post(f'/v90af/sales/orders/{so}/pick-list',headers=h).status_code==200
    assert c.post(f'/v90af/sales/orders/{so}/pick-list',headers=h).status_code==409
