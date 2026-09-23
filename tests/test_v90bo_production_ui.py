from fastapi.testclient import TestClient
from uuid import uuid4
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
from app.org_structure import create_entity, create_location
from app.access_scope import grant_entity_access, grant_location_access
from sqlalchemy import text

def scoped_user():
    uid=str(uuid4()); name='bo_'+uid[:8]
    create_user(engine,uid,name,'pw','BO User','production')
    h={'Authorization':f'Bearer {make_access_token(UserRecord(uid,name,'production'))}'}
    org=uuid4(); ent=uuid4(); loc=uuid4()
    create_entity(engine,str(ent),'BO'+str(ent)[:8],'BO Entity'); create_location(engine,str(loc),str(ent),'BOL'+str(loc)[:8],'BO Location')
    grant_entity_access(engine,uid,str(ent)); grant_location_access(engine,uid,str(loc))
    # production.view is already granted to the production role in the module bootstrap
    return h,org,ent,loc

def test_production_pages_and_summary():
    h,org,ent,loc=scoped_user(); c=TestClient(app); p={'organization_id':str(org),'entity_id':str(ent),'location_id':str(loc)}
    r=c.get('/v90bo/production/summary',params=p,headers=h); assert r.status_code==200
    assert set(['plans','orders','batches','material_issues']).issubset(r.json()['counts'])
    assert c.get('/ui/production').status_code==200

def test_production_lists_read_existing_rows():
    h,org,ent,loc=scoped_user(); c=TestClient(app)
    with engine.begin() as conn:
        plan=str(uuid4()); order=str(uuid4()); batch=str(uuid4())
        conn.execute(text("INSERT INTO production_plan(plan_id,organization_id,entity_id,location_id,plan_no,period_start,period_end,status,created_by) VALUES(:p,:o,:e,:l,'BO-PLAN','2026-09-01','2026-09-30','APPROVED','erpadmin')"),{'p':plan,'o':str(org),'e':str(ent),'l':str(loc)})
        pline=str(uuid4()); conn.execute(text("INSERT INTO production_plan_line(plan_line_id,plan_id,line_no,item_master_id,uom,planned_qty) VALUES(:id,:p,1,:m,'KG',100)"),{'id':pline,'p':plan,'m':str(uuid4())})
        conn.execute(text("INSERT INTO production_order(production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:id,:o,:e,:l,:p,:pl,'BO-ORD',:m,100,'KG','APPROVED','erpadmin')"),{'id':order,'o':str(org),'e':str(ent),'l':str(loc),'p':plan,'pl':pline,'m':str(uuid4())})
        conn.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:id,:o,:org,:e,:l,'BO-BATCH',:m,100,'KG','RUNNING','erpadmin')"),{'id':batch,'o':order,'org':str(org),'e':str(ent),'l':str(loc),'m':str(uuid4())})
    p={'organization_id':str(org),'entity_id':str(ent),'location_id':str(loc)}
    assert c.get('/v90bo/plans',params=p,headers=h).json()['count'] == 1
    assert c.get('/v90bo/orders',params=p,headers=h).json()['count'] == 1
    assert c.get('/v90bo/batches',params=p,headers=h).json()['count'] == 1

def test_production_ui_preferences_round_trip():
    h,org,ent,loc=scoped_user(); c=TestClient(app)
    payload={'entity_id':str(ent),'location_id':str(loc),'filters':{'status':'RUNNING'},'columns':['batch_no','planned_qty']}
    assert c.put('/v90bo/preferences/production',json=payload,headers=h).status_code==200
    r=c.get('/v90bo/preferences/production',headers=h); assert r.status_code==200 and r.json()['filters']['status']=='RUNNING'

def test_v90bo_migration_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==140 and m.filename=='140_v90bo_production_ui.sql' for m in ms); assert ms[-1].version>=140
