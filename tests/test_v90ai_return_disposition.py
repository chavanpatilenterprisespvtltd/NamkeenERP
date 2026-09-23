from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_return():
    uid=str(uuid4()); uname=f'ai_{uid[:8]}'
    create_user(engine,uid,uname,'pw','AI Tester','manager')
    tok=make_access_token(UserRecord(uid,uname,'manager')); c=TestClient(app,headers={'Authorization':f'Bearer {tok}'})
    ids={k:str(uuid4()) for k in ['e','l','w','cust','sku','lot','so','sol','disp','dl']}; org=str(uuid4()); order_no='SO-AI-'+ids['so'][:8]; dispatch_no='D-AI-'+ids['disp'][:8]; return_no='RET-AI-'+ids['so'][:8]
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AI','legal_entity',1)"),{'e':ids['e'],'ec':'AI'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AI','site',1)"),{'l':ids['l'],'e':ids['e'],'lc':'AIL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AI','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'wc':'AIW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:c,:o,'CUSTOMER',:e,1,'{}'),(:s,:o,'SKU',:e,1,'{}')"),{'c':ids['cust'],'s':ids['sku'],'o':org,'e':ids['e']})
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:so,:o,:e,:l,:w,:c,:order_no,'DISPATCHED','PASS','PASS','DISPATCHED',100,0,100,0,100,:u)"),{'so':ids['so'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'c':ids['cust'],'u':uid,'order_no':order_no})
        db.execute(text("INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price,discount_pct,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) VALUES(:sl,:so,:s,10,10,0,0,100,0,0,100)"),{'sl':ids['sol'],'so':ids['so'],'s':ids['sku']})
        db.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,created_by) VALUES(:d,:o,:e,:l,:w,:so,:p,:dispatch_no,'POSTED',:u)"),{'d':ids['disp'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'so':ids['so'],'p':str(uuid4()),'u':uid,'dispatch_no':dispatch_no})
        db.execute(text("INSERT INTO dispatch_lines(dispatch_line_id,dispatch_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,dispatched_qty,uom) VALUES(:dl,:d,:sl,:a,:s,:lot,'AI',10,'kg')"),{'dl':ids['dl'],'d':ids['disp'],'sl':ids['sol'],'a':str(uuid4()),'s':ids['sku'],'lot':ids['lot']})
        db.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:lot,:o,:e,:l,:w,:pr,:src,:s,'AI',10,10,0,'kg','2026-09-01','2099-12-31','DISPATCHED','RELEASED',:u)"),{'lot':ids['lot'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'pr':str(uuid4()),'src':str(uuid4()),'s':ids['sku'],'u':uid})
        db.execute(text("INSERT INTO sales_returns(sales_return_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,customer_id,return_no,status,reason,created_by) VALUES(:r,:o,:e,:l,:w,:so,:c,:return_no,'RECEIVED_QC_HOLD','AI',:u)"),{'r':ids['so'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'so':ids['so'],'c':ids['cust'],'u':uid,'return_no':return_no})
        # line/hold IDs intentionally separate
        rline=str(uuid4()); hold=str(uuid4()); ids['rline']=rline; ids['hold']=hold; ids['ret']=ids['so']
        db.execute(text("INSERT INTO sales_return_lines(sales_return_line_id,sales_return_id,dispatch_line_id,sales_order_line_id,sku_id,packed_fg_lot_id,lot_code,requested_qty,received_qty,disposition_status,reason) VALUES(:l,:r,:dl,:sl,:s,:lot,'AI',4,4,'QC_HOLD','AI')"),{'l':rline,'r':ids['ret'],'dl':ids['dl'],'sl':ids['sol'],'s':ids['sku'],'lot':ids['lot']})
        db.execute(text("INSERT INTO return_hold_lots(return_hold_id,sales_return_id,sales_return_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,status,created_by) VALUES(:h,:r,:l,:o,:e,:loc,:w,:s,:lot,'AI',4,'QC_HOLD',:u)"),{'h':hold,'r':ids['ret'],'l':rline,'o':org,'e':ids['e'],'loc':ids['l'],'w':ids['w'],'s':ids['sku'],'lot':ids['lot'],'u':uid})
        db.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:i,'kg',0)"),{'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'i':ids['sku']})
    return c,ids


def test_saleable_disposition_returns_to_stock():
    c,ids=setup_return(); r=c.post(f"/v90ai/returns/{ids['ret']}/lines/{ids['rline']}/disposition",json={'disposition':'SALEABLE','quantity':4,'reason':'sealed and acceptable'}); assert r.status_code==200,r.text
    with engine.connect() as db:
        assert float(db.execute(text('SELECT available_qty FROM inventory_stock_balance WHERE item_master_id=:i'),{'i':ids['sku']}).scalar())==4
        assert float(db.execute(text('SELECT available_qty FROM packed_fg_lot WHERE packed_fg_lot_id=:l'),{'l':ids['lot']}).scalar())==4
        assert db.execute(text('SELECT disposition_status FROM sales_return_lines WHERE sales_return_line_id=:l'),{'l':ids['rline']}).scalar()=='SALEABLE'
        assert db.execute(text('SELECT status FROM sales_returns WHERE sales_return_id=:r'),{'r':ids['ret']}).scalar()=='DISPOSITIONED'
        assert db.execute(text("SELECT movement_type FROM inventory_stock_ledger WHERE reference_id=:r ORDER BY created_at DESC LIMIT 1"),{'r':ids['ret']}).scalar()=='RETURN_IN'


def test_damage_disposition_is_non_saleable_and_audited():
    c,ids=setup_return(); r=c.post(f"/v90ai/returns/{ids['ret']}/lines/{ids['rline']}/disposition",json={'disposition':'DAMAGE','quantity':4}); assert r.status_code==200,r.text
    with engine.connect() as db:
        assert float(db.execute(text('SELECT available_qty FROM inventory_stock_balance WHERE item_master_id=:i'),{'i':ids['sku']}).scalar())==0
        assert db.execute(text('SELECT disposition FROM return_disposition_history WHERE sales_return_id=:r'),{'r':ids['ret']}).scalar()=='DAMAGE'
        assert db.execute(text('SELECT status FROM return_hold_lots WHERE return_hold_id=:h'),{'h':ids['hold']}).scalar()=='DISPOSED'


def test_invalid_disposition_and_overage_blocked():
    c,ids=setup_return();
    assert c.post(f"/v90ai/returns/{ids['ret']}/lines/{ids['rline']}/disposition",json={'disposition':'UNKNOWN','quantity':1}).status_code==422
    assert c.post(f"/v90ai/returns/{ids['ret']}/lines/{ids['rline']}/disposition",json={'disposition':'REPACK','quantity':5}).status_code==409
