from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
 r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text; return {'Authorization':f"Bearer {r.json()['access_token']}"}

def scope_and_product(c,h):
 eid,lid=[str(uuid4()) for _ in range(2)]
 assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'EO'+eid[:6],'entity_name':'Entity O'},headers=h).status_code==200
 assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'LO'+lid[:6],'location_name':'Plant O'},headers=h).status_code==200
 assert c.post('/admin/access/entity',json={'user_id':'erpadmin','entity_id':eid},headers=h).status_code==200
 assert c.post('/admin/access/location',json={'user_id':'erpadmin','location_id':lid},headers=h).status_code==200
 oid=str(uuid4()); pid=str(uuid4())
 with engine.begin() as conn:
  conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:m,:o,:e,'PRODUCT',1,'{}')"),{'m':pid,'o':oid,'e':eid})
 return oid,eid,lid,pid

def manager(c,h,eid,lid):
 uid=str(uuid4()); un='mgr_'+uid[:8]
 assert c.post('/admin/users',json={'user_id':uid,'username':un,'password':'pw','display_name':'Mgr','role_id':'manager'},headers=h).status_code==200
 assert c.post('/admin/access/entity',json={'user_id':uid,'entity_id':eid},headers=h).status_code==200
 assert c.post('/admin/access/location',json={'user_id':uid,'location_id':lid},headers=h).status_code==200
 return login(c,un,'pw')

def test_create_submit_approve_plan():
 c=TestClient(app); h=login(c); oid,eid,lid,pid=scope_and_product(c,h); mh=manager(c,h,eid,lid)
 r=c.post('/v90o/production-planning/plans',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_no':'PLAN-'+eid[:6],'period_start':'2026-09-07','period_end':'2026-09-13','source':'SALES','lines':[{'item_master_id':pid,'uom':'kg','planned_qty':500,'priority':1}]},headers=h); assert r.status_code==200,r.text
 plan=r.json()['plan_id']
 assert c.post(f'/v90o/production-planning/plans/{plan}/submit',json={},headers=h).json()['status']=='PENDING_APPROVAL'
 a=c.post(f'/v90o/production-planning/plans/{plan}/approve',json={'reason':'scheduled'},headers=mh); assert a.status_code==200 and a.json()['status']=='APPROVED',a.text
 d=c.get(f'/v90o/production-planning/plans/{plan}',headers=h); assert d.status_code==200 and d.json()['plan']['status']=='APPROVED'

def test_self_approval_and_duplicate_plan_block():
 c=TestClient(app); h=login(c); oid,eid,lid,pid=scope_and_product(c,h); body={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_no':'DUP-'+eid[:6],'period_start':'2026-09-07','period_end':'2026-09-07','lines':[{'item_master_id':pid,'uom':'kg','planned_qty':10}]}
 r=c.post('/v90o/production-planning/plans',json=body,headers=h); assert r.status_code==200
 r2=c.post('/v90o/production-planning/plans',json=body,headers=h); assert r2.status_code==409
 plan=r.json()['plan_id']; assert c.post(f'/v90o/production-planning/plans/{plan}/submit',json={},headers=h).status_code==200
 assert c.post(f'/v90o/production-planning/plans/{plan}/approve',json={},headers=h).status_code==409

def test_requirement_and_manifest():
 c=TestClient(app); h=login(c); oid,eid,lid,pid=scope_and_product(c,h)
 r=c.post('/v90o/production-planning/plans',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_no':'REQ-'+eid[:6],'period_start':'2026-09-07','period_end':'2026-09-08','lines':[{'item_master_id':pid,'uom':'kg','planned_qty':100}]},headers=h); assert r.status_code==200
 plan=r.json()['plan_id']; req=c.post(f'/v90o/production-planning/plans/{plan}/requirements',json={'item_master_id':pid,'required_qty':25,'uom':'kg','requirement_type':'RAW_MATERIAL'},headers=h); assert req.status_code==200,r.text
 ms=load_migrations(); assert ms[-1].version>=89 and any(m.version==88 and m.filename=='088_v90o_production_planning.sql' for m in ms)
 assert c.get('/build').json()['maintenance_stage'].startswith('v90.')
