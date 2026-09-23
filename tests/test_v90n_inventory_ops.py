from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
 r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text; return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup_scope(c,h):
 eid,lid,w1,w2,m=[str(uuid4()) for _ in range(5)]
 for path,payload in [
  ('/admin/entities',{'entity_id':eid,'entity_code':'EN'+eid[:5],'entity_name':'Entity N'}),
  ('/admin/locations',{'location_id':lid,'entity_id':eid,'location_code':'LC'+lid[:5],'location_name':'Plant N'}),
  ('/admin/access/entity',{'user_id':'erpadmin','entity_id':eid}),
  ('/admin/access/location',{'user_id':'erpadmin','location_id':lid}),
  ('/admin/warehouses',{'warehouse_id':w1,'entity_id':eid,'location_id':lid,'warehouse_code':'W1'+w1[:5],'warehouse_name':'RM A'}),
  ('/admin/warehouses',{'warehouse_id':w2,'entity_id':eid,'location_id':lid,'warehouse_code':'W2'+w2[:5],'warehouse_name':'RM B'}),
 ]:
  r=c.post(path,json=payload,headers=h); assert r.status_code==200,r.text
 return eid,lid,w1,w2,m

def seed_lots(eid,lid,w,m):
 with engine.begin() as conn:
  for code,exp,qty in [('LOT-LATE','2027-02-01',30),('LOT-EARLY','2026-12-01',30)]:
   lid2=str(uuid4())
   conn.execute(text("INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,supplier_lot_no,lot_code,mfg_date,expiry_date,received_qty,accepted_qty,available_qty,rejected_qty,uom,qc_status,status) VALUES(:id,:o,:e,:l,:w,:m,:g,:gl,:s,:sl,:lc,NULL,:exp,:q,:q,:q,0,'kg','RELEASED','AVAILABLE')"), {'id':lid2,'o':str(uuid4()),'e':eid,'l':lid,'w':w,'m':m,'g':'g','gl':'gl','s':'s','sl':code,'lc':code,'exp':exp,'q':qty})
  conn.execute(text("""INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES((SELECT organization_id FROM inventory_lot LIMIT 1),:e,:l,:w,:m,'kg',60)"""), {'e':eid,'l':lid,'w':w,'m':m})

def test_fefo_preview_orders_earliest_expiry_first():
 c=TestClient(app); h=login(c); eid,lid,w1,w2,m=setup_scope(c,h); org=str(uuid4())
 # seed with matching organization for predictable query
 with engine.begin() as conn:
  for code,exp in [('LATE','2027-02-01'),('EARLY','2026-12-01')]:
   lid2=str(uuid4()); conn.execute(text("INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,lot_code,expiry_date,received_qty,accepted_qty,available_qty,rejected_qty,uom,qc_status,status) VALUES(:id,:o,:e,:l,:w,:m,'g','gl','s',:lc,:exp,30,30,30,0,'kg','RELEASED','AVAILABLE')"), {'id':lid2,'o':org,'e':eid,'l':lid,'w':w1,'m':m,'lc':code,'exp':exp})
 r=c.get('/v90n/inventory/fefo-preview',params={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':w1,'item_master_id':m,'quantity':40},headers=h); assert r.status_code==200,r.text
 a=r.json()['fefo']; assert a[0]['lot_code']=='EARLY' and a[0]['quantity']==30 and a[1]['lot_code']=='LATE' and a[1]['quantity']==10

def test_reservation_rejects_when_unreserved_stock_is_insufficient():
 c=TestClient(app); h=login(c); eid,lid,w1,w2,m=setup_scope(c,h); org=str(uuid4())
 with engine.begin() as conn:
  conn.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:m,'kg',10)"), {'o':org,'e':eid,'l':lid,'w':w1,'m':m})
 r=c.post('/v90n/inventory/reservations',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':w1,'item_master_id':m,'quantity':11},headers=h); assert r.status_code==409

def test_manifest_is_contiguous_and_build_is_v90n():
 ms=load_migrations(); assert ms[-1].version>=89; assert any(m.version==88 and m.filename=='088_v90o_production_planning.sql' for m in ms)
 c=TestClient(app); assert c.get('/build').json()['maintenance_stage'].startswith('v90.')


def test_reservation_create_and_release_cycle():
 c=TestClient(app); h=login(c); eid,lid,w1,w2,m=setup_scope(c,h); org=str(uuid4())
 with engine.begin() as conn:
  conn.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:m,'kg',50)"), {'o':org,'e':eid,'l':lid,'w':w1,'m':m})
 r=c.post('/v90n/inventory/reservations',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':w1,'item_master_id':m,'quantity':20,'reference_type':'TEST','reference_id':'T1'},headers=h); assert r.status_code==200,r.text
 rid=r.json()['reservation_id']; lr=c.get('/v90n/inventory/reservations',params={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':w1,'status':'OPEN'},headers=h); assert lr.status_code==200 and lr.json()['items'][0]['reservation_id']==rid
 rr=c.post(f'/v90n/inventory/reservations/{rid}/release',params={'reason':'test complete'},headers=h); assert rr.status_code==200,r.text


def test_reservation_accounts_for_existing_reserved_qty():
 c=TestClient(app); h=login(c); eid,lid,w1,w2,m=setup_scope(c,h); org=str(uuid4())
 with engine.begin() as conn:
  conn.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:m,'kg',30)"), {'o':org,'e':eid,'l':lid,'w':w1,'m':m})
  conn.execute(text("INSERT INTO inventory_reservation(reservation_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,quantity,reserved_qty,status,created_by) VALUES(:r,:o,:e,:l,:w,:m,20,20,'OPEN','erpadmin')"), {'r':str(uuid4()),'o':org,'e':eid,'l':lid,'w':w1,'m':m})
 r=c.post('/v90n/inventory/reservations',json={'organization_id':org,'entity_id':eid,'location_id':lid,'warehouse_id':w1,'item_master_id':m,'quantity':11},headers=h); assert r.status_code==409
