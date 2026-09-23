from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env():
 u=str(uuid4()); n='GS'+u[:8]; create_user(engine,u,n,'pw','GS Tester','manager'); c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(u,n,'manager'))}); o=str(uuid4()); e=str(uuid4()); l=str(uuid4())
 with engine.begin() as x:
  x.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GS','legal_entity',1)"),{'e':e,'c':'GS'+e[:8]})
  x.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GS','site',1)"),{'l':l,'e':e,'c':'GSL'+l[:6]})
  x.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':u,'e':e}); x.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':u,'l':l})
 return c,o,e,l

def test_transaction_validation_posting_and_idempotency():
 c,o,e,l=env(); ev=str(uuid4()); ref=str(uuid4()); b={'organization_id':o,'entity_id':e,'location_id':l,'event_id':ev,'transaction_type':'DELIVERY_CONFIRM','reference_type':'ORDER','reference_id':ref,'payload':{'qty':10}}
 r=c.post('/v90gs/mobile/transactions/integrate',json=b); assert r.status_code==200 and r.json()['status']=='READY'; iid=r.json()['integration_id']
 r2=c.post('/v90gs/mobile/transactions/integrate',json=b); assert r2.json()['idempotent']
 r3=c.post(f'/v90gs/mobile/transactions/{iid}/post'); assert r3.json()['status']=='POSTED'
 r4=c.post(f'/v90gs/mobile/transactions/{iid}/post'); assert r4.json()['idempotent']
 assert c.get('/v90gs/mobile/transactions',params={'organization_id':o,'entity_id':e,'location_id':l,'status':'POSTED'}).json()['transactions']
