from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.identity import create_user, permissions_for_user
from sqlalchemy import text

def test_identity_seeded():
    with engine.connect() as c:
        assert c.execute(text('select count(*) from erp_roles')).scalar() >= 4
        assert c.execute(text('select count(*) from erp_permissions')).scalar() >= 10

def test_persistent_user_login_and_permissions():
    try:
        create_user(engine,'u-eve','eve','secret-e','Eve','salesperson')
    except Exception:
        pass
    client=TestClient(app)
    r=client.post('/auth/login',json={'username':'eve','password':'secret-e'})
    assert r.status_code==200
    token=r.json()['access_token']
    p=client.get('/auth/permissions',headers={'Authorization':f'Bearer {token}'})
    assert p.status_code==200
    assert 'sales.edit' in p.json()['permissions']
    assert 'admin.users' not in p.json()['permissions']

def test_admin_can_create_user():
    client=TestClient(app)
    r=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    token=r.json()['access_token']
    out=client.post('/admin/users',headers={'Authorization':f'Bearer {token}'},json={'user_id':'u-new','username':'newuser','password':'pw','display_name':'New User','role_id':'operator'})
    assert out.status_code==200
