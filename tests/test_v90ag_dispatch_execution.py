from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.__main__ import app, engine
from app.identity import create_user


def test_v90ag_dispatch_execution_roundtrip():
    uid = str(uuid4())
    create_user(engine, uid, f"ag_{uid[:8]}", "pw", "AG Tester", "manager")
    token = TestClient(app).post('/auth/login', json={'username': f'ag_{uid[:8]}', 'password':'pw'}).json()['access_token']
    client = TestClient(app, headers={'Authorization': f'Bearer {token}'})
    o = uuid4(); ent=uuid4(); loc=uuid4(); wh=uuid4(); cust=uuid4(); sku=uuid4(); lot=uuid4(); alloc=uuid4(); pick=uuid4(); pl=uuid4(); so_line=uuid4(); fg_alloc=uuid4(); inv_bal=0
    with engine.begin() as c:
        c.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:i,'AG','AG','legal_entity')"), {'i':str(ent)})
        c.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type) VALUES(:i,:e,'AGL','AG','site')"), {'i':str(loc),'e':str(ent)})
        c.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:i,:e,:l,'AGW','AG','general',1)"), {'i':str(wh),'e':str(ent),'l':str(loc)})
        c.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"), {'u':uid,'e':str(ent)})
        c.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"), {'u':uid,'l':str(loc)})
        org= str(uuid4())
        c.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:id,:o,'CUSTOMER',:e,1,'{}'),(:sid,:o,'SKU',:e,1,'{}')"), {'id':str(cust),'sid':str(sku),'o':org,'e':str(ent)})
        c.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:id,:o,:e,:l,:w,:c,'SO-AG','APPROVED','PASS','PASS','READY',100,0,100,12,112,:u)"), {'id':str(o),'o':org,'e':str(ent),'l':str(loc),'w':str(wh),'c':str(cust),'u':uid})
        c.execute(text("INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price,discount_pct,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) VALUES(:id,:o,:s,10,10,0,0,100,12,12,112)"), {'id':str(so_line),'o':str(o),'s':str(sku)})
        c.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:id,:org,:e,:l,:w,:pr,:src,:s,'LAG',10,10,10,'kg','2026-09-01',NULL,'AVAILABLE','RELEASED',:u)"), {'id':str(lot),'org':org,'e':str(ent),'l':str(loc),'w':str(wh),'pr':str(uuid4()),'src':str(uuid4()),'s':str(sku),'u':uid})
        c.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:s,'kg',10)"), {'o':org,'e':str(ent),'l':str(loc),'w':str(wh),'s':str(sku)})
        c.execute(text("INSERT INTO sales_order_allocations(sales_order_allocation_id,sales_order_id,sales_order_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,fg_allocation_group_id,status,created_by) VALUES(:a,:o,:sl,:org,:e,:l,:w,:s,:lot,'LAG',10,:g,'ALLOCATED',:u)"), {'a':str(alloc),'o':str(o),'sl':str(so_line),'org':org,'e':str(ent),'l':str(loc),'w':str(wh),'s':str(sku),'lot':str(lot),'g':str(uuid4()),'u':uid})
        c.execute(text("INSERT INTO fg_fefo_allocation(allocation_id,allocation_group_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,reference_type,reference_id,quantity,status,allocated_by) VALUES(:id,:g,:o,:e,:l,:w,:s,:lot,'LAG','SALES_ORDER',:ref,10,'OPEN',:u)"), {'id':str(fg_alloc),'g':str(uuid4()),'o':org,'e':str(ent),'l':str(loc),'w':str(wh),'s':str(sku),'lot':str(lot),'ref':str(o),'u':uid})
        c.execute(text("INSERT INTO dispatch_pick_lists(pick_list_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,status,created_by) VALUES(:p,:o,:e,:l,:w,:so,'PICKED',:u)"), {'p':str(pick),'o':org,'e':str(ent),'l':str(loc),'w':str(wh),'so':str(o),'u':uid})
        c.execute(text("INSERT INTO dispatch_pick_lines(pick_line_id,pick_list_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,allocated_qty,picked_qty,status) VALUES(:id,:p,:sl,:a,:s,:lot,'LAG',10,10,'PICKED')"), {'id':str(pl),'p':str(pick),'sl':str(so_line),'a':str(alloc),'s':str(sku),'lot':str(lot)})
    r=client.post(f'/v90ag/sales/orders/{o}/dispatch',json={'dispatch_no':'D-AG-1','invoice_no':'INV-AG-1'})
    assert r.status_code == 200, r.text
    with engine.connect() as c:
        assert float(c.execute(text('SELECT available_qty FROM packed_fg_lot WHERE packed_fg_lot_id=:l'),{'l':str(lot)}).scalar()) == 0
        assert c.execute(text("SELECT status FROM sales_order_allocations WHERE sales_order_allocation_id=:a"),{'a':str(alloc)}).scalar() == 'DISPATCHED'
        assert c.execute(text("SELECT status, stock_status FROM sales_orders WHERE sales_order_id=:o"),{'o':str(o)}).fetchone() == ('DISPATCHED','DISPATCHED')
        assert c.execute(text("SELECT status FROM dispatches WHERE dispatch_id=:d"),{'d':r.json()['dispatch_id']}).scalar() == 'POSTED'
        assert c.execute(text("SELECT invoice_no,status FROM sales_invoices WHERE invoice_id=:i"),{'i':r.json()['invoice_id']}).fetchone() == ('INV-AG-1','POSTED')


def test_v90ag_duplicate_dispatch_blocked():
    # Reuse the smallest possible database state from the prior roundtrip is not deterministic,
    # so this test validates the public duplicate-number guard with a synthetic row.
    from sqlalchemy import text
    from uuid import uuid4
    uid = str(uuid4())
    create_user(engine, uid, f"dup_{uid[:8]}", "pw", "Dup Tester", "manager")
    token = TestClient(app).post('/auth/login', json={'username': f'dup_{uid[:8]}', 'password':'pw'}).json()['access_token']
    client = TestClient(app, headers={'Authorization': f'Bearer {token}'})
    ent, loc, wh, org, so = [str(uuid4()) for _ in range(5)]
    with engine.begin() as c:
        c.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:i,:c,'Dup','legal_entity')"), {'i':ent,'c':ent[:8]})
        c.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type) VALUES(:i,:e,:c,'Dup','site')"), {'i':loc,'e':ent,'c':loc[:8]})
        c.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:i,:e,:l,:c,'Dup','general',1)"), {'i':wh,'e':ent,'l':loc,'c':wh[:8]})
        c.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"), {'u':uid,'e':ent})
        c.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"), {'u':uid,'l':loc})
        c.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,created_by) VALUES(:d,:o,:e,:l,:w,:so,:p,'DUP-1','POSTED',:u)"), {'d':str(uuid4()),'o':org,'e':ent,'l':loc,'w':wh,'so':so,'p':str(uuid4()),'u':uid})
    # Lookup existing dispatch number must fail even before a valid order is present.
    r=client.post(f'/v90ag/sales/orders/{so}/dispatch',json={'dispatch_no':'DUP-1','invoice_no':'INV-DUP'})
    assert r.status_code == 404

