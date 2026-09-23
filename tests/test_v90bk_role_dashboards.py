from fastapi.testclient import TestClient
from app.__main__ import app
from app.auth import make_access_token, UserRecord
from app.identity import create_user
from uuid import uuid4


def setup(role='manager'):
    uid = str(uuid4()); uname = 'bk_' + uid[:8]
    create_user(__import__('app.__main__', fromlist=['engine']).engine, uid, uname, 'pw', 'BK User', role)
    return uid, uname


def client(uid, uname, role='manager'):
    return TestClient(app, headers={'Authorization': f'Bearer {make_access_token(UserRecord(uid, uname, role))}'})


def test_role_scoped_screens():
    uid, uname = setup('production'); c = client(uid, uname, 'production')
    r = c.get('/v90bk/screens'); assert r.status_code == 200
    ids = {x['screen_id'] for x in r.json()['screens']}
    assert 'production' in ids and 'sales' not in ids


def test_default_dashboard_widgets():
    uid, uname = setup('dispatch'); c = client(uid, uname, 'dispatch')
    r = c.get('/v90bk/dashboard'); assert r.status_code == 200
    assert 'dispatch_queue' in r.json()['widgets'] and r.json()['role'] == 'dispatch'


def test_dashboard_preferences_round_trip():
    uid, uname = setup('manager'); c = client(uid, uname)
    payload = {'dashboard_key':'home','widgets':['kpi_sales','alerts_approvals']}
    assert c.put('/v90bk/dashboard', json=payload).status_code == 200
    r = c.get('/v90bk/dashboard?dashboard_key=home'); assert r.status_code == 200
    assert r.json()['widgets'] == payload['widgets']


def test_dashboard_permission_denied_for_operator():
    uid, uname = setup('operator'); c = client(uid, uname, 'operator')
    assert c.put('/v90bk/dashboard', json={'widgets':['production_today']}).status_code == 403


def test_unknown_screen_is_not_exposed_to_role():
    uid, uname = setup('salesperson'); c = client(uid, uname, 'salesperson')
    ids = {x['screen_id'] for x in c.get('/v90bk/screens').json()['screens']}
    assert 'inventory' not in ids


def test_migration_136_and_release_metadata():
    from app.migrations import load_migrations
    from app.release import load_release_info
    ms = load_migrations(); assert any(m.version == 136 and m.filename == '136_v90bk_role_dashboards_ui_screens.sql' for m in ms)
    assert load_release_info().version.startswith('v90.') and int(load_release_info().schema_target) >= 136
