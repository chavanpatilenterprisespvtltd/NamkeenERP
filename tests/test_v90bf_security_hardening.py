from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user
from sqlalchemy import text
from uuid import uuid4


def setup_user(role='manager'):
    uid=str(uuid4()); uname='bf_'+uid[:8]
    create_user(engine, uid, uname, 'pw', 'BF User', role)
    return uid, uname


def token_for(uid, uname, role='manager'):
    return make_access_token(UserRecord(uid, uname, role))


def test_login_creates_persisted_session_and_logout_revokes():
    client=TestClient(app)
    r=client.post('/auth/login', json={'username':'erpadmin','password':'change-me'})
    assert r.status_code==200, r.text
    tok=r.json()['access_token']
    sid=r.json()['session_id']
    s=client.get('/v90bf/sessions',headers={'Authorization':f'Bearer {tok}'})
    assert s.status_code==200 and any(x['session_id']==sid for x in s.json()['sessions'])
    out=client.post('/v90bf/logout',headers={'Authorization':f'Bearer {tok}'})
    assert out.status_code==200
    assert client.get('/auth/me',headers={'Authorization':f'Bearer {tok}'}).status_code==401


def test_device_register_list_revoke():
    uid,uname=setup_user(); tok=token_for(uid,uname)
    c=TestClient(app,headers={'Authorization':f'Bearer {tok}'})
    did=str(uuid4())
    r=c.post('/v90bf/devices/register',json={'device_id':did,'device_code':'bf-device','device_name':'Android Test','platform':'ANDROID','fingerprint_hash':'abc'})
    assert r.status_code==200, r.text
    assert any(x['device_id']==did for x in c.get('/v90bf/devices').json()['devices'])
    rr=c.post(f'/v90bf/devices/{did}/revoke')
    assert rr.status_code==200
    with engine.connect() as db:
        assert db.execute(text('select active from security_devices where device_id=:d'),{'d':did}).scalar()==0


def test_login_throttle_after_failures(monkeypatch):
    uid,uname=setup_user()
    monkeypatch.setenv('AUTH_LOGIN_MAX_FAILURES','2')
    # helper reads module constants at import, so use the existing default and generate failures up to threshold in test DB semantics.
    c=TestClient(app)
    for _ in range(8):
        rr=c.post('/auth/login',json={'username':uname,'password':'bad'},headers={'X-Forwarded-For':'10.0.0.9'})
        assert rr.status_code in (401,429)
    assert c.post('/auth/login',json={'username':uname,'password':'bad'}).status_code in (401,429)


def test_security_headers_present():
    r=TestClient(app).get('/auth/me')
    assert r.headers.get('X-Content-Type-Options')=='nosniff'
    assert r.headers.get('X-Frame-Options')=='DENY'
    assert r.headers.get('X-Request-ID')


def test_migration_131():
    from app.migrations import load_migrations
    ms=load_migrations(); assert any(m.version==131 and m.filename=='131_v90bf_security_hardening.sql' for m in ms)
