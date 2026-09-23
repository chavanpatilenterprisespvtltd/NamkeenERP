from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_accounting():
    uid=str(uuid4()); uname=f'aj_{uid[:8]}'
    create_user(engine,uid,uname,'pw','AJ Tester','manager')
    tok=make_access_token(UserRecord(uid,uname,'manager')); c=TestClient(app,headers={'Authorization':f'Bearer {tok}'})
    ids={k:str(uuid4()) for k in ['e','l','w','cust','sku','lot','so','sol','disp','dl','inv','invl','accrual']}; org=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AJ','legal_entity',1)"),{'e':ids['e'],'ec':'AJ'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AJ','site',1)"),{'l':ids['l'],'e':ids['e'],'lc':'AJL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AJ','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'wc':'AJW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:c,:o,'CUSTOMER',:e,1,'{}'),(:s,:o,'SKU',:e,1,'{}')"),{'c':ids['cust'],'s':ids['sku'],'o':org,'e':ids['e']})
        order_no='SO-AJ-'+ids['so'][:8]; dispatch_no='D-AJ-'+ids['disp'][:8]; invoice_no='INV-AJ-'+ids['inv'][:8]; return_no='RET-AJ-'+ids['so'][:8]
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:so,:o,:e,:l,:w,:c,:order_no,'DISPATCHED','PASS','PASS','DISPATCHED',100,0,100,18,118,:u)"),{'so':ids['so'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'c':ids['cust'],'u':uid,'order_no':order_no})
        db.execute(text("INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price,discount_pct,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) VALUES(:sl,:so,:s,10,10,0,0,100,18,18,118)"),{'sl':ids['sol'],'so':ids['so'],'s':ids['sku']})
        db.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,created_by) VALUES(:d,:o,:e,:l,:w,:so,:p,:dispatch_no,'POSTED',:u)"),{'d':ids['disp'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'so':ids['so'],'p':str(uuid4()),'u':uid,'dispatch_no':dispatch_no})
        db.execute(text("INSERT INTO dispatch_lines(dispatch_line_id,dispatch_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,dispatched_qty,uom) VALUES(:dl,:d,:sl,:a,:s,:lot,'AJ',10,'kg')"),{'dl':ids['dl'],'d':ids['disp'],'sl':ids['sol'],'a':str(uuid4()),'s':ids['sku'],'lot':ids['lot']})
        db.execute(text("INSERT INTO sales_invoices(invoice_id,organization_id,entity_id,location_id,sales_order_id,dispatch_id,invoice_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:i,:o,:e,:l,:so,:d,:invoice_no,'POSTED',100,0,100,18,118,:u)"),{'i':ids['inv'],'o':org,'e':ids['e'],'l':ids['l'],'so':ids['so'],'d':ids['disp'],'u':uid,'invoice_no':invoice_no})
        db.execute(text("INSERT INTO sales_invoice_lines(invoice_line_id,invoice_id,sales_order_line_id,sku_id,quantity,unit_price,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) VALUES(:il,:i,:sl,:s,10,10,0,100,18,18,118)"),{'il':ids['invl'],'i':ids['inv'],'sl':ids['sol'],'s':ids['sku']})
        r=str(uuid4()); rl=str(uuid4()); h=str(uuid4()); ids.update(r=r,rl=rl,h=h)
        db.execute(text("INSERT INTO sales_returns(sales_return_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,customer_id,return_no,status,reason,created_by) VALUES(:r,:o,:e,:l,:w,:so,:c,:return_no,'DISPOSITIONED','AJ',:u)"),{'r':r,'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'so':ids['so'],'c':ids['cust'],'u':uid,'return_no':return_no})
        db.execute(text("INSERT INTO sales_return_lines(sales_return_line_id,sales_return_id,dispatch_line_id,sales_order_line_id,sku_id,packed_fg_lot_id,lot_code,requested_qty,received_qty,disposition_status) VALUES(:rl,:r,:dl,:sl,:s,:lot,'AJ',4,4,'SALEABLE')"),{'rl':rl,'r':r,'dl':ids['dl'],'sl':ids['sol'],'s':ids['sku'],'lot':ids['lot']})
        db.execute(text("INSERT INTO incentive_accruals(incentive_accrual_id,incentive_rule_id,organization_id,entity_id,location_id,salesperson_user_id,sku_id,sales_order_id,quantity,unit_cost,gross_net_sales,net_sales,margin_pct,incentive_amount,status,reason,created_by) VALUES(:a,:ir,:o,:e,:l,:sp,:s,:so,10,5,100,100,100,10,'ACCRUED','AJ',:u)"),{'a':ids['accrual'],'ir':str(uuid4()),'o':org,'e':ids['e'],'l':ids['l'],'sp':uid,'s':ids['sku'],'so':ids['so'],'u':uid})
    return c,ids


def test_credit_note_and_reversal():
    c,ids=setup_accounting()
    r=c.post(f"/v90aj/returns/{ids['r']}/credit-note",json={'credit_note_no':'CN-AJ-1-'+ids['r'][:8],'reason':'customer return'})
    assert r.status_code==200,r.text
    data=r.json(); assert data['grand_total']==47.2; assert data['gst_total']==7.2; assert data['incentive_reversal_total']==4
    with engine.connect() as db:
        assert float(db.execute(text('SELECT amount FROM customer_credit_adjustments WHERE sales_return_id=:r'),{'r':ids['r']}).scalar())==47.2
        assert float(db.execute(text('SELECT reversal_amount FROM incentive_reversals WHERE sales_return_id=:r'),{'r':ids['r']}).scalar())==4
    again=c.post(f"/v90aj/returns/{ids['r']}/credit-note",json={'credit_note_no':'CN-AJ-1-'+ids['r'][:8]})
    assert again.status_code==200 and again.json()['idempotent'] is True


def test_credit_note_requires_disposition():
    c,ids=setup_accounting()
    with engine.begin() as db: db.execute(text("UPDATE sales_returns SET status='RECEIVED_QC_HOLD' WHERE sales_return_id=:r"),{'r':ids['r']})
    r=c.post(f"/v90aj/returns/{ids['r']}/credit-note",json={'credit_note_no':'CN-AJ-2-'+ids['r'][:8]})
    assert r.status_code==409
