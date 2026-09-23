from sqlalchemy import text
from fastapi.testclient import TestClient
from app.__main__ import app, engine

def test_org_tables_exist():
    with engine.connect() as c:
        for t in ['erp_entities','erp_locations','erp_departments','erp_responsibilities','erp_user_org_assignments']:
            assert c.execute(text(f'select count(*) from {t}')).scalar() >= 0

def test_admin_can_create_org_structure():
    client = TestClient(app)
    tok = client.post('/auth/login', json={'username':'erpadmin','password':'change-me'}).json()['access_token']
    h={'Authorization':f'Bearer {tok}'}
    assert client.post('/admin/entities',headers=h,json={'entity_id':'ent-f','entity_code':'FCO','entity_name':'Factory Entity'}).status_code==200
    assert client.post('/admin/locations',headers=h,json={'location_id':'loc-f','entity_id':'ent-f','location_code':'PLANT','location_name':'Main Plant','location_type':'factory'}).status_code==200
    assert client.post('/admin/departments',headers=h,json={'department_id':'dep-f','entity_id':'ent-f','department_code':'PROD','department_name':'Production'}).status_code==200
    assert client.post('/admin/responsibilities',headers=h,json={'responsibility_id':'resp-f','entity_id':'ent-f','department_id':'dep-f','responsibility_code':'MANUFACTURING','responsibility_name':'Manufacturing','module_name':'Production'}).status_code==200
