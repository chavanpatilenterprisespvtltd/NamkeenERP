from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.migrations import load_migrations

def login(c, username='erpadmin', password='change-me'):
 r=c.post('/auth/login',json={'username':username,'password':password}); assert r.status_code==200,r.text; return {'Authorization':f"Bearer {r.json()['access_token']}"}

def setup_scope(c,h):
 oid,eid,lid=[str(uuid4()) for _ in range(3)]
 assert c.post('/admin/entities',json={'entity_id':eid,'entity_code':'EP'+eid[:6],'entity_name':'Entity P'},headers=h).status_code==200
 assert c.post('/admin/locations',json={'location_id':lid,'entity_id':eid,'location_code':'LP'+lid[:6],'location_name':'Plant P'},headers=h).status_code==200
 assert c.post('/admin/access/entity',json={'user_id':'erpadmin','entity_id':eid},headers=h).status_code==200
 assert c.post('/admin/access/location',json={'user_id':'erpadmin','location_id':lid},headers=h).status_code==200
 pid,mid,pkid=[str(uuid4()) for _ in range(3)]
 with engine.begin() as conn:
  for midx,typ in [(pid,'PRODUCT'),(mid,'RAW_MATERIAL'),(pkid,'PACKAGING')]:
   conn.execute(text("INSERT INTO master_record(master_id,organization_id,entity_id,master_type,active,data) VALUES(:m,:o,:e,:t,1,'{}')"),{'m':midx,'o':oid,'e':eid,'t':typ})
 return oid,eid,lid,pid,mid,pkid

def manager(c,h,eid,lid):
 uid=str(uuid4()); un='mgrp_'+uid[:8]
 assert c.post('/admin/users',json={'user_id':uid,'username':un,'password':'pw','display_name':'Mgr','role_id':'manager'},headers=h).status_code==200
 assert c.post('/admin/access/entity',json={'user_id':uid,'entity_id':eid},headers=h).status_code==200
 assert c.post('/admin/access/location',json={'user_id':uid,'location_id':lid},headers=h).status_code==200
 return login(c,un,'pw')

def test_recipe_create_submit_approve_and_get():
 c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,pkid=setup_scope(c,h); mh=manager(c,h,eid,lid)
 body={'organization_id':oid,'entity_id':eid,'product_master_id':pid,'recipe_code':'RCP-'+eid[:6],'recipe_name':'Test Recipe','version_no':1,'yield_qty':100,'yield_uom':'kg','expected_loss_pct':1,'lines':[{'material_master_id':mid,'material_type':'RAW_MATERIAL','qty':90,'uom':'kg','scrap_pct':2}],'packaging':[{'packaging_master_id':pkid,'qty':200,'uom':'pack'}]}
 r=c.post('/v90p/recipes',json=body,headers=h); assert r.status_code==200,r.text; rid=r.json()['recipe_id']
 assert c.post(f'/v90p/recipes/{rid}/submit',json={},headers=h).json()['status']=='PENDING_APPROVAL'
 a=c.post(f'/v90p/recipes/{rid}/approve',json={'reason':'ok'},headers=mh); assert a.status_code==200,a.text
 g=c.get(f'/v90p/recipes/{rid}',headers=h); assert g.status_code==200 and g.json()['recipe']['status']=='APPROVED'

def test_requirement_calculation_uses_latest_approved_recipe():
 c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,pkid=setup_scope(c,h); mh=manager(c,h,eid,lid)
 r=c.post('/v90o/production-planning/plans',json={'organization_id':oid,'entity_id':eid,'location_id':lid,'plan_no':'PLP-'+eid[:6],'period_start':'2026-09-07','period_end':'2026-09-07','lines':[{'item_master_id':pid,'uom':'kg','planned_qty':200}]},headers=h); assert r.status_code==200,r.text
 pl=r.json()['plan_id']; line_id=c.get(f'/v90o/production-planning/plans/{pl}',headers=h).json()['lines'][0]['plan_line_id']
 body={'organization_id':oid,'entity_id':eid,'product_master_id':pid,'recipe_code':'RCP2-'+eid[:6],'recipe_name':'Calc Recipe','version_no':1,'yield_qty':100,'yield_uom':'kg','lines':[{'material_master_id':mid,'qty':50,'uom':'kg','scrap_pct':10}],'packaging':[{'packaging_master_id':pkid,'qty':100,'uom':'pack'}]}
 r=c.post('/v90p/recipes',json=body,headers=h); assert r.status_code==200; rid=r.json()['recipe_id']
 assert c.post(f'/v90p/recipes/{rid}/submit',json={},headers=h).status_code==200
 assert c.post(f'/v90p/recipes/{rid}/approve',json={},headers=mh).status_code==200
 cr=c.post('/v90p/material-requirements/calculate',json={'plan_id':pl,'plan_line_id':line_id,'planned_qty':200},headers=h); assert cr.status_code==200,cr.text
 data=cr.json(); assert data['recipe_version']==1
 reqs=data['requirements']; assert any(x['requirement_type']=='RAW_MATERIAL' and abs(x['required_qty']-110)<1e-6 for x in reqs)
 assert any(x['requirement_type']=='PACKAGING' and abs(x['required_qty']-200)<1e-6 for x in reqs)

def test_recipe_duplicate_version_block_and_migration():
 c=TestClient(app); h=login(c); oid,eid,lid,pid,mid,pkid=setup_scope(c,h)
 body={'organization_id':oid,'entity_id':eid,'product_master_id':pid,'recipe_code':'DUPP-'+eid[:6],'recipe_name':'Dup','version_no':1,'yield_qty':100,'lines':[{'material_master_id':mid,'qty':1,'uom':'kg'}]}
 assert c.post('/v90p/recipes',json=body,headers=h).status_code==200
 assert c.post('/v90p/recipes',json=body,headers=h).status_code==409
 ms=load_migrations(); assert ms[-1].version>=89 and any(m.version==89 and m.filename=='089_v90p_recipe_bom_material_requirements.sql' for m in ms)
 assert c.get('/build').json()['maintenance_stage'].startswith('v90.')
