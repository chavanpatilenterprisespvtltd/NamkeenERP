from fastapi.testclient import TestClient
from uuid import uuid4
from app.__main__ import app, engine
from app.org_structure import create_entity
from app.access_scope import grant_entity_access


def login(client):
    r=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def scope():
    org=uuid4(); eid=uuid4(); loc=uuid4()
    create_entity(engine,str(eid),'BM'+str(eid)[:8],'BM Entity')
    grant_entity_access(engine,'erpadmin',str(eid))
    return org,eid,loc


def test_transaction_ui_routes_and_preferences():
    c=TestClient(app); h=login(c); org,eid,loc=scope()
    r=c.get('/v90bm/products',params={'organization_id':str(org),'entity_id':str(eid)},headers=h)
    assert r.status_code==200 and 'items' in r.json()
    r=c.get('/v90bm/recipes',params={'organization_id':str(org),'entity_id':str(eid)},headers=h)
    assert r.status_code==200 and 'recipes' in r.json()
    r=c.get('/v90bm/procurement',params={'organization_id':str(org),'entity_id':str(eid),'location_id':str(loc)},headers=h)
    assert r.status_code==200 and 'counts' in r.json()
    key='products'
    r=c.put(f'/v90bm/preferences/{key}',json={'filters':{'active':True},'columns':['code','name']},headers=h)
    assert r.status_code==200
    r=c.get(f'/v90bm/preferences/{key}',headers=h)
    assert r.status_code==200 and r.json()['filters']['active'] is True
    assert c.get('/ui/products').status_code==200
    assert c.get('/ui/recipes').status_code==200
    assert c.get('/ui/procurement').status_code==200
