from fastapi.testclient import TestClient
from uuid import uuid4
from app.__main__ import app, engine
from app.org_structure import create_entity
from app.access_scope import grant_entity_access
from app.identity import create_user


def login(client):
    r=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_master_api_create_list_and_scope():
    client=TestClient(app)
    h=login(client)
    org=str(uuid4())
    eid=str(uuid4())
    create_entity(engine,eid,'I-ENT','V90I Entity')
    grant_entity_access(engine,'erpadmin',eid)
    payload={
        'organization_id':org,
        'master_type':'PRODUCT',
        'action':'CREATE',
        'entity_id':eid,
        'payload':{'code':'I-P001','name':'V90i Product'}
    }
    r=client.post('/v90i/master-data/changes',json=payload,headers=h)
    assert r.status_code==200, r.text
    rid=r.json()['request_id']
    q=client.get('/v90i/approval-queue',params={'organization_id':org},headers=h)
    assert q.status_code==200 and len(q.json()['items'])==1
    # Super-admin UUID is non-UUID in legacy seed; approval endpoint uses compatibility fallback.
    manager_id = str(uuid4())
    create_user(engine, manager_id, 'v90i_manager_'+org[:8], 'manager-pass', 'V90i Manager', 'manager')
    grant_entity_access(engine, manager_id, eid)
    rm=client.post('/auth/login',json={'username':'v90i_manager_'+org[:8],'password':'manager-pass'})
    assert rm.status_code==200, rm.text
    hm={'Authorization':f"Bearer {rm.json()['access_token']}"}
    r=client.post(f'/v90i/approval-queue/{rid}/approve',json={'organization_id':org,'reason':'seed test'},headers=hm)
    assert r.status_code==200, r.text
    mid=r.json()['master_id']
    r=client.get('/v90i/master-data/PRODUCT',params={'organization_id':org,'entity_id':eid},headers=h)
    assert r.status_code==200, r.text
    items=r.json()['items']
    assert any(x['master_id']==mid and x['name']=='V90i Product' for x in items)


def test_master_api_denies_unscoped_entity():
    client=TestClient(app)
    h=login(client)
    org=str(uuid4()); eid=str(uuid4())
    create_entity(engine,eid,'I-ENT2','Unscoped')
    payload={'organization_id':org,'master_type':'PRODUCT','action':'CREATE','entity_id':eid,'payload':{'code':'I-P002','name':'Blocked'}}
    r=client.post('/v90i/master-data/changes',json=payload,headers=h)
    assert r.status_code==403
