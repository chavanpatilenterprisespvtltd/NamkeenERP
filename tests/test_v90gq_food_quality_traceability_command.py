from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env(role='manager'):
    uid=str(uuid4()); uname='gq_'+uid[:8]; create_user(engine,uid,uname,'pw','GQ Tester',role)
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'GQ Tester',role))})
    org,e,l,b=map(str,[uuid4(),uuid4(),uuid4(),uuid4()])
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GQ','legal_entity',1)"),{'e':e,'c':'GQ'+e[:5]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GQ','site',1)"),{'l':l,'e':e,'c':'GQL'+l[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:o,:org,:e,:l,'GQ-B1',:p,100,'KG','COMPLETED',:u)"),{'b':b,'o':str(uuid4()),'org':org,'e':e,'l':l,'p':str(uuid4()),'u':uid})
        ins=str(uuid4()); db.execute(text("INSERT INTO quality_inspection(inspection_id,organization_id,entity_id,batch_id,stage,status,sample_qty,created_by) VALUES(:i,:o,:e,:b,'FG','RELEASED',1,:u)"),{'i':ins,'o':org,'e':e,'b':b,'u':uid})
        fg=str(uuid4()); db.execute(text("INSERT INTO finished_goods_lot(fg_lot_id,organization_id,entity_id,location_id,warehouse_id,batch_id,product_master_id,fg_lot_code,mfg_date,quantity,available_qty,uom,created_by) VALUES(:f,:o,:e,:l,:w,:b,:p,'GQ-FG','2026-09-12',100,100,'KG',:u)"),{'f':fg,'o':org,'e':e,'l':l,'w':str(uuid4()),'b':b,'p':str(uuid4()),'u':uid}); db.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,created_by) VALUES(:p,:o,:e,:l,:w,:r,:f,:s,'GQ-L1',10,100,100,'KG','2026-09-12',:u)"),{'p':str(uuid4()),'o':org,'e':e,'l':l,'w':str(uuid4()),'r':str(uuid4()),'f':fg,'s':str(uuid4()),'u':uid})
    return c,org,e,l,b

def test_dashboard_snapshot_action():
    c,o,e,l,b=env(); q={'organization_id':o,'entity_id':e,'location_id':l,'from_date':'2020-01-01','to_date':'2999-12-31'}
    r=c.get('/v90gq/food-quality-traceability',params=q); assert r.status_code==200,r.text; d=r.json(); assert d['batches_reviewed']==1 and d['released_batches']==1 and d['traceable_batches']==1 and d['traceability_pct']==100.0
    r=c.post('/v90gq/food-quality-traceability/snapshots',json=q); assert r.status_code==200 and r.json()['snapshot_id']
    r=c.post('/v90gq/food-quality-traceability/actions',json={**q,'batch_id':b,'action_type':'RELEASE_REVIEW','priority':'HIGH','reason':'Review release evidence'}); assert r.status_code==200
    assert c.get('/v90gq/food-quality-traceability/actions',params={'organization_id':o,'entity_id':e,'location_id':l}).json()['actions']

def test_rbac():
    c,o,e,l,b=env('salesperson'); r=c.get('/v90gq/food-quality-traceability',params={'organization_id':o,'entity_id':e,'location_id':l}); assert r.status_code==403
