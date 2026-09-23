from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
from sqlalchemy import text
from uuid import uuid4


def setup_user(role='manager'):
    uid=str(uuid4()); uname='bj_'+uid[:8]
    create_user(engine, uid, uname, 'pw', 'BJ User', role)
    return uid, uname


def token_for(uid, uname, role='manager'):
    return make_access_token(UserRecord(uid, uname, role))


def test_web_entrypoint_and_static_asset():
    c=TestClient(app)
    r=c.get('/web')
    assert r.status_code==200 and 'Namkeen ERP' in r.text
    assert c.get('/web/assets/app.css').status_code==200


def test_ui_manifest_requires_scope_permission():
    uid,uname=setup_user(); c=TestClient(app,headers={'Authorization':f'Bearer {token_for(uid,uname)}'})
    r=c.get('/v90bj/ui-manifest')
    assert r.status_code==200
    body=r.json(); assert body['web']['entry']=='/web'; assert body['android']['application_id']=='com.namkeen.erp'


def test_ui_build_registry_round_trip():
    uid,uname=setup_user(); c=TestClient(app,headers={'Authorization':f'Bearer {token_for(uid,uname)}'})
    payload={'target':'ANDROID','build_version':'90.bj-debug','artifact':'app-debug.apk','commit_sha':'abc','metadata':{'variant':'debug'}}
    r=c.post('/v90bj/build-registry',json=payload); assert r.status_code==200, r.text
    b=c.get('/v90bj/build-registry?target=ANDROID'); assert b.status_code==200
    rows=b.json()['builds']; assert rows and rows[0]['target']=='ANDROID' and rows[0]['build_version']=='90.bj-debug'


def test_ui_build_registry_permission_denied_for_operator():
    uid,uname=setup_user(role='operator'); c=TestClient(app,headers={'Authorization':f'Bearer {token_for(uid,uname,"operator")}'} )
    assert c.post('/v90bj/build-registry',json={'target':'WEB','build_version':'90.bj'}).status_code==403


def test_migration_135_and_release_metadata():
    from app.migrations import load_migrations
    from app.release import load_release_info
    ms=load_migrations(); assert any(m.version==135 and m.filename=='135_v90bj_ui_mobile_web_integration.sql' for m in ms)
    assert int(load_release_info().schema_target) >= 135
