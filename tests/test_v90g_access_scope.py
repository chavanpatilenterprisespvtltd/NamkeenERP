from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.identity import create_user
from app.access_scope import grant_entity_access, grant_location_access, grant_warehouse_access
from sqlalchemy import text


def test_access_scope_tables_exist():
    with engine.connect() as c:
        for t in ['erp_entity_user_access','erp_location_user_access','erp_warehouses','erp_warehouse_user_access']:
            assert c.execute(text(f'select count(*) from {t}')).scalar() >= 0


def test_admin_can_create_warehouse_and_scope():
    client=TestClient(app)
    tok=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'}).json()['access_token']
    h={'Authorization':f'Bearer {tok}'}
    for p in [
        ('/admin/entities', {'entity_id':'ent-g','entity_code':'GCO','entity_name':'G Entity'}),
        ('/admin/locations', {'location_id':'loc-g','entity_id':'ent-g','location_code':'GPLANT','location_name':'G Plant'}),
        ('/admin/users', {'user_id':'u-g','username':'scopeuser','password':'pw-g','display_name':'Scope User','role_id':'operator'}),
        ('/admin/warehouses', {'warehouse_id':'wh-g','entity_id':'ent-g','location_id':'loc-g','warehouse_code':'RM01','warehouse_name':'RM Warehouse'}),
    ]:
        r=client.post(p[0],headers=h,json=p[1]); assert r.status_code==200, r.text
    assert client.post('/admin/access/entity',headers=h,json={'user_id':'u-g','entity_id':'ent-g'}).status_code==200
    assert client.post('/admin/access/location',headers=h,json={'user_id':'u-g','location_id':'loc-g'}).status_code==200
    assert client.post('/admin/access/warehouse',headers=h,json={'user_id':'u-g','warehouse_id':'wh-g'}).status_code==200
    tok2=client.post('/auth/login',json={'username':'scopeuser','password':'pw-g'}).json()['access_token']
    r=client.get('/auth/scope',headers={'Authorization':f'Bearer {tok2}'})
    assert r.status_code==200
    body=r.json(); assert body['entities']==['ent-g']; assert body['locations']==['loc-g']; assert body['warehouses']==['wh-g']
    assert client.get('/access/check/entity/ent-g',headers={'Authorization':f'Bearer {tok2}'}).json()['allowed'] is True
    assert client.get('/access/check/entity/other',headers={'Authorization':f'Bearer {tok2}'}).json()['allowed'] is False
