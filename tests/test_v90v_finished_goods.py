from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c):
    r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
    org,eid,lid,wid,pid,po,bid=[str(uuid4()) for _ in range(7)]
    assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'EV'+eid[:5],'entity_name':'Entity V'},headers=h).status_code==200
    assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'LV'+lid[:5],'location_name':'Plant V'},headers=h).status_code==200
    assert c.post('/admin/warehouses',json={'warehouse_id':wid,'entity_id':eid,'location_id':lid,'warehouse_code':'WV'+wid[:5],'warehouse_name':'FG V'},headers=h).status_code==200
    for path,payload in [('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),('/admin/access/warehouse',{'user_id':'erpadmin','warehouse_id':wid})]:
        assert c.post(path,json=payload,headers=h).status_code==200
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:p,:o,:e,'PRODUCT',1,'{}')"),{'p':pid,'o':org,'e':eid})
        conn.execute(text("INSERT INTO production_order(production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:po,:o,:e,:l,:p,:pl,'OV'+:x,:m,100,'kg','APPROVED','erpadmin')"),{'po':po,'o':org,'e':eid,'l':lid,'p':str(uuid4()),'pl':str(uuid4()),'x':eid[:5],'m':pid})
        conn.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:po,:o,:e,:l,'BV'+:x,:m,100,'kg','COMPLETED','erpadmin')"),{'b':bid,'po':po,'o':org,'e':eid,'l':lid,'x':eid[:5],'m':pid})
        conn.execute(text("INSERT INTO production_batch_output(output_id,batch_id,organization_id,entity_id,location_id,good_qty,rework_qty,wastage_qty,uom,yield_pct,wastage_pct,recorded_by) VALUES(:id,:b,:o,:e,:l,90,5,5,'kg',90,5,'erpadmin')"),{'id':str(uuid4()),'b':bid,'o':org,'e':eid,'l':lid})
    return org,eid,lid,wid,bid

def test_fg_receipt_creates_lot_and_inventory():
    c=TestClient(app); h=login(c); org,eid,lid,wid,bid=setup(c,h)
    body={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'fg_lot_code':'FGV1'}
    r=c.post(f'/v90v/batches/{bid}/fg',json=body,headers=h)
    assert r.status_code==200,r.text
    d=r.json(); assert d['quantity']==90.0; assert d['status']=='AVAILABLE'; assert d['qc_status']=='RELEASED'
    g=c.get(f"/v90v/fg/{d['fg_lot_id']}",headers=h); assert g.status_code==200
    with engine.connect() as conn:
        bal=conn.execute(text("SELECT available_qty FROM inventory_stock_balance WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w"),{'o':org,'e':eid,'l':lid,'w':wid}).scalar()
        assert float(bal)==90.0
        mv=conn.execute(text("SELECT COUNT(*) FROM inventory_stock_ledger WHERE reference_type='PRODUCTION_BATCH' AND reference_id=:b AND movement_type='FG_RECEIPT'"),{'b':bid}).scalar()
        assert mv==1

def test_fg_receipt_requires_completed_batch_and_is_idempotently_blocked():
    c=TestClient(app); h=login(c); org,eid,lid,wid,bid=setup(c,h)
    r=c.post(f'/v90v/batches/{bid}/fg',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'fg_lot_code':'FGV2'},headers=h)
    assert r.status_code==200
    r2=c.post(f'/v90v/batches/{bid}/fg',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'fg_lot_code':'FGV3'},headers=h)
    assert r2.status_code==409

def test_rejected_qc_blocks_fg_and_migration():
    c=TestClient(app); h=login(c); org,eid,lid,wid,bid=setup(c,h)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO production_process_qc_decision(decision_id,process_log_id,batch_id,organization_id,entity_id,location_id,decision,decided_by) VALUES(:d,:p,:b,:o,:e,:l,'REJECT','erpadmin')"),{'d':str(uuid4()),'p':str(uuid4()),'b':bid,'o':org,'e':eid,'l':lid})
    r=c.post(f'/v90v/batches/{bid}/fg',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'fg_lot_code':'FGV4'},headers=h)
    assert r.status_code==409
    ms=load_migrations(); assert any(m.version==95 and m.filename=='095_v90v_finished_goods_receipt.sql' for m in ms) and ms[-1].version>=96
    assert c.get('/build').json()['finished_goods']=='batch_output_to_fg_lot_inventory'
