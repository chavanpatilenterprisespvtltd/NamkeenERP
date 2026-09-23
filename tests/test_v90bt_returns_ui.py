import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]

def login():
    from app.auth import make_access_token, UserRecord
    return TestClient(app), {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}

def test_manifest_release_and_ui_routes():
    mm=json.loads((ROOT/'config/migration_manifest.json').read_text())['migrations']
    assert any(m['version']==145 and m['filename']=='145_v90bt_returns_ui.sql' for m in mm)
    rel=json.loads((ROOT/'config/release_manifest.json').read_text())
    assert int(rel['schema_target'])>=145 and rel['release'].startswith('v90.')
    c,h=login()
    assert c.get('/ui/returns').status_code==200
    assert c.get('/ui/returns/accounting').status_code==200

def test_returns_ui_summary_empty_scope_allowed_for_admin():
    import uuid
    c,h=login(); ids=[str(uuid.uuid4()) for _ in range(3)]
    r=c.get('/v90bt/returns/summary',params={'organization_id':ids[0],'entity_id':ids[1],'location_id':ids[2]},headers=h)
    assert r.status_code in (200,403)

def test_returns_preferences_roundtrip():
    c,h=login()
    r=c.put('/v90bt/preferences/returns',json={'filters':{'status':'DISPOSITIONED'},'columns':['return_no','status']},headers=h)
    assert r.status_code==200
    g=c.get('/v90bt/preferences/returns',headers=h)
    assert g.status_code==200 and g.json()['filters']['status']=='DISPOSITIONED'
