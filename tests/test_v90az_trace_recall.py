from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def setup_env():
    uid=str(uuid4()); uname='az_'+uid[:8]
    create_user(engine,uid,uname,'pw','AZ Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); ids={k:str(uuid4()) for k in ['e','l','w','p','f','b','so','sol','d','dl','inv']}
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AZ','legal_entity',1)"),{'e':ids['e'],'c':'AZ'+ids['e'][:6]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AZ','site',1)"),{'l':ids['l'],'e':ids['e'],'c':'AZL'+ids['l'][:5]})
        db.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:w,:e,:l,:c,'AZ','general',1)"),{'w':ids['w'],'e':ids['e'],'l':ids['l'],'c':'AZW'+ids['w'][:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':ids['e']})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':ids['l']})
        db.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:po,:o,:e,:l,'AZB','P1',100,'kg','COMPLETED',:u)"),{'b':ids['b'],'po':str(uuid4()),'o':org,'e':ids['e'],'l':ids['l'],'u':uid})
        db.execute(text("INSERT INTO finished_goods_lot(fg_lot_id,organization_id,entity_id,location_id,warehouse_id,batch_id,product_master_id,sku_id,fg_lot_code,mfg_date,expiry_date,quantity,available_qty,uom,qc_status,status,created_by) VALUES(:f,:o,:e,:l,:w,:b,'P1','SKU1','AZFG','2026-09-01','2027-03-01',100,100,'kg','RELEASED','AVAILABLE',:u)"),{'f':ids['f'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'b':ids['b'],'u':uid})
        db.execute(text("INSERT INTO packing_run(packing_run_id,organization_id,entity_id,location_id,warehouse_id,source_fg_lot_id,sku_id,run_no,source_qty,packed_qty,status,created_by) VALUES(:p,:o,:e,:l,:w,:f,'SKU1','AZPR',100,100,'COMPLETED',:u)"),{'p':ids['p'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'f':ids['f'],'u':uid})
        db.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:p,:o,:e,:l,:w,:pr,:f,'SKU1','AZPK',200,100,100,'kg','2026-09-01','2027-03-01','AVAILABLE','RELEASED',:u)"),{'p':ids['p'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'pr':ids['p'],'f':ids['f'],'u':uid})
        db.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:so,:o,:e,:l,:w,:c,'AZSO'||:so,'APPROVED','APPROVED','APPROVED','ALLOCATED',0,0,0,0,0,:u)"),{'so':ids['so'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'c':str(uuid4()),'u':uid})
        db.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,created_by,posted_at) VALUES(:d,:o,:e,:l,:w,:so,:pk,'AZD','POSTED',:u,'2026-09-02')"),{'d':ids['d'],'o':org,'e':ids['e'],'l':ids['l'],'w':ids['w'],'so':ids['so'],'pk':str(uuid4()),'u':uid})
        db.execute(text("INSERT INTO dispatch_lines(dispatch_line_id,dispatch_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,dispatched_qty) VALUES(:dl,:d,:sol,:a,'SKU1',:p,30)"),{'dl':ids['dl'],'d':ids['d'],'sol':str(uuid4()),'a':str(uuid4()),'p':ids['p']})
    return c,ids,org

def test_recall_trace_and_withdrawal():
    c,ids,org=setup_env()
    r=c.post('/v90az/recalls',json={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'recall_no':'AZR1','title':'Recall','reason':'QC issue','source_type':'PACKED_FG_LOT','source_id':ids['p']})
    assert r.status_code==200,r.text; rid=r.json()['recall_id']
    tr=c.get(f'/v90az/recalls/{rid}/trace-forward'); assert tr.status_code==200; stages=[x['stage'] for x in tr.json()['trace']]; assert 'PRODUCTION_BATCH' in stages and 'DISPATCH' in stages
    w=c.post(f'/v90az/recalls/{rid}/withdraw',json={'lot_type':'PACKED_FG_LOT','lot_id':ids['p'],'quantity':25,'reason':'Quarantine','warehouse_id':ids['w']})
    assert w.status_code==200 and w.json()['withdrawn_qty']==25.0
    w2=c.post(f'/v90az/recalls/{rid}/withdraw',json={'lot_type':'PACKED_FG_LOT','lot_id':ids['p'],'quantity':80,'reason':'Too much'})
    assert w2.status_code==422

def test_recall_duplicate_number_and_list():
    c,ids,org=setup_env(); payload={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l'],'recall_no':'AZR2','title':'Recall','reason':'Issue','source_type':'PACKED_FG_LOT','source_id':ids['p']}
    assert c.post('/v90az/recalls',json=payload).status_code==200
    assert c.post('/v90az/recalls',json=payload).status_code==409
    assert c.get('/v90az/recalls',params={'organization_id':org,'entity_id':ids['e'],'location_id':ids['l']}).json()['items']

def test_v90az_migration_125():
    from app.migrations import load_migrations
    assert any(m.version==125 and m.filename=='125_v90az_batch_traceability_recall.sql' for m in load_migrations())
