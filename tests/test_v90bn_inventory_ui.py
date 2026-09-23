from fastapi.testclient import TestClient
from uuid import uuid4
from sqlalchemy import text

from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
from app.org_structure import create_entity
from app.access_scope import grant_entity_access, grant_location_access
from app.org_structure import create_location
from app.access_scope import create_warehouse


def admin_headers():
    return {"Authorization": f"Bearer {make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}"}


def scoped_user():
    uid=str(uuid4()); name='bn_'+uid[:8]
    create_user(engine, uid, name, 'pw', 'BN User', 'warehouse')
    h={"Authorization": f"Bearer {make_access_token(UserRecord(uid,name,'warehouse'))}"}
    org=uuid4(); ent=uuid4(); loc=uuid4(); wh=uuid4()
    create_entity(engine,str(ent),'BN'+str(ent)[:8],'BN Entity')
    create_location(engine,str(loc),str(ent),'BNL'+str(loc)[:8],'BN Location')
    create_warehouse(engine,str(wh),str(ent),str(loc),'BNW'+str(wh)[:8],'BN Warehouse')
    grant_entity_access(engine,uid,str(ent))
    grant_location_access(engine,uid,str(loc))
    return h,org,ent,loc,wh


def test_inventory_ui_summary_and_pages():
    h,org,ent,loc,wh=scoped_user(); c=TestClient(app)
    p={'organization_id':str(org),'entity_id':str(ent),'location_id':str(loc)}
    r=c.get('/v90bn/inventory/summary',params=p,headers=h); assert r.status_code==200 and 'counts' in r.json()
    assert c.get('/ui/grn').status_code==200
    assert c.get('/ui/qc').status_code==200
    assert c.get('/ui/inventory').status_code==200


def test_inventory_ui_reads_existing_operational_tables():
    h,org,ent,loc,wh=scoped_user(); c=TestClient(app)
    with engine.begin() as conn:
        # Minimal ledger row exercises the UI's scoped data access.
        item=str(uuid4()); lot=str(uuid4());
        conn.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:id,:o,:e,:l,:w,:m,:lot,'RECEIPT',5,'KG','TEST',:ref,'POSTED','erpadmin')"), {'id':str(uuid4()),'o':str(org),'e':str(ent),'l':str(loc),'w':str(wh),'m':item,'lot':lot,'ref':str(uuid4())})
    p={'organization_id':str(org),'entity_id':str(ent),'location_id':str(loc)}
    r=c.get('/v90bn/ledger',params=p,headers=h); assert r.status_code==200; assert r.json()['count']==1; assert r.json()['items'][0]['quantity'] == 5


def test_inventory_ui_preferences_round_trip():
    h,org,ent,loc,wh=scoped_user(); c=TestClient(app)
    r=c.put('/v90bn/preferences/inventory',json={'filters':{'qc_status':'RELEASED'},'columns':['lot_code','available_qty']},headers=h)
    assert r.status_code==200
    r=c.get('/v90bn/preferences/inventory',headers=h); assert r.status_code==200; assert r.json()['filters']['qc_status']=='RELEASED'


def test_inventory_ui_permission_enforced():
    uid=str(uuid4()); name='bnop_'+uid[:8]
    create_user(engine,uid,name,'pw','BN Operator','operator')
    c=TestClient(app,headers={"Authorization":f"Bearer {make_access_token(UserRecord(uid,name,'operator'))}"})
    r=c.get('/v90bn/inventory/summary',params={'organization_id':str(uuid4()),'entity_id':str(uuid4()),'location_id':str(uuid4())})
    assert r.status_code==403


def test_v90bn_migration_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==139 and m.filename=='139_v90bn_inventory_ui.sql' for m in ms); assert ms[-1].version>=139
