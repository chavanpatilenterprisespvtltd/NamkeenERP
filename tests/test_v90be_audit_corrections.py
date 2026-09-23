from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user


def setup_env():
    uid=str(uuid4()); uname='be_'+uid[:8]
    approver=str(uuid4()); aname='bea_'+approver[:8]
    create_user(engine,uid,uname,'pw','BE Tester','manager')
    create_user(engine,approver,aname,'pw','BE Approver','manager')
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'operator'))})
    a=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(approver,aname,'manager'))})
    org=str(uuid4()); e=str(uuid4()); l=str(uuid4())
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'BE','legal_entity',1)"),{'e':e,'c':'BE'+e[:8]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'BE','site',1)"),{'l':l,'e':e,'c':'BEL'+l[:6]})
        for u in (uid,approver):
            db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':u,'e':e})
            db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':u,'l':l})
    return c,a,org,e,l,uid,approver


def test_audit_record_and_filter():
    c,a,org,e,l,_,_=setup_env()
    r=c.post('/v90be/audit',json={'organization_id':org,'entity_id':e,'location_id':l,'action':'UPDATE','object_type':'SKU','object_id':str(uuid4()),'before':{'price':10},'after':{'price':12},'reason':'price correction'})
    assert r.status_code==200, r.text
    q=a.get('/v90be/audit',params={'organization_id':org,'entity_id':e,'location_id':l,'object_type':'SKU'})
    assert q.status_code==200 and q.json()['count']==1
    assert q.json()['items'][0]['action']=='UPDATE'


def test_correction_self_approval_and_approval_audit():
    c,a,org,e,l,uid,approver=setup_env()
    source=str(uuid4())
    r=c.post('/v90be/corrections',json={'organization_id':org,'entity_id':e,'location_id':l,'source_type':'SALES_ORDER','source_id':source,'correction_type':'QTY_ADJUSTMENT','reason':'Wrong order quantity entered','proposed':{'line_id':'1','qty':20,'_before':{'qty':18}}})
    assert r.status_code==200, r.text
    cid=r.json()['correction_id']
    assert c.post(f'/v90be/corrections/{cid}/approve',json={}).status_code==409
    assert a.post(f'/v90be/corrections/{cid}/approve',json={'reason':'Reviewed supporting evidence'}).json()['status']=='APPROVED'
    rows=a.get('/v90be/corrections',params={'organization_id':org,'status':'APPROVED'}).json()['corrections']
    assert any(x['correction_id']==cid and x['applied_by']==approver for x in rows)
    aud=a.get('/v90be/audit',params={'organization_id':org,'entity_id':e,'object_type':'CORRECTIVE_TRANSACTION','object_id':cid}).json()['items']
    assert aud[0]['action']=='APPROVED'


def test_correction_duplicate_and_rejection_reason():
    c,a,org,e,l,_,_=setup_env(); source=str(uuid4())
    body={'organization_id':org,'entity_id':e,'location_id':l,'source_type':'PAYMENT','source_id':source,'correction_type':'ALLOCATE','reason':'Fix incorrect allocation','proposed':{'amount':100}}
    r1=c.post('/v90be/corrections',json=body); assert r1.status_code==200
    assert c.post('/v90be/corrections',json=body).status_code==409
    cid=r1.json()['correction_id']
    assert a.post(f'/v90be/corrections/{cid}/reject',json={}).status_code==422
    assert a.post(f'/v90be/corrections/{cid}/reject',json={'reason':'Not authorized'}).json()['status']=='REJECTED'


def test_migration_130():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==130 and m.filename=='130_v90be_audit_corrective_workflow.sql' for m in ms)
