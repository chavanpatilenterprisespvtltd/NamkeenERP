from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.__main__ import app, engine
from app.identity import create_user
from app.migrations import load_migrations


def _user():
    uid = str(uuid4())
    create_user(engine, uid, f"ax_{uid[:8]}", "pw", "AX Tester", "manager")
    c = TestClient(app)
    token = c.post('/auth/login', json={'username': f'ax_{uid[:8]}', 'password':'pw'}).json()['access_token']
    return uid, {'Authorization': f'Bearer {token}'}


def _dispatch_state(uid):
    org, ent, loc, wh, so, line, sku, disp = [str(uuid4()) for _ in range(8)]
    with engine.begin() as c:
        c.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:e,:code,'AX','legal_entity')"), {'e':ent,'code':'AXE'+ent[:8]})
        c.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type) VALUES(:l,:e,:code,'AX','site')"), {'l':loc,'e':ent,'code':'AXL'+loc[:8]})
        c.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:code,'AX','general',1)"), {'w':wh,'e':ent,'l':loc,'code':'AXW'+wh[:8]})
        c.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"), {'u':uid,'e':ent})
        c.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"), {'u':uid,'l':loc})
        c.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:s,:o,:e,:l,:w,:c,:ono,'DISPATCHED','PASS','PASS','DISPATCHED',100,0,100,0,100,:u)"), {'s':so,'o':org,'e':ent,'l':loc,'w':wh,'c':str(uuid4()),'u':uid,'ono':'AX-SO-'+so[:8]})
        c.execute(text("INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price) VALUES(:l,:s,:sku,10,10)"), {'l':line,'s':so,'sku':sku})
        c.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,created_by) VALUES(:d,:o,:e,:l,:w,:s,:p,'AX-D1','POSTED',:u)"), {'d':disp,'o':org,'e':ent,'l':loc,'w':wh,'s':so,'p':str(uuid4()),'u':uid})
        c.execute(text("INSERT INTO dispatch_lines(dispatch_line_id,dispatch_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,dispatched_qty) VALUES(:dl,:d,:l,:a,:sku,:lot,6)"), {'dl':str(uuid4()),'d':disp,'l':line,'a':str(uuid4()),'sku':sku,'lot':str(uuid4())})
    return org, ent, loc, so, disp


def test_reconciliation_creates_open_backorder():
    uid, headers = _user(); _, ent, loc, so, _ = _dispatch_state(uid)
    c=TestClient(app, headers=headers)
    r=c.get(f'/v90ax/sales/orders/{so}/reconciliation')
    assert r.status_code==200, r.text
    body=r.json(); assert body['status']=='PARTIALLY_DISPATCHED'; assert body['ordered_qty']==10.0; assert body['dispatched_qty']==6.0; assert body['backorder_qty']==4.0
    b=c.get(f'/v90ax/sales/orders/{so}/backorders'); assert b.status_code==200; assert b.json()['items'][0]['backorder_qty']==4.0


def test_transporter_assignment_and_pod():
    uid, headers = _user(); org, ent, loc, so, disp = _dispatch_state(uid)
    c=TestClient(app, headers=headers)
    r=c.post('/v90ax/transporters',json={'organization_id':org,'entity_id':ent,'transporter_code':'T1','transporter_name':'Fast Transport'},headers=headers); assert r.status_code==200, r.text
    tid=r.json()['transporter_id']
    r=c.post(f'/v90ax/dispatches/{disp}/assignment',json={'transporter_id':tid,'vehicle_no':'MH12AB1234','driver_name':'Driver','driver_phone':'9999999999','eway_bill_no':'EWAY-1'}); assert r.status_code==200, r.text
    r=c.post(f'/v90ax/dispatches/{disp}/pod',json={'received_by':'Retailer','pod_reference':'POD-1','attachment_ref':'s3://pod/1.jpg'}); assert r.status_code==200 and r.json()['status']=='DELIVERED'
    r=c.get(f'/v90ax/dispatches/{disp}/pod'); assert r.status_code==200 and r.json()['items'][0]['pod_reference']=='POD-1'


def test_transporter_duplicate_code_blocked_and_migration_123():
    uid, headers = _user(); org, ent, *_ = _dispatch_state(uid); c=TestClient(app, headers=headers)
    payload={'organization_id':org,'entity_id':ent,'transporter_code':'DUP','transporter_name':'One'}
    assert c.post('/v90ax/transporters',json=payload).status_code==200
    assert c.post('/v90ax/transporters',json=payload).status_code==409
    assert any(m.version==123 and m.filename=='123_v90ax_dispatch_reconciliation_pod_backorder.sql' for m in load_migrations())
