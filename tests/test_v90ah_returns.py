from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_state():
    uid=str(uuid4()); uname=f'ah_{uid[:8]}'
    create_user(engine,uid,uname,'pw','AH Tester','manager')
    tok=make_access_token(UserRecord(uid,uname,'manager')); c=TestClient(app,headers={'Authorization':f'Bearer {tok}'})
    ids={k:str(uuid4()) for k in ['e','l','w','cust','sku','lot','so','sol','disp','dl']}; org=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AH','legal_entity',1)"),{'e':ids['e'],'ec':'AH'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AH','site',1)"),{'l':ids['l'],'e':ids['e'],'lc':'AHL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AH','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'wc':'AHW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:c,:o,'CUSTOMER',:e,1,'{}'),(:s,:o,'SKU',:e,1,'{}')"),{'c':ids['cust'],'s':ids['sku'],'o':org,'e':ids['e']})
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:so,:o,:e,:l,:w,:c,:order_no,'DISPATCHED','PASS','PASS','DISPATCHED',100,0,100,0,100,:u)"),{'so':ids['so'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'c':ids['cust'],'u':uid,'order_no':'SO-AH-'+ids['so'][:8]})
        db.execute(text("INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price,discount_pct,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) VALUES(:sl,:so,:s,10,10,0,0,100,0,0,100)"),{'sl':ids['sol'],'so':ids['so'],'s':ids['sku']})
        db.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,created_by) VALUES(:d,:o,:e,:l,:w,:so,:p,'D-AH','POSTED',:u)"),{'d':ids['disp'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'so':ids['so'],'p':str(uuid4()),'u':uid})
        db.execute(text("INSERT INTO dispatch_lines(dispatch_line_id,dispatch_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,dispatched_qty,uom) VALUES(:dl,:d,:sl,:a,:s,:lot,'AHLOT',10,'kg')"),{'dl':ids['dl'],'d':ids['disp'],'sl':ids['sol'],'a':str(uuid4()),'s':ids['sku'],'lot':ids['lot']})
        db.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:lot,:o,:e,:l,:w,:pr,:src,:s,'AHLOT',10,0,0,'kg','2026-09-01','2099-12-31','AVAILABLE','RELEASED',:u)"),{'lot':ids['lot'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'pr':str(uuid4()),'src':str(uuid4()),'s':ids['sku'],'u':uid})
    return c,ids


def test_return_request_and_receive_hold():
    c,ids=setup_state(); r=c.post(f"/v90ah/sales/orders/{ids['so']}/returns",json={'return_no':'RET-AH-1','lines':[{'dispatch_line_id':ids['dl'],'requested_qty':3,'reason':'customer return'}]}); assert r.status_code==200,r.text
    rid=r.json()['sales_return_id']
    r=c.post(f'/v90ah/returns/{rid}/receive'); assert r.status_code==200,r.text and r.json()['status']=='RECEIVED_QC_HOLD'
    g=c.get(f'/v90ah/returns/{rid}'); assert g.status_code==200; assert g.json()['return']['status']=='RECEIVED_QC_HOLD'; assert float(g.json()['lines'][0]['received_qty'])==3
    with engine.connect() as db:
        assert db.execute(text('SELECT status FROM return_hold_lots WHERE sales_return_id=:r'),{'r':rid}).scalar()=='QC_HOLD'
        assert db.execute(text('SELECT available_qty FROM packed_fg_lot WHERE packed_fg_lot_id=:l'),{'l':ids['lot']}).scalar()==0


def test_return_cannot_exceed_dispatched_balance_or_duplicate_number():
    c,ids=setup_state(); payload={'return_no':'RET-AH-2','lines':[{'dispatch_line_id':ids['dl'],'requested_qty':8}]}
    r=c.post(f"/v90ah/sales/orders/{ids['so']}/returns",json=payload); assert r.status_code==200
    r2=c.post(f"/v90ah/sales/orders/{ids['so']}/returns",json={'return_no':'RET-AH-2','lines':[{'dispatch_line_id':ids['dl'],'requested_qty':1}]}); assert r2.status_code==409
    r3=c.post(f"/v90ah/sales/orders/{ids['so']}/returns",json={'return_no':'RET-AH-3','lines':[{'dispatch_line_id':ids['dl'],'requested_qty':3}]}); assert r3.status_code==409
