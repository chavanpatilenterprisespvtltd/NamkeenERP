from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def setup_env():
    uid=str(uuid4()); uname='bd_'+uid[:8]
    approver=str(uuid4()); aname='bdm_'+approver[:8]
    create_user(engine,uid,uname,'pw','BD Tester','manager')
    create_user(engine,approver,aname,'pw','BD Approver','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'manager'))})
    a=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(approver,aname,'manager'))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4())
    with engine.begin() as db:
      db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'BD','legal_entity',1)"),{'e':e,'c':'BD'+e[:8]})
      db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'BD','site',1)"),{'l':l,'e':e,'c':'BDL'+l[:6]})
      for u in (uid,approver):
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':u,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':u,'l':l})
    return c,a,org,e,l,uid,approver

def test_notifications_template_queue_and_scope():
    c,a,org,e,l,_,_=setup_env()
    t=c.post('/v90bd/notification-templates',json={'organization_id':org,'entity_id':e,'template_code':'POD_READY','channel':'IN_APP','body_template':'POD ready'})
    assert t.status_code==200,t.text
    n=c.post('/v90bd/notifications',json={'organization_id':org,'entity_id':e,'location_id':l,'recipient_address':'ops','channel':'IN_APP','subject':'Ready','body':'POD ready','related_type':'DISPATCH','related_id':str(uuid4())})
    assert n.status_code==200 and n.json()['status']=='PENDING'
    assert c.get('/v90bd/notifications',params={'organization_id':org}).json()['notifications']

def test_approval_submit_self_approval_and_approve():
    c,a,org,e,l,uid,approver=setup_env()
    w=c.post('/v90bd/workflows',json={'organization_id':org,'entity_id':e,'workflow_code':'DISPATCH_HIGH_VALUE','workflow_name':'Dispatch High Value','module_name':'DISPATCH','min_amount':10000})
    assert w.status_code==200,w.text; wid=w.json()['workflow_id']
    sub=c.post('/v90bd/approvals',json={'organization_id':org,'entity_id':e,'location_id':l,'workflow_id':wid,'subject_type':'DISPATCH','subject_id':str(uuid4()),'payload':{'amount':12000}})
    assert sub.status_code==200,sub.text; aid=sub.json()['approval_request_id']
    assert c.post(f'/v90bd/approvals/{aid}/approve',json={'reason':'self'}).status_code==409
    assert a.get('/v90bd/approvals',params={'organization_id':org}).json()['approvals']
    dec=a.post(f'/v90bd/approvals/{aid}/approve',json={'reason':'Reviewed'})
    assert dec.status_code==200 and dec.json()['status']=='APPROVED'

def test_reject_requires_reason():
    c,a,org,e,l,_,_=setup_env()
    w=c.post('/v90bd/workflows',json={'organization_id':org,'entity_id':e,'workflow_code':'QC_HOLD','workflow_name':'QC Hold','module_name':'QC'})
    wid=w.json()['workflow_id']
    sub=c.post('/v90bd/approvals',json={'organization_id':org,'entity_id':e,'location_id':l,'workflow_id':wid,'subject_type':'QC','subject_id':str(uuid4())})
    aid=sub.json()['approval_request_id']
    assert a.post(f'/v90bd/approvals/{aid}/reject',json={}).status_code==422
    assert a.post(f'/v90bd/approvals/{aid}/reject',json={'reason':'Insufficient evidence'}).json()['status']=='REJECTED'

def test_migration_129():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==129 and m.filename=='129_v90bd_notifications_approval_workflow.sql' for m in ms)
