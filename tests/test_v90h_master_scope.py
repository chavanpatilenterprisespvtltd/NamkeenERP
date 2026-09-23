from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.org_structure import create_entity, create_location
from app.access_scope import grant_entity_access, grant_location_access

def test_master_scope_read_and_write():
    client=TestClient(app)
    # admin is seeded by identity bootstrap
    r=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200
    t=r.json()['access_token']
    h={'Authorization':f'Bearer {t}'}
    create_entity(engine,'h_e1','H1','H Entity')
    create_location(engine,'h_l1','h_e1','HLOC','H Location')
    grant_entity_access(engine,'erpadmin','h_e1')
    grant_location_access(engine,'erpadmin','h_l1')
    assert client.get('/masters/access-check',params={'entity_id':'h_e1','location_id':'h_l1'},headers=h).status_code==200
    r=client.post('/masters/access-check',json={'entity_id':'h_e1','location_id':'h_l1'},headers=h)
    assert r.status_code==200
