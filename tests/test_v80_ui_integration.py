from uuid import uuid4
from fastapi.testclient import TestClient

from app.v80.app import app, SessionLocal
from app.v77.persistent_master import Base, MasterRecordORM
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_client(tmp_path, monkeypatch):
    engine=create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    service=__import__('app.v80.app', fromlist=['']).service
    # Patch module-global session factory used by the API.
    mod=__import__('app.v80.app', fromlist=[''])
    mod.SessionLocal=sessionmaker(bind=engine, expire_on_commit=False)
    mod.service=__import__('app.v77.persistent_master', fromlist=['']).PersistentMasterAdmin(mod.SessionLocal)
    return TestClient(app), mod.SessionLocal

def test_ui_and_types(tmp_path, monkeypatch):
    c,_=make_client(tmp_path, monkeypatch)
    assert c.get('/v80').status_code==200
    types=c.get('/v80/master-types').json()['items']
    assert 'SKU' in types and 'CUSTOMER' in types

def test_create_and_approve_with_history(tmp_path, monkeypatch):
    c, _=make_client(tmp_path, monkeypatch)
    org=uuid4(); requester=uuid4(); approver=uuid4()
    body={'organization_id':str(org),'master_type':'CUSTOMER','action':'CREATE','requested_by':str(requester),'payload':{'code':'C001','name':'Demo'},'master_id':None,'entity_id':None,'effective_from':None,'effective_to':None,'base_version_no':None,'client_event_id':'evt-1'}
    r=c.post('/v80/master-data/changes',json=body); assert r.status_code==200
    rid=r.json()['request_id']
    q=c.get('/v80/approval-queue',params={'organization_id':str(org)}).json()['items']; assert len(q)==1
    a=c.post(f'/v80/approval-queue/{rid}/approve',json={'organization_id':str(org),'approver_id':str(approver),'reason':''}); assert a.status_code==200
    mid=a.json()['master_id']
    rows=c.get('/v80/master-data/CUSTOMER',params={'organization_id':str(org)}).json()['items']
    assert any(x['master_id']==mid for x in rows)

def test_self_approval_block(tmp_path, monkeypatch):
    c,_=make_client(tmp_path, monkeypatch)
    org=uuid4(); u=uuid4()
    body={'organization_id':str(org),'master_type':'CUSTOMER','action':'CREATE','requested_by':str(u),'payload':{'code':'C002','name':'Self'},'client_event_id':'evt-2'}
    rid=c.post('/v80/master-data/changes',json=body).json()['request_id']
    r=c.post(f'/v80/approval-queue/{rid}/approve',json={'organization_id':str(org),'approver_id':str(u),'reason':''})
    assert r.status_code==400 and 'Self-approval' in r.text

def test_history_empty_for_new_master(tmp_path, monkeypatch):
    c,_=make_client(tmp_path, monkeypatch)
    org=uuid4(); mid=uuid4()
    r=c.get(f'/v80/master-data/CUSTOMER/{mid}/history',params={'organization_id':str(org)})
    assert r.status_code==200 and r.json()['items']==[]
