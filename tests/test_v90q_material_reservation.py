from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
 r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text; return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup(c,h):
 eid,lid,pid,mid=[str(uuid4()) for _ in range(4)]; oid=str(uuid4())
 assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'EQ'+eid[:6],'entity_name':'Entity Q'},headers=h).status_code==200
 assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'LQ'+lid[:6],'location_name':'Plant Q'},headers=h).status_code==200
 assert c.post('/admin/access/entity',json={'user_id':'erpadmin','entity_id':eid},headers=h).status_code==200
 assert c.post('/admin/access/location',json={'user_id':'erpadmin','location_id':lid},headers=h).status_code==200
 with engine.begin() as conn:
  conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:m,:o,:e,'PRODUCT',1,'{}')"),{'m':pid,'o':oid,'e':eid})
  conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:m,:o,:e,'RAW_MATERIAL',1,'{}')"),{'m':mid,'o':oid,'e':eid})
  conn.execute(text("INSERT INTO production_plan(plan_id,organization_id,entity_id,location_id,plan_no,period_start,period_end,status,created_by) VALUES(:p,:o,:e,:l,:n,'2026-09-10','2026-09-10','APPROVED','erpadmin')"),{'p':str(uuid4()),'o':oid,'e':eid,'l':lid,'n':'PQ'+eid[:6]})
  plan=conn.execute(text("SELECT plan_id FROM production_plan WHERE plan_no=:n"),{'n':'PQ'+eid[:6]}).scalar_one()
  pl=str(uuid4()); conn.execute(text("INSERT INTO production_plan_line(plan_line_id,plan_id,line_no,item_master_id,uom,planned_qty) VALUES(:pl,:p,1,:m,'kg',100)"),{'pl':pl,'p':plan,'m':pid})
  conn.execute(text("INSERT INTO material_requirement_calc(calc_id,plan_id,plan_line_id,recipe_id,material_master_id,requirement_type,gross_qty,scrap_qty,required_qty,uom) VALUES(:c,:p,:pl,:r,:m,'RAW_MATERIAL',40,0,40,'kg')"),{'c':str(uuid4()),'p':plan,'pl':pl,'r':str(uuid4()),'m':mid})
  conn.execute(text("INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,lot_code,received_qty,accepted_qty,available_qty,uom,qc_status,status) VALUES(:id,:o,:e,:l,:w,:m,:g,:gl,:s,:c,75,75,75,'kg','RELEASED','AVAILABLE')"),{'id':str(uuid4()),'o':oid,'e':eid,'l':lid,'w':str(uuid4()),'m':mid,'g':str(uuid4()),'gl':str(uuid4()),'s':str(uuid4()),'c':'LQ'+eid[:6]})
 return oid,eid,lid,pid,mid,plan,pl

def manager(c,h,eid,lid):
 uid=str(uuid4()); un='qmgr_'+uid[:8]
 assert c.post('/admin/users',json={'user_id':uid,'username':un,'password':'pw','display_name':'Mgr','role_id':'manager'},headers=h).status_code==200
 assert c.post('/admin/access/entity',json={'user_id':uid,'entity_id':eid},headers=h).status_code==200
 assert c.post('/admin/access/location',json={'user_id':uid,'location_id':lid},headers=h).status_code==200
 return login(c,un,'pw')

def test_reservation_checks_stock_and_approval():
 c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,plan,pl=setup(c,h)
 r=c.post('/v90q/reservations',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_id':plan,'plan_line_id':pl,'material_master_id':mid,'requested_qty':50},headers=h); assert r.status_code==200,r.text; rid=r.json()['reservation_id']
 mh=manager(c,h,eid,lid); a=c.post(f'/v90q/reservations/{rid}/approve',json={'reason':'ok'},headers=mh); assert a.status_code==200
 bad=c.post('/v90q/reservations',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_id':plan,'plan_line_id':pl,'material_master_id':mid,'requested_qty':26},headers=h); assert bad.status_code==409

def test_production_order_builds_from_requirements_and_approval():
 c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,plan,pl=setup(c,h)
 r=c.post('/v90q/production-orders',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_id':plan,'plan_line_id':pl,'order_no':'POQ-'+eid[:6],'product_master_id':pid,'planned_qty':50,'uom':'kg','scheduled_start':'2026-09-10T06:00:00Z','scheduled_end':'2026-09-10T07:00:00Z'},headers=h); assert r.status_code==200,r.text; oid2=r.json()['production_order_id']
 g=c.get(f'/v90q/production-orders/{oid2}',headers=h); assert g.status_code==200; assert abs(float(g.json()['materials'][0]['required_qty'])-20)<1e-9
 assert c.post(f'/v90q/production-orders/{oid2}/submit',json={},headers=h).status_code==200
 mh=manager(c,h,eid,lid); a=c.post(f'/v90q/production-orders/{oid2}/approve',json={'reason':'schedule approved'},headers=mh); assert a.status_code==200

def test_production_order_duplicate_and_bad_schedule():
 c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,plan,pl=setup(c,h)
 body={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_id':plan,'plan_line_id':pl,'order_no':'DUPQ-'+eid[:6],'product_master_id':pid,'planned_qty':10,'uom':'kg','scheduled_start':'2026-09-10T08:00:00Z','scheduled_end':'2026-09-10T07:00:00Z'}
 assert c.post('/v90q/production-orders',json=body,headers=h).status_code==422
 body['scheduled_end']='2026-09-10T09:00:00Z'; assert c.post('/v90q/production-orders',json=body,headers=h).status_code==200
 assert c.post('/v90q/production-orders',json=body,headers=h).status_code==409

def test_release_and_migration():
 c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,plan,pl=setup(c,h)
 r=c.post('/v90q/reservations',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_id':plan,'plan_line_id':pl,'material_master_id':mid,'requested_qty':10},headers=h); rid=r.json()['reservation_id']
 assert c.post(f'/v90q/reservations/{rid}/release',json={},headers=h).status_code==200
 ms=load_migrations(); assert any(m.version==90 and m.filename=='090_v90q_material_reservation_production_orders.sql' for m in ms) and ms[-1].version>=90
 assert c.get('/build').json()['maintenance_stage'].startswith('v90.')
