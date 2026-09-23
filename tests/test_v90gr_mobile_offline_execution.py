from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env():
 u=str(uuid4()); n='GR'+u[:8]; create_user(engine,u,n,'pw','GR Tester','manager'); c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(u,n,'manager'))}); o=str(uuid4()); e=str(uuid4()); l=str(uuid4()); d=str(uuid4())
 with engine.begin() as x:
  x.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GR','legal_entity',1)"),{'e':e,'c':'GR'+e[:8]})
  x.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GR','site',1)"),{'l':l,'e':e,'c':'GRL'+l[:6]})
  x.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':u,'e':e}); x.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':u,'l':l})
 return c,o,e,l,d

def test_mobile_event_idempotency_and_gap():
 c,o,e,l,d=env(); s=c.post('/v90gr/mobile/sessions',json={'organization_id':o,'entity_id':e,'location_id':l,'device_id':d}); assert s.status_code==200; sid=s.json()['session_id']
 b={'organization_id':o,'entity_id':e,'location_id':l,'device_id':d,'session_id':sid,'sequence_no':1,'event_type':'DELIVERY_CONFIRM','reference_type':'ORDER','reference_id':str(uuid4()),'payload':{'qty':10},'client_event_id':'evt-1'}
 assert c.post('/v90gr/mobile/events',json=b).json()['status']=='ACCEPTED'; assert c.post('/v90gr/mobile/events',json=b).json()['idempotent']
 g={**b,'sequence_no':3,'client_event_id':'evt-3'}; r=c.post('/v90gr/mobile/events',json=g); assert r.json()['status']=='EXCEPTION' and r.json()['exception_code']=='SEQUENCE_GAP'
 assert c.get('/v90gr/mobile/exceptions',params={'organization_id':o,'entity_id':e,'location_id':l}).json()['exceptions']
