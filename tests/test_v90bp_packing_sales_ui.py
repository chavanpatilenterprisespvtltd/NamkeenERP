import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app, engine

ROOT = Path(__file__).resolve().parents[1]

def login():
    from app.auth import make_access_token, UserRecord
    c=TestClient(app)
    return c, {'Authorization': 'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}

def test_migration_and_release():
    mm=json.loads((ROOT/'config/migration_manifest.json').read_text())['migrations']
    assert any(m['version']==141 and m['filename']=='141_v90bp_packing_sales_ui.sql' for m in mm)
    rel=json.loads((ROOT/'config/release_manifest.json').read_text())
    assert int(rel['schema_target'])>=141 and rel['release'].startswith('v90.')

def test_ui_routes_require_auth_and_exist():
    c=TestClient(app)
    assert c.get('/ui/packing').status_code==200
    assert c.get('/ui/sales').status_code==200
    cc,h=login()
    assert cc.get('/ui/packing',headers=h).status_code==200
    assert cc.get('/ui/sales',headers=h).status_code==200

def test_summary_endpoints_scope_and_empty_payload():
    c,h=login()
    import uuid
    ids=[str(uuid.uuid4()) for _ in range(3)]
    r=c.get('/v90bp/packing/summary',params={'organization_id':ids[0],'entity_id':ids[1],'location_id':ids[2]},headers=h)
    assert r.status_code in (200,403)
    r=c.get('/v90bp/sales/summary',params={'organization_id':ids[0],'entity_id':ids[1],'location_id':ids[2]},headers=h)
    assert r.status_code in (200,403)
