from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env():
    uid=str(uuid4()); uname='as_'+uid[:8]
    create_user(engine,uid,uname,'pw','AS Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'AS','legal_entity',1)"),{'e':e,'c':'AS'+e[:5]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'AS','site',1)"),{'l':l,'e':e,'c':'ASL'+l[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
    return c,org,e,l

def test_factory_kpi_and_snapshot():
    c,org,e,l=env()
    q={'organization_id':org,'entity_id':e,'location_id':l,'from_date':'2026-09-07','to_date':'2026-09-07'}
    with engine.begin() as db:
        db.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by,created_at) VALUES(:b,:o,:org,:e,:l,'ASB',:p,100,'kg','COMPLETED',:u,'2026-09-07T10:00:00')"),{'b':str(uuid4()),'o':str(uuid4()),'org':org,'e':e,'l':l,'p':str(uuid4()),'u':str(uuid4())})
    # Replace with a direct count-only scenario if production row constraints differ; KPI must still be well-formed.
    r=c.get('/v90as/factory-kpi',params=q); assert r.status_code==200,r.text
    j=r.json(); assert j['planned_qty']==100 and j['batch_count']==1
    s=c.post('/v90as/factory-kpi/snapshots',json=q); assert s.status_code==200,s.text
    sid=s.json()['snapshot_id']
    r=c.get('/v90as/factory-kpi/snapshots',params={'organization_id':org,'entity_id':e,'location_id':l})
    assert r.status_code==200 and any(x['snapshot_id']==sid for x in r.json()['snapshots'])
