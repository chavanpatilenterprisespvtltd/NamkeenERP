from uuid import uuid4
from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.org_structure import create_entity, create_location
from app.access_scope import grant_entity_access, grant_location_access
from app.identity import create_user


def login(client, username='erpadmin', password='change-me'):
    r = client.post('/auth/login', json={'username': username, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def make_scope():
    org = uuid4(); eid = uuid4(); lid = uuid4()
    create_entity(engine, str(eid), 'K-ENT-' + str(eid)[:8], 'V90K Entity')
    create_location(engine, str(lid), str(eid), 'K-LOC-' + str(lid)[:8], 'V90K Site')
    grant_entity_access(engine, 'erpadmin', str(eid))
    grant_location_access(engine, 'erpadmin', str(lid))
    return org, eid, lid


def approve(client, org, eid, rid):
    username = 'v90k_mgr_' + str(uuid4())[:8]
    uid = str(uuid4())
    create_user(engine, uid, username, 'mgr-pass', 'V90K Manager', 'manager')
    grant_entity_access(engine, uid, str(eid))
    rh = client.post('/auth/login', json={'username': username, 'password': 'mgr-pass'})
    assert rh.status_code == 200, rh.text
    hm = {'Authorization': f"Bearer {rh.json()['access_token']}"}
    rr = client.post(f'/v90i/approval-queue/{rid}/approve', json={'organization_id': str(org), 'reason': 'approved'}, headers=hm)
    assert rr.status_code == 200, rr.text
    return rr.json()['master_id']


def test_customer_supplier_and_bin_workflows():
    client=TestClient(app); h=login(client); org,eid,lid=make_scope()
    customer={"organization_id":str(org),"entity_id":str(eid),"location_id":str(lid),"action":"CREATE","payload":{"code":"C-K1","name":"Shree Traders","phone":"9876543210","gstin":"27ABCDE1234F1Z5","credit_limit":50000}}
    r=client.post('/v90k/operational-masters/CUSTOMER/changes',json=customer,headers=h); assert r.status_code==200,r.text
    cid=approve(client,org,eid,r.json()['request_id'])
    supplier={"organization_id":str(org),"entity_id":str(eid),"location_id":str(lid),"action":"CREATE","payload":{"code":"S-K1","name":"Agro Supplier","payment_terms_days":7}}
    r=client.post('/v90k/operational-masters/SUPPLIER/changes',json=supplier,headers=h); assert r.status_code==200,r.text
    sid=approve(client,org,eid,r.json()['request_id'])
    warehouse={"organization_id":str(org),"entity_id":str(eid),"location_id":str(lid),"action":"CREATE","payload":{"code":"WH-K1","name":"RM Store","warehouse_type":"raw_material"}}
    r=client.post('/v90k/operational-masters/WAREHOUSE/changes',json=warehouse,headers=h); assert r.status_code==200,r.text
    wid=approve(client,org,eid,r.json()['request_id'])
    bin_payload={"organization_id":str(org),"entity_id":str(eid),"location_id":str(lid),"action":"CREATE","payload":{"code":"BIN-K1","name":"Rack A1","warehouse_id":wid,"zone":"A","aisle":"01","rack":"01"}}
    r=client.post('/v90k/operational-masters/BIN/changes',json=bin_payload,headers=h); assert r.status_code==200,r.text
    bid=approve(client,org,eid,r.json()['request_id'])
    loc=client.get(f'/v90k/bin/{bid}/location',params={'organization_id':str(org),'entity_id':str(eid)},headers=h)
    assert loc.status_code==200 and loc.json()['warehouse_id']==wid


def test_validation_and_scope():
    client=TestClient(app); h=login(client); org,eid,lid=make_scope()
    bad={"organization_id":str(org),"entity_id":str(eid),"location_id":str(lid),"action":"CREATE","payload":{"code":"C-K2","name":"Bad","gstin":"BAD"}}
    r=client.post('/v90k/operational-masters/CUSTOMER/changes',json=bad,headers=h); assert r.status_code==422
    badbin={"organization_id":str(org),"entity_id":str(eid),"location_id":str(lid),"action":"CREATE","payload":{"code":"BIN-K2","name":"Bad Bin","warehouse_id":str(uuid4())}}
    r=client.post('/v90k/operational-masters/BIN/changes',json=badbin,headers=h); assert r.status_code==422
