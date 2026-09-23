
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
    r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
    oid,eid,lid,pid,mid,wh,lot,plan,pl,orm = [str(uuid4()) for _ in range(10)]
    assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'ER'+eid[:5],'entity_name':'Entity R'},headers=h).status_code==200
    assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'LR'+lid[:5],'location_name':'Plant R'},headers=h).status_code==200
    assert c.post('/admin/warehouses',json={'warehouse_id':wh,'entity_id':eid,'location_id':lid,'warehouse_code':'WR'+wh[:5],'warehouse_name':'RM Warehouse'},headers=h).status_code==200
    assert c.post('/admin/access/entity',json={'user_id':'erpadmin','entity_id':eid},headers=h).status_code==200
    assert c.post('/admin/access/location',json={'user_id':'erpadmin','location_id':lid},headers=h).status_code==200
    assert c.post('/admin/access/warehouse',json={'user_id':'erpadmin','warehouse_id':wh},headers=h).status_code==200
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:m,:o,:e,'PRODUCT',1,'{}'),(:m2,:o,:e,'RAW_MATERIAL',1,'{}')"),{'m':pid,'m2':mid,'o':oid,'e':eid})
        conn.execute(text("INSERT INTO production_plan(plan_id,organization_id,entity_id,location_id,plan_no,period_start,period_end,status,created_by) VALUES(:p,:o,:e,:l,'PR'+:s,'2026-09-10','2026-09-10','APPROVED','erpadmin')"),{'p':plan,'o':oid,'e':eid,'l':lid,'s':eid[:5]})
        conn.execute(text("INSERT INTO production_plan_line(plan_line_id,plan_id,line_no,item_master_id,uom,planned_qty) VALUES(:pl,:p,1,:m,'kg',100)"),{'pl':pl,'p':plan,'m':pid})
        conn.execute(text("INSERT INTO material_requirement_calc(calc_id,plan_id,plan_line_id,recipe_id,material_master_id,requirement_type,gross_qty,scrap_qty,required_qty,uom) VALUES(:c,:p,:pl,:r,:m,'RAW_MATERIAL',50,0,50,'kg')"),{'c':str(uuid4()),'p':plan,'pl':pl,'r':str(uuid4()),'m':mid})
        conn.execute(text("INSERT INTO production_order(production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:o,:org,:e,:l,:p,:pl,:no,:m,100,'kg','APPROVED','erpadmin')"),{'o':orm,'org':oid,'e':eid,'l':lid,'p':plan,'pl':pl,'no':'OR'+eid[:5],'m':pid})
        conn.execute(text("INSERT INTO production_order_material(order_material_id,production_order_id,material_master_id,requirement_type,required_qty,reserved_qty,uom) VALUES(:om,:o,:m,'RAW_MATERIAL',50,50,'kg')"),{'om':str(uuid4()),'o':orm,'m':mid})
        conn.execute(text("INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,lot_code,received_qty,accepted_qty,available_qty,uom,qc_status,status) VALUES(:id,:org,:e,:l,:w,:m,:g,:gl,:s,'LR1',60,60,60,'kg','RELEASED','AVAILABLE')"),{'id':lot,'org':oid,'e':eid,'l':lid,'w':wh,'m':mid,'g':str(uuid4()),'gl':str(uuid4()),'s':str(uuid4())})
    return oid,eid,lid,pid,mid,wh,lot,orm

def manager(c,h,eid,lid):
    uid=str(uuid4()); un='rmgr_'+uid[:8]
    assert c.post('/admin/users',json={'user_id':uid,'username':un,'password':'pw','display_name':'Mgr','role_id':'manager'},headers=h).status_code==200
    assert c.post('/admin/access/entity',json={'user_id':uid,'entity_id':eid},headers=h).status_code==200
    assert c.post('/admin/access/location',json={'user_id':uid,'location_id':lid},headers=h).status_code==200
    return login(c,un,'pw')

def test_issue_requires_approval_and_reduces_lot():
    c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,wh,lot,orm=setup(c,h)
    # Force order back to PENDING to verify gate
    with engine.begin() as conn: conn.execute(text("UPDATE production_order SET status='DRAFT' WHERE production_order_id=:o"),{'o':orm})
    r=c.post(f'/v90r/production-orders/{orm}/issues',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'lines':[{'order_material_id':None,'material_master_id':mid,'lot_id':lot,'warehouse_id':wh,'issued_qty':10,'uom':'kg'}]},headers=h)
    assert r.status_code==409
    with engine.begin() as conn: conn.execute(text("UPDATE production_order SET status='APPROVED' WHERE production_order_id=:o"),{'o':orm})
    r=c.post(f'/v90r/production-orders/{orm}/issues',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'lines':[{'material_master_id':mid,'lot_id':lot,'warehouse_id':wh,'issued_qty':10,'uom':'kg'}]},headers=h)
    assert r.status_code==200,r.text
    with engine.connect() as conn: q=float(conn.execute(text('SELECT available_qty FROM inventory_lot WHERE lot_id=:l'),{'l':lot}).scalar_one())
    assert abs(q-50)<1e-9

def test_batch_requires_issue_and_lifecycle():
    c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,wh,lot,orm=setup(c,h)
    # Create batch before issue -> blocked
    r=c.post(f'/v90r/production-orders/{orm}/batches',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'batch_no':'BR-'+eid[:6]},headers=h); assert r.status_code==409
    assert c.post(f'/v90r/production-orders/{orm}/issues',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'lines':[{'material_master_id':mid,'lot_id':lot,'warehouse_id':wh,'issued_qty':5,'uom':'kg'}]},headers=h).status_code==200
    r=c.post(f'/v90r/production-orders/{orm}/batches',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'batch_no':'BR-'+eid[:6]},headers=h); assert r.status_code==200,r.text; bid=r.json()['batch_id']
    assert c.post(f'/v90r/batches/{bid}/start',json={},headers=h).status_code==200
    assert c.post(f'/v90r/batches/{bid}/start',json={},headers=h).status_code==409
    assert c.post(f'/v90r/batches/{bid}/complete',json={'reason':'completed'},headers=h).status_code==200
    g=c.get(f'/v90r/batches/{bid}',headers=h); assert g.status_code==200; assert g.json()['batch']['status']=='COMPLETED'

def test_duplicate_batch_and_overissue_block():
    c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,wh,lot,orm=setup(c,h)
    assert c.post(f'/v90r/production-orders/{orm}/issues',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'lines':[{'material_master_id':mid,'lot_id':lot,'warehouse_id':wh,'issued_qty':50,'uom':'kg'}]},headers=h).status_code==200
    bad=c.post(f'/v90r/production-orders/{orm}/issues',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'lines':[{'material_master_id':mid,'lot_id':lot,'warehouse_id':wh,'issued_qty':1,'uom':'kg'}]},headers=h)
    assert bad.status_code==409
    r=c.post(f'/v90r/production-orders/{orm}/batches',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'batch_no':'DUP-'+eid[:6]},headers=h); assert r.status_code==200
    dup=c.post(f'/v90r/production-orders/{orm}/batches',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'production_order_id':orm,'batch_no':'DUP-'+eid[:6]},headers=h); assert dup.status_code==409

def test_release_and_migration():
    ms=load_migrations(); assert any(m.version==91 and m.filename=='091_v90r_production_execution.sql' for m in ms)
    c=TestClient(app); h=login(c); assert c.get('/build').json()['production_execution']=='material_issue_batch_start_complete'
