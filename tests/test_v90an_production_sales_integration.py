from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_env():
    uid = str(uuid4()); uname = 'an_' + uid[:8]
    create_user(engine, uid, uname, 'pw', 'AN Tester', 'manager')
    client = TestClient(app, headers={'Authorization': 'Bearer ' + make_access_token(UserRecord(uid, uname, 'manager'))})
    org,e,l,w,cust,so,batch,fg,pack,pfg,alloc,pick,disp,inv = [str(uuid4()) for _ in range(14)]
    pm,sku = str(uuid4()), str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:ec,'AN','legal_entity',1)"), {'e':e,'ec':'AN'+e[:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:lc,'AN','site',1)"), {'l':l,'e':e,'lc':'ANL'+l[:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:wc,'AN','general',1)"), {'w':w,'e':e,'l':l,'wc':'ANW'+w[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"), {'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"), {'u':uid,'l':l})
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at) VALUES(:so,:o,:e,:l,:w,:c,:order_no,'DISPATCHED','PASS','PASS','DISPATCHED',100,0,100,0,100,:u,CURRENT_TIMESTAMP)"), {'so':so,'o':org,'e':e,'l':l,'w':w,'c':cust,'order_no':'AN-SO-'+so[:8],'u':uid})
        db.execute(text("INSERT INTO production_batch(batch_id,organization_id,entity_id,location_id,production_order_id,batch_no,product_master_id,planned_qty,uom,status,created_by,created_at) VALUES(:b,:o,:e,:l,:po,:bn,:pm,10,'kg','COMPLETED',:u,CURRENT_TIMESTAMP)"), {'b':batch,'o':org,'e':e,'l':l,'po':str(uuid4()),'bn':'AN-BATCH-'+batch[:8],'pm':pm,'u':uid})
        db.execute(text("INSERT INTO production_process_qc_decision(decision_id,process_log_id,batch_id,organization_id,entity_id,location_id,decision,reason,source,decided_by,decided_at) VALUES(:id,:pl,:b,:o,:e,:l,'RELEASE',NULL,'PROCESS_QC',:u,CURRENT_TIMESTAMP)"), {'id':str(uuid4()),'pl':str(uuid4()),'b':batch,'o':org,'e':e,'l':l,'u':uid})
        db.execute(text("INSERT INTO finished_goods_lot(fg_lot_id,organization_id,entity_id,location_id,warehouse_id,batch_id,product_master_id,sku_id,fg_lot_code,mfg_date,expiry_date,quantity,available_qty,uom,qc_status,status,created_by,created_at) VALUES(:fg,:o,:e,:l,:w,:b,:pm,:s,:code,'2026-09-01',NULL,10,10,'kg','RELEASED','AVAILABLE',:u,CURRENT_TIMESTAMP)"), {'fg':fg,'o':org,'e':e,'l':l,'w':w,'b':batch,'pm':pm,'s':sku,'code':'AN-FG-'+fg[:8],'u':uid})
        db.execute(text("INSERT INTO packing_run(packing_run_id,organization_id,entity_id,location_id,warehouse_id,source_fg_lot_id,sku_id,run_no,source_qty,packed_qty,status,created_by,created_at) VALUES(:p,:o,:e,:l,:w,:fg,:s,:run,10,10,'COMPLETED',:u,CURRENT_TIMESTAMP)"), {'p':pack,'o':org,'e':e,'l':l,'w':w,'fg':fg,'s':sku,'run':'AN-PACK-'+pack[:8],'u':uid})
        db.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by,created_at) VALUES(:pfg,:o,:e,:l,:w,:p,:fg,:s,:code,20,10,10,'kg','2026-09-01',NULL,'AVAILABLE','RELEASED',:u,CURRENT_TIMESTAMP)"), {'pfg':pfg,'o':org,'e':e,'l':l,'w':w,'p':pack,'fg':fg,'s':sku,'code':'AN-PACKED-'+pfg[:8],'u':uid})
        sol = str(uuid4())
        db.execute(text("INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) VALUES(:sl,:so,:s,10,10,0,100,0,0,100)"), {'sl':sol,'so':so,'s':sku})
        db.execute(text("INSERT INTO sales_order_allocations(sales_order_allocation_id,sales_order_id,sales_order_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,fg_allocation_group_id,status,created_by,created_at) VALUES(:a,:so,:sl,:o,:e,:l,:w,:s,:pfg,:code,10,:g,'DISPATCHED',:u,CURRENT_TIMESTAMP)"), {'a':alloc,'so':so,'sl':sol,'o':org,'e':e,'l':l,'w':w,'s':sku,'pfg':pfg,'code':'AN-PACKED-'+pfg[:8],'g':str(uuid4()),'u':uid})
        db.execute(text("INSERT INTO dispatch_pick_lists(pick_list_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,status,created_by,created_at,picked_at) VALUES(:p,:o,:e,:l,:w,:so,'PICKED',:u,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {'p':pick,'o':org,'e':e,'l':l,'w':w,'so':so,'u':uid})
        db.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,created_by,posted_at) VALUES(:d,:o,:e,:l,:w,:so,:p,:dn,'POSTED',:u,CURRENT_TIMESTAMP)"), {'d':disp,'o':org,'e':e,'l':l,'w':w,'so':so,'p':pick,'dn':'AN-DISP-'+disp[:8],'u':uid})
        db.execute(text("INSERT INTO sales_invoices(invoice_id,organization_id,entity_id,location_id,sales_order_id,dispatch_id,invoice_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by,created_at) VALUES(:i,:o,:e,:l,:so,:d,:in,'POSTED',100,0,100,0,100,:u,CURRENT_TIMESTAMP)"), {'i':inv,'o':org,'e':e,'l':l,'so':so,'d':disp,'in':'AN-INV-'+inv[:8],'u':uid})
    return client, so


def test_trace_and_validate_pass():
    c, so = setup_env()
    r = c.get(f'/v90an/integration/sales-orders/{so}/trace'); assert r.status_code == 200, r.text
    assert r.json()['dispatch']['status'] == 'POSTED'
    r = c.post(f'/v90an/integration/sales-orders/{so}/validate'); assert r.status_code == 200, r.text
    assert r.json()['status'] == 'PASS'; assert r.json()['failure_count'] == 0


def test_validation_catches_missing_invoice():
    c, so = setup_env()
    with engine.begin() as db:
        db.execute(text("DELETE FROM sales_invoices WHERE sales_order_id=:so"), {'so':so})
    r = c.post(f'/v90an/integration/sales-orders/{so}/validate'); assert r.status_code == 200, r.text
    assert r.json()['status'] == 'FAIL'
    assert any(x['check'] == 'invoice_posted' and not x['passed'] for x in r.json()['checks'])
