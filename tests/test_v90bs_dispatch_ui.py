import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]

def login():
    from app.auth import make_access_token, UserRecord
    return TestClient(app), {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}

def test_manifest_and_release():
    mm=json.loads((ROOT/'config/migration_manifest.json').read_text())['migrations']
    assert any(m['version']==144 and m['filename']=='144_v90bs_dispatch_ui.sql' for m in mm)
    rel=json.loads((ROOT/'config/release_manifest.json').read_text())
    assert int(rel['schema_target'])>=144 and rel['release'].startswith('v90.')

def test_dispatch_ui_route_and_summary():
    c,h=login()
    assert c.get('/ui/dispatch',headers=h).status_code==200
    import uuid
    ids=[str(uuid.uuid4()) for _ in range(3)]
    r=c.get('/v90bs/dispatch/summary',params={'organization_id':ids[0],'entity_id':ids[1],'location_id':ids[2]},headers=h)
    assert r.status_code in (200,403)

def test_preferences_roundtrip():
    c,h=login()
    r=c.put('/v90bs/preferences/dispatch',json={'filters':{'status':'POSTED'},'columns':['dispatch_no','status']},headers=h)
    assert r.status_code==200
    g=c.get('/v90bs/preferences/dispatch',headers=h)
    assert g.status_code==200 and g.json()['filters']['status']=='POSTED'
