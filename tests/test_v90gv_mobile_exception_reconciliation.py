from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env():
    u=str(uuid4()); n='GV'+u[:8]; create_user(engine,u,n,'pw','GV Tester','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(u,n,'manager'))})
    o=str(uuid4()); e=str(uuid4()); l=str(uuid4()); iid=str(uuid4())
    with engine.begin() as x:
        x.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GV','legal_entity',1)"),{'e':e,'c':'GV'+e[:8]})
        x.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GV','site',1)"),{'l':l,'e':e,'c':'GVL'+l[:6]})
        x.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':u,'e':e})
        x.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':u,'l':l})
        x.execute(text("INSERT INTO mobile_transaction_integrations(integration_id,event_id,organization_id,entity_id,location_id,transaction_type,reference_type,reference_id,status,validation_code,validation_message,created_by,created_at) VALUES(:i,:ev,:o,:e,:l,'RECEIPT_CONFIRM','GRN',:r,'REJECTED','BAD','bad mobile event',:u,'2026-09-13T00:00:00+00:00')"),{'i':iid,'ev':str(uuid4()),'o':o,'e':e,'l':l,'r':str(uuid4()),'u':u})
    return c,o,e,l,iid

def test_reconcile_rejected_creates_open_exception_and_lists_it():
    c,o,e,l,iid=env(); r=c.post(f'/v90gv/mobile/reconcile/{iid}'); assert r.status_code==200; assert r.json()['exception']['exception_code']=='INTEGRATION_REJECTED'
    r=c.get('/v90gv/mobile/exceptions',params={'organization_id':o,'entity_id':e,'location_id':l,'status':'OPEN'}); assert r.status_code==200; assert len(r.json()['exceptions'])==1

def test_resolve_is_idempotent():
    c,o,e,l,iid=env(); ex=c.post(f'/v90gv/mobile/reconcile/{iid}').json()['exception']; eid=ex['exception_id']
    r=c.post(f'/v90gv/mobile/exceptions/{eid}/resolve',json={'resolution_note':'Reviewed and routed to source workflow'}); assert r.status_code==200 and r.json()['status']=='RESOLVED'
    r2=c.post(f'/v90gv/mobile/exceptions/{eid}/resolve',json={'resolution_note':'same'}); assert r2.status_code==200 and r2.json()['idempotent']

def test_ready_with_execution_record_is_state_mismatch():
    c,o,e,l,iid=env()
    with engine.begin() as x:
        x.execute(text("UPDATE mobile_transaction_integrations SET status='READY' WHERE integration_id=:i"),{'i':iid})
        x.execute(text("INSERT INTO mobile_execution_records(execution_id,integration_id,organization_id,entity_id,location_id,transaction_type,reference_type,reference_id,status,result_json,executed_by,executed_at) VALUES(:id,:i,:o,:e,:l,'RECEIPT_CONFIRM','GRN',:r,'EXECUTED','{}','u','2026-09-13T00:00:00+00:00')"),{'id':str(uuid4()),'i':iid,'o':o,'e':e,'l':l,'r':str(uuid4())})
    r=c.post(f'/v90gv/mobile/reconcile/{iid}'); assert r.status_code==200 and r.json()['exception']['exception_code']=='EXECUTION_STATE_MISMATCH'
