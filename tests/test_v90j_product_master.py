from fastapi.testclient import TestClient
from uuid import uuid4
from app.__main__ import app, engine
from app.org_structure import create_entity
from app.access_scope import grant_entity_access


def login(client):
    r=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def make_scope():
    org=uuid4(); eid=uuid4()
    create_entity(engine,str(eid),'J-ENT-' + str(eid)[:8], 'V90J Entity')
    grant_entity_access(engine,'erpadmin',str(eid))
    return org,eid


def approve(client, headers, org, rid):
    midger=str(uuid4())
    from app.identity import create_user
    create_user(engine, midger, 'v90j_mgr_'+str(rid)[:6], 'mgr-pass', 'V90J Manager', 'manager')
    grant_entity_access(engine, midger, str(eid_global))
    rh=client.post('/auth/login',json={'username':'v90j_mgr_'+str(rid)[:6],'password':'mgr-pass'})
    assert rh.status_code==200
    hm={'Authorization':f"Bearer {rh.json()['access_token']}"}
    rr=client.post(f'/v90i/approval-queue/{rid}/approve',json={'organization_id':str(org),'reason':'approved'},headers=hm)
    assert rr.status_code==200, rr.text
    return rr.json()['master_id']


def test_product_pack_sku_workflow_and_relationships():
    global eid_global
    client=TestClient(app); h=login(client); org,eid=make_scope(); eid_global=eid
    product={"organization_id":str(org),"entity_id":str(eid),"action":"CREATE","payload":{"code":"P-J1","name":"Motichur Boondi","description":"test","active":True}}
    r=client.post('/v90j/product-masters/PRODUCT/changes',json=product,headers=h); assert r.status_code==200, r.text
    product_id=approve(client,h,org,r.json()['request_id'])
    pack={"organization_id":str(org),"entity_id":str(eid),"action":"CREATE","payload":{"code":"PK-500G","name":"500 g","quantity":500,"uom":"g"}}
    r=client.post('/v90j/product-masters/PACK_SIZE/changes',json=pack,headers=h); assert r.status_code==200, r.text
    pack_id=approve(client,h,org,r.json()['request_id'])
    sku={"organization_id":str(org),"entity_id":str(eid),"action":"CREATE","payload":{"sku":"BOONDI-500","name":"Motichur Boondi 500g","product_id":product_id,"pack_size_id":pack_id,"barcode":"890000000001"}}
    r=client.post('/v90j/product-masters/SKU/changes',json=sku,headers=h); assert r.status_code==200, r.text
    sku_id=approve(client,h,org,r.json()['request_id'])
    conf=client.get(f'/v90j/sku/{sku_id}/configuration',params={'organization_id':str(org),'entity_id':str(eid)},headers=h)
    assert conf.status_code==200 and conf.json()['sku']['sku']=='BOONDI-500'
    dup=client.post('/v90j/product-masters/SKU/changes',json={"organization_id":str(org),"entity_id":str(eid),"action":"CREATE","payload":{"sku":"BOONDI-500B","name":"Dup barcode","product_id":product_id,"pack_size_id":pack_id,"barcode":"890000000001"}},headers=h)
    assert dup.status_code==422


def test_sku_rejects_missing_parent():
    client=TestClient(app); h=login(client); org,eid=make_scope()
    bad={"organization_id":str(org),"entity_id":str(eid),"action":"CREATE","payload":{"sku":"BAD","name":"Bad SKU","product_id":str(uuid4()),"pack_size_id":str(uuid4())}}
    r=client.post('/v90j/product-masters/SKU/changes',json=bad,headers=h)
    assert r.status_code==422
