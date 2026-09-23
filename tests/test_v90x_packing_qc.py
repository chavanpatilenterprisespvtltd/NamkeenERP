from __future__ import annotations
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c):
 r=c.post('/auth/login',json={'username':'erpadmin','password':'change-me'}); assert r.status_code==200,r.text
 return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup_pack(c,h):
 org,eid,lid,wid,pid,fgid,skuid,packid=[str(uuid4()) for _ in range(8)]
 for path,payload in [
 ('/admin/entities',{'entity_id':eid,'entity_code':'EX'+eid[:5],'entity_name':'Entity X'}),
 ('/admin/locations',{'location_id':lid,'entity_id':eid,'location_code':'LX'+lid[:5],'location_name':'Plant X'}),
 ('/admin/warehouses',{'warehouse_id':wid,'entity_id':eid,'location_id':lid,'warehouse_code':'WX'+wid[:5],'warehouse_name':'Packing'})]:
  assert c.post(path,json=payload,headers=h).status_code==200
 for path,payload in [('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),('/admin/access/warehouse',{'user_id':'erpadmin','warehouse_id':wid})]: assert c.post(path,json=payload,headers=h).status_code==200
 with engine.begin() as x:
  x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'PRODUCT',1,'{}')"),{'id':pid,'o':org,'e':eid})
  x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'PACK_SIZE',1,'{}')"),{'id':packid,'o':org,'e':eid})
  x.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:id,:o,:e,'SKU',1,:d)"),{'id':skuid,'o':org,'e':eid,'d':'{"pack_size_id":"'+packid+'","product_id":"'+pid+'"}'})
  x.execute(text("INSERT INTO finished_goods_lot(fg_lot_id,organization_id,entity_id,location_id,warehouse_id,batch_id,product_master_id,fg_lot_code,mfg_date,quantity,available_qty,uom,qc_status,status,created_by) VALUES(:f,:o,:e,:l,:w,:b,:p,'BFGX',CURRENT_TIMESTAMP,100,100,'kg','RELEASED','AVAILABLE','erpadmin')"),{'f':fgid,'o':org,'e':eid,'l':lid,'w':wid,'b':str(uuid4()),'p':pid})
  x.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:i,'kg',20)"),{'o':org,'e':eid,'l':lid,'w':wid,'i':packid})
 r=c.post('/v90w/packing-runs',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':wid,'source_fg_lot_id':fgid,'sku_id':skuid,'run_no':'PX1','source_qty':10,'materials':[{'material_master_id':packid,'quantity':1,'uom':'kg'}]},headers=h); assert r.status_code==200,r.text
 rid=r.json()['packing_run_id']; assert c.post(f'/v90w/packing-runs/{rid}/start',headers=h).status_code==200
 r=c.post(f'/v90w/packing-runs/{rid}/complete',json={'lot_code':'PKX1','pack_count':20,'net_qty':10},headers=h); assert r.status_code==200,r.text
 return rid

def test_packing_qc_hold_and_pass():
 c=TestClient(app); h=login(c); rid=setup_pack(c,h)
 bad=c.post(f'/v90x/packing-runs/{rid}/qc',json={'net_weight_target':0.5,'net_weight_actual':0.53,'weight_tolerance_pct':2,'seal_status':'PASS','label_status':'PASS','nitrogen_status':'FAIL','visual_status':'PASS'},headers=h)
 assert bad.status_code==200; assert bad.json()['overall_status']=='HOLD'
 with engine.connect() as x:
  st=x.execute(text("SELECT qc_status,status FROM packed_fg_lot WHERE packing_run_id=:r"),{'r':rid}).first(); assert tuple(st)==('HOLD','HOLD')
 good=c.post(f'/v90x/packing-runs/{rid}/qc',json={'net_weight_target':0.5,'net_weight_actual':0.505,'weight_tolerance_pct':2,'seal_status':'PASS','label_status':'PASS','nitrogen_status':'PASS','visual_status':'PASS','checks':[{'parameter':'seal','observed_value':'OK','status':'PASS'}]},headers=h)
 assert good.status_code==200; assert good.json()['overall_status']=='PASS'
 rel=c.post(f'/v90x/packing-runs/{rid}/qc/release',headers=h); assert rel.status_code==200

def test_packing_qc_guards_and_migration():
 c=TestClient(app); h=login(c)
 assert any(m.version==97 and m.filename=='097_v90x_packing_qc.sql' for m in load_migrations())
 assert any(m.version==97 and m.filename=='097_v90x_packing_qc.sql' for m in load_migrations())
 bad=c.post(f'/v90x/packing-runs/{uuid4()}/qc/release',headers=h); assert bad.status_code==404
