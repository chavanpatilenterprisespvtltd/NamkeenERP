from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def setup_env():
    uid=str(uuid4()); uname='bc_'+uid[:8]
    create_user(engine,uid,uname,'pw','BC Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4())
    with engine.begin() as db:
      db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'BC','legal_entity',1)"),{'e':e,'c':'BC'+e[:8]})
      db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'BC','site',1)"),{'l':l,'e':e,'c':'BCL'+l[:6]})
      db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
      db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
    return c,org,e,l

def test_attachment_gps_and_listing():
    c,org,e,l=setup_env()
    x=c.post('/v90bc/attachments',json={'organization_id':org,'entity_id':e,'location_id':l,'subject_type':'DELIVERY','subject_id':str(uuid4()),'document_type':'POD_PHOTO','filename':'pod.jpg','mime_type':'image/jpeg','storage_ref':'obj://pod/1','sha256':'a'*64,'size_bytes':123,'metadata':{'source':'android'}})
    assert x.status_code==200,x.text; aid=x.json()['attachment_id']
    g=c.post(f'/v90bc/attachments/{aid}/gps',json={'latitude':18.52,'longitude':73.85,'accuracy_m':4.2,'provider':'GNSS'})
    assert g.status_code==200,g.text
    lst=c.get('/v90bc/attachments',params={'organization_id':org,'entity_id':e,'location_id':l,'subject_type':'DELIVERY'})
    assert lst.status_code==200 and len(lst.json()['attachments'])==1
    a=lst.json()['attachments'][0]; assert a['latitude']==18.52 and a['metadata']['source']=='android'
    assert c.post(f'/v90bc/attachments/{aid}/gps',json={'latitude':1,'longitude':2}).status_code==409
    assert c.post(f'/v90bc/attachments/{aid}/deactivate').status_code==200

def test_migration():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==128 and m.filename=='128_v90bc_evidence_attachment_gps.sql' for m in ms)
