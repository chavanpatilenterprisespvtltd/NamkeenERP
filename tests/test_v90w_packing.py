from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c):
 r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
 return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
 org,eid,lid,wid,pid,fgid,skuid,packid=[str(uuid4()) for _ in range(8)]
 assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'EW'+eid[:5],'entity_name':'Entity W'},headers=h).status_code==200
 assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'LW'+lid[:5],'location_name':'Plant W'},headers=h).status_code==200
 assert c.post('/admin/warehouses',json={'warehouse_id':wid,'entity_id':eid,'location_id':lid,'warehouse_code':'WW'+wid[:5],'warehouse_name':'Packing'},headers=h).status_code==200
 for path,payload in [('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),('/admin/access/warehouse',{'user_id':'erpadmin','warehouse_id':wid})]: assert c.post(path,json=payload,headers=h).status_code==200
 with engine.begin() as x:
  x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'PRODUCT',1,'{}')"),{'id':pid,'o':org,'e':eid})
  x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'SKU',1,:d)"),{'id':skuid,'o':org,'e':eid,'d':'{"pack_size_id":"'+packid+'","product_id":"'+pid+'"}'})
  x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'PACK_SIZE',1,'{}')"),{'id':packid,'o':org,'e':eid})
  x.execute(text("INSERT INTO finished_goods_lot(fg_lot_id,organization_id,entity_id,location_id,warehouse_id,batch_id,product_master_id,fg_lot_code,mfg_date,quantity,available_qty,uom,qc_status,status,created_by) VALUES(:f,:o,:e,:l,:w,:b,:p,'BFG',CURRENT_TIMESTAMP,100,100,'kg','RELEASED','AVAILABLE','erpadmin')"),{'f':fgid,'o':org,'e':eid,'l':lid,'w':wid,'b':str(uuid4()),'p':pid})
  x.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:i,'kg',50)"),{'o':org,'e':eid,'l':lid,'w':wid,'i':packid})
 return org,eid,lid,wid,fgid,skuid,packid

def test_packing_start_complete_creates_packed_fg_and_consumes_material():
 c=TestClient(app); h=login(c); org,eid,lid,wid,fg,sku,pack=setup(c,h)
 r=c.post('/v90w/packing-runs',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'source_fg_lot_id':fg,'sku_id':sku,'run_no':'PW1','source_qty':20,'materials':[{'material_master_id':pack,'quantity':2,'uom':'kg'}]},headers=h)
 assert r.status_code==200,r.text; rid=r.json()['packing_run_id']
 assert c.post(f'/v90w/packing-runs/{rid}/start',headers=h).status_code==200
 r2=c.post(f'/v90w/packing-runs/{rid}/complete',json={'lot_code':'PK1','pack_count':40,'net_qty':20},headers=h)
 assert r2.status_code==200,r2.text; d=r2.json(); assert d['status']=='COMPLETED'
 with engine.connect() as x:
  src=x.execute(text('SELECT available_qty FROM finished_goods_lot WHERE fg_lot_id=:f'),{'f':fg}).scalar(); assert float(src)==80
  bal=x.execute(text("SELECT available_qty FROM inventory_stock_balance WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND uom='kg'"),{'o':org,'e':eid,'l':lid,'w':wid,'i':pack}).scalar(); assert float(bal)==48
  pbal=x.execute(text("SELECT available_qty FROM inventory_stock_balance WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND uom='kg'"),{'o':org,'e':eid,'l':lid,'w':wid,'i':sku}).scalar(); assert float(pbal)==20

def test_packing_guards():
 c=TestClient(app); h=login(c); org,eid,lid,wid,fg,sku,pack=setup(c,h)
 r=c.post('/v90w/packing-runs',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'source_fg_lot_id':fg,'sku_id':sku,'run_no':'PW2','source_qty':60,'materials':[]},headers=h); assert r.status_code==200
 rid=r.json()['packing_run_id']; assert c.post(f'/v90w/packing-runs/{rid}/start',headers=h).status_code==200
 bad=c.post(f'/v90w/packing-runs/{rid}/complete',json={'lot_code':'PK2','pack_count':120,'net_qty':60},headers=h); assert bad.status_code==409

def test_migration_and_build():
 ms=load_migrations(); assert any(m.version==96 and m.filename=='096_v90w_packing_sku_conversion.sql' for m in ms)
 assert any(m.version==97 and m.filename=='097_v90x_packing_qc.sql' for m in ms)
 assert cbuild().status_code==200

def cbuild(): return TestClient(app).get('/build')
