from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def setup_env():
    uid=str(uuid4()); uname='bb_'+uid[:8]
    create_user(engine,uid,uname,'pw','BB Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4())
    with engine.begin() as db:
      db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'BB','legal_entity',1)"),{'e':e,'c':'BB'+e[:8]})
      db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'BB','site',1)"),{'l':l,'e':e,'c':'BBL'+l[:6]})
      db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
      db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
    return c,org,e,l

def test_offline_push_idempotency_and_conflict_resolution():
    c,org,e,l=setup_env(); dev=c.post('/v90bb/devices/register',json={'organization_id':org,'entity_id':e,'location_id':l,'device_code':'DEV-'+e[:8],'device_name':'Factory Android'}); assert dev.status_code==200,dev.text; did=dev.json()['device_id']; aid=str(uuid4())
    base={'organization_id':org,'entity_id':e,'location_id':l,'device_id':did,'client_operation_id':'op-1','aggregate_type':'VISIT','aggregate_id':aid,'operation_type':'UPSERT','base_version':0,'payload':{'status':'DONE'}}
    x=c.post('/v90bb/sync/push',json=base); assert x.status_code==200 and x.json()['status']=='APPLIED'; assert c.post('/v90bb/sync/push',json=base).json()['idempotent']
    stale={**base,'client_operation_id':'op-2','base_version':0,'payload':{'status':'UPDATED'}}; y=c.post('/v90bb/sync/push',json=stale); assert y.status_code==200 and y.json()['status']=='CONFLICT'
    conflicts=c.get('/v90bb/sync/conflicts',params={'organization_id':org,'entity_id':e,'location_id':l}); assert conflicts.status_code==200 and len(conflicts.json()['conflicts'])==1; cid=conflicts.json()['conflicts'][0]['conflict_id']
    z=c.post(f'/v90bb/sync/conflicts/{cid}/resolve',json={'resolution':'APPLIED','merged_payload':{'status':'MERGED'}}); assert z.status_code==200
    pull=c.get('/v90bb/sync/pull',params={'device_id':did,'after_version':0}); assert pull.status_code==200; assert pull.json()['items']

def test_migration():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==128 and m.filename=='128_v90bc_evidence_attachment_gps.sql' for m in ms)
