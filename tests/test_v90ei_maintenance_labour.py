import json, uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT = Path(__file__).resolve().parents[1]

def auth():
    from app.auth import make_access_token, UserRecord
    return {'Authorization': 'Bearer ' + make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}

def test_release_and_ui():
    d = json.loads((ROOT/'config/release_manifest.json').read_text())
    assert str(d['release']).startswith('v90.') and int(d['schema_target']) >= 210
    assert TestClient(app).get('/ui/maintenance-labour').status_code == 200

def test_maintenance_labour_flow():
    c, h = TestClient(app), auth()
    o, e, w = [str(uuid.uuid4()) for _ in range(3)]
    plan = c.post('/v90dc/maintenance/plans', json={'organization_id':o,'entity_id':e,'work_center_id':w,'plan_name':'PM','frequency_type':'CALENDAR'}, headers=h)
    assert plan.status_code == 200
    oid = c.post('/v90dc/maintenance/orders', json={'organization_id':o,'entity_id':e,'work_center_id':w,'description':'repair'}, headers=h).json()['order_id']
    rate = c.post('/v90ei/maintenance/labour-rates', json={'organization_id':o,'entity_id':e,'work_center_id':w,'labour_category':'TECH','regular_rate':100,'overtime_rate':150,'burden_pct':10}, headers=h)
    assert rate.status_code == 200
    ch = c.post('/v90ei/maintenance/labour-charges', json={'organization_id':o,'entity_id':e,'maintenance_order_id':oid,'work_center_id':w,'labour_category':'TECH','charge_date':'2026-09-08','regular_hours':4,'overtime_hours':2}, headers=h)
    assert ch.status_code == 200
    assert ch.json()['regular_cost'] == 400 and ch.json()['overtime_cost'] == 300 and ch.json()['burden_cost'] == 70 and ch.json()['total_cost'] == 770
    dash = c.get('/v90ei/maintenance/labour/dashboard', params={'organization_id':o,'entity_id':e}, headers=h)
    assert dash.status_code == 200
    assert dash.json()['total_cost'] == 770 and dash.json()['overtime_share_pct'] == 33.33
    closed = c.post('/v90ei/maintenance/labour/2026-09-01/2026-09-30/close', json={'organization_id':o,'entity_id':e}, headers=h)
    assert closed.status_code == 200 and closed.json()['status'] == 'CLOSED'
