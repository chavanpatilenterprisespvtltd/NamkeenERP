# FILE PATH: tests/test_v90gx_ui_support.py
# ─── V90.gx UI Support tests v1.0 (Session CS2 — new) ─
# [Session CS2] FEATURE — scope lookup, item lookup, scope-picker injection into existing pages, new pages served. Fixtures use TRUE (not 1) for BOOLEAN columns so the file also runs on PostgreSQL.
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.__main__ import app, engine
from app.auth import UserRecord, make_access_token

H = {'Authorization': 'Bearer ' + make_access_token(UserRecord('erpadmin', 'erpadmin', 'super_admin'))}


def test_scope_lookup_lists_entities_locations_warehouses():
    c = TestClient(app)
    o, e, l, w = [str(uuid4()) for _ in range(4)]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:i,:c,'UI','legal_entity')"), {'i': e, 'c': 'U' + e[:6]})
        conn.execute(text("INSERT INTO erp_security_entity_organization(entity_id,organization_id) VALUES(:e,:o)"), {'e': e, 'o': o})
        conn.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name) VALUES(:l,:e,'F1','Factory')"), {'l': l, 'e': e})
        conn.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name) VALUES(:w,:e,:l,'FG','Finished Goods')"), {'w': w, 'e': e, 'l': l})
        conn.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:m,:o,'SKU',:e,TRUE,:d)"), {'m': str(uuid4()), 'o': o, 'e': e, 'd': '{"code":"SF500","name":"Special Farsan 500 g"}'})
    d = c.get('/v90gx/lookups/scope', headers=H).json()
    assert any(x['entity_id'] == e and x['organization_id'] == o for x in d['entities'])
    assert any(x['location_id'] == l for x in d['locations']) and any(x['warehouse_id'] == w for x in d['warehouses'])
    assert {'organization_id': o, 'label': o} in d['organizations']
    items = c.get('/v90gx/lookups/items', headers=H, params={'organization_id': o}).json()['items']
    assert items[0]['label'] == 'SF500 Special Farsan 500 g'
    assert c.get('/v90gx/lookups/scope').status_code == 401


def test_scope_picker_injected_into_existing_and_new_pages():
    c = TestClient(app)
    for path in ('/ui/grn', '/ui/sales', '/ui/company-profile', '/ui/intercompany-xy', '/ui/plant-registers', '/ui/daily-work', '/web'):
        r = c.get(path)
        assert r.status_code == 200, path
        assert r.text.count('/web/assets/scope-picker.js') == 1, path
    assert c.get('/web/assets/scope-picker.js').status_code == 200
    assert c.get('/web/assets/erp-forms.js').status_code == 200
    assert 'scope-picker' not in c.get('/health').text
