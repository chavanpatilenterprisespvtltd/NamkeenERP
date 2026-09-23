from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.identity import create_user
from app.access_scope import grant_entity_access, grant_location_access, grant_warehouse_access, create_warehouse
from app.auth import make_access_token, UserRecord
from sqlalchemy import text
from uuid import uuid4


def _admin(client):
    r=client.post('/auth/login',json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200, r.text
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_organization_scope_and_cross_org_entity_denial():
    c=TestClient(app); h=_admin(c)
    uid='fn-'+str(uuid4())[:8]; uname='fnuser_'+uid[-4:]
    assert c.post('/admin/users',headers=h,json={'user_id':uid,'username':uname,'password':'pw','display_name':'FN User','role_id':'operator'}).status_code==200
    # use IDs present in entity/location masters for scope chain
    org1,org2='fn-org1','fn-org2'; e1,e2='fn-e1','fn-e2'; l1='fn-l1'; w1='fn-w1'
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:e,:c,:n,'legal_entity') ON CONFLICT(entity_id) DO NOTHING"),{'e':e1,'c':'FNE1','n':'FN E1'})
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:e,:c,:n,'legal_entity') ON CONFLICT(entity_id) DO NOTHING"),{'e':e2,'c':'FNE2','n':'FN E2'})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type) VALUES(:l,:e,'FNL1','FN L1','site') ON CONFLICT(location_id) DO NOTHING"),{'l':l1,'e':e1})
    create_warehouse(engine,w1,e1,l1,'FNW1','FN Warehouse')
    assert c.post(f'/v90fn/security/entity/{e1}/organization/{org1}',headers=h).status_code==200
    assert c.post(f'/v90fn/security/entity/{e2}/organization/{org2}',headers=h).status_code==200
    assert c.post(f'/v90fn/security/users/{uid}/organization/{org1}',headers=h).status_code==200
    # Admin can see target user's security context.
    login=c.post('/auth/login',json={'username':uname,'password':'pw'}); assert login.status_code==200, login.text
    uh={'Authorization':f"Bearer {login.json()['access_token']}"}
    # organization scope alone permits the entity but not unrelated organization.
    from app.v90fn_security_rbac_scope_hardening import assert_security_scope
    assert_security_scope(engine,uid,organization_id=org1,entity_id=e1)
    try:
        assert_security_scope(engine,uid,organization_id=org2)
        assert False, 'cross-org access should be denied'
    except PermissionError:
        pass
    # grant source entity/location/warehouse only within own organization.
    assert c.post(f'/v90fn/security/users/{uid}/scope/entity/{e1}',headers=h).status_code==200
    assert c.post(f'/v90fn/security/users/{uid}/scope/location/{l1}',headers=h).status_code==200
    assert c.post(f'/v90fn/security/users/{uid}/scope/warehouse/{w1}',headers=h).status_code==200
    ctx=c.get('/v90fn/security/context',headers=uh); assert ctx.status_code==200
    assert e1 in ctx.json()['entities'] and l1 in ctx.json()['locations'] and w1 in ctx.json()['warehouses'] and org1 in ctx.json()['organizations']


def test_persisted_session_is_revoked_for_deactivated_user():
    c=TestClient(app); h=_admin(c)
    uid='fn-'+str(uuid4())[:8]; uname='fninactive_'+uid[-4:]
    assert c.post('/admin/users',headers=h,json={'user_id':uid,'username':uname,'password':'pw','display_name':'Inactive FN','role_id':'operator'}).status_code==200
    r=c.post('/auth/login',json={'username':uname,'password':'pw'}); assert r.status_code==200, r.text
    tok=r.json()['access_token']; uh={'Authorization':f'Bearer {tok}'}
    with engine.begin() as db: db.execute(text('UPDATE erp_users SET active=0 WHERE user_id=:u'),{'u':uid})
    assert c.get('/auth/me',headers=uh).status_code==401


def test_migration_240_manifest():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(x.version==241 and x.filename=='241_v90fo_audit_approval_evidence.sql' for x in ms)
