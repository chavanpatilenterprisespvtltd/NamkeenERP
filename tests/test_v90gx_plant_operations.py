# FILE PATH: tests/test_v90gx_plant_operations.py
# ─── V90.gx Plant Registers, Business Date, Notifications & Worker tests v1.0 (Session CS2 — new) ─
# [Session CS2] FEATURE — oil TPM rule, fuel/utility maths, carton variance, complaint lifecycle (HIGH needs
# CAPA), purchase return stock + debit note, business-date limits, notification outbox with a local fake
# webhook gateway, stub provider never reports SENT, worker single cycle.
import json
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.__main__ import app, engine
from app.auth import UserRecord, make_access_token
from app.business_date import parse_business_date
from app.v90gx_notifications import enqueue, enqueue_daily_alerts, process_outbox

H = {'Authorization': 'Bearer ' + make_access_token(UserRecord('erpadmin', 'erpadmin', 'super_admin'))}
TODAY = datetime.now(timezone.utc).date()


def scope():
    o, e, l = str(uuid4()), str(uuid4()), str(uuid4())
    with engine.begin() as c:
        c.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:i,:c,'P','legal_entity')"), {'i': e, 'c': 'P' + e[:6]})
    return {'organization_id': o, 'entity_id': e, 'location_id': l}


def test_business_date_rules():
    assert parse_business_date(None) is None
    assert parse_business_date((TODAY - timedelta(days=1)).isoformat()) == (TODAY - timedelta(days=1)).isoformat()
    with pytest.raises(HTTPException):
        parse_business_date((TODAY + timedelta(days=5)).isoformat())
    with pytest.raises(HTTPException):
        parse_business_date((TODAY - timedelta(days=30)).isoformat())


def test_oil_fuel_utility_cartons_and_daily_summary():
    c = TestClient(app); s = scope(); yday = (TODAY - timedelta(days=1)).isoformat()
    r = c.post('/v90gx/plant/oil-log', headers=H, json={**s, 'business_date': yday, 'fryer_id': 'FRYER-1', 'opening_litres': 120, 'topped_up_litres': 30, 'discarded_litres': 0, 'closing_litres': 110, 'tpm_pct': 26})
    assert r.status_code == 200 and r.json()['consumed_litres'] == 40.0 and r.json()['status'] == 'DISCARD_REQUIRED'
    assert c.post('/v90gx/plant/oil-log', headers=H, json={**s, 'fryer_id': 'F', 'opening_litres': 10, 'closing_litres': 20}).status_code == 422
    r = c.post('/v90gx/plant/fuel-log', headers=H, json={**s, 'business_date': yday, 'fuel_type': 'WOOD', 'quantity': 350, 'uom': 'kg', 'rate': 7.5})
    assert r.json()['amount'] == 2625.0
    r = c.post('/v90gx/plant/utility-log', headers=H, json={**s, 'business_date': yday, 'utility_type': 'ELECTRICITY', 'meter_id': 'MSEB-1', 'opening_reading': 1000, 'closing_reading': 1240, 'rate': 11})
    assert r.json()['units'] == 240.0 and r.json()['amount'] == 2640.0
    assert c.post('/v90gx/plant/utility-log', headers=H, json={**s, 'utility_type': 'WATER', 'meter_id': 'W', 'opening_reading': 50, 'closing_reading': 40}).status_code == 422
    r = c.post('/v90gx/plant/carton-consumption', headers=H, json={**s, 'sku_id': str(uuid4()), 'packs_packed': 205, 'packs_per_carton': 20, 'cartons_used': 12})
    assert r.json()['expected_cartons'] == 11 and r.json()['variance_cartons'] == 1
    d = c.get('/v90gx/plant/daily-summary', headers=H, params={'entity_id': s['entity_id'], 'business_date': yday}).json()
    assert d['oil']['consumed_litres'] == 40.0 and d['oil']['discard_required'] == 1 and d['fuel'][0]['amount'] == 2625.0 and d['utilities'][0]['units'] == 240.0
    assert len(c.get('/v90gx/plant/registers/oil', headers=H, params={'entity_id': s['entity_id']}).json()['rows']) == 1


def test_complaint_lifecycle_high_needs_capa():
    c = TestClient(app); s = scope()
    r = c.post('/v90gx/complaints', headers=H, json={'organization_id': s['organization_id'], 'entity_id': s['entity_id'], 'customer_name': 'Shree Stores', 'lot_code': 'SF-260925-01',
               'category': 'FOREIGN_MATTER', 'severity': 'LOW', 'description': 'Small stone found in 500 g pack'})
    assert r.status_code == 200 and r.json()['severity'] == 'HIGH'
    cid = r.json()['complaint_id']
    assert c.post(f'/v90gx/complaints/{cid}/investigate', headers=H).json()['status'] == 'INVESTIGATING'
    assert c.post(f'/v90gx/complaints/{cid}/close', headers=H, json={'root_cause': 'Sieve torn', 'action_taken': 'Sieve replaced'}).status_code == 422
    assert c.post(f'/v90gx/complaints/{cid}/close', headers=H, json={'root_cause': 'Sieve torn', 'action_taken': 'Sieve replaced', 'capa_ref': 'CAPA-12'}).status_code == 200
    assert c.get('/v90gx/complaints', headers=H, params={'entity_id': s['entity_id'], 'status': 'CLOSED'}).json()['complaints'][0]['capa_ref'] == 'CAPA-12'


def test_purchase_return_moves_stock_and_numbers_debit_note():
    c = TestClient(app); s = scope(); wh, item = str(uuid4()), str(uuid4())
    base = {'organization_id': s['organization_id'], 'address_line1': 'Gat 12', 'city': 'Pune', 'state_code': '27', 'pincode': '411001'}
    assert c.put(f"/v90gx/entities/{s['entity_id']}/profile", headers=H, json={**base, 'legal_name': 'X Mfg', 'business_role': 'MANUFACTURER', 'invoice_prefix': 'XPR'}).status_code == 200
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:m,:o,:e,:l,:w,:i,NULL,'GRN_RECEIPT',100,'kg','GRN','g1','POSTED','erpadmin')"),
                     {'m': str(uuid4()), 'o': s['organization_id'], 'e': s['entity_id'], 'l': s['location_id'], 'w': wh, 'i': item})
        conn.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:i,'kg',100)"),
                     {'o': s['organization_id'], 'e': s['entity_id'], 'l': s['location_id'], 'w': wh, 'i': item})
    body = {**s, 'warehouse_id': wh, 'supplier_id': str(uuid4()), 'reason': 'QC_REJECTED', 'lines': [{'item_master_id': item, 'quantity': 25, 'uom': 'kg', 'rate': 90, 'gst_rate': 5}]}
    r = c.post('/v90gx/purchase-returns', headers=H, json=body)
    assert r.status_code == 200 and r.json()['total_value'] == 2362.5
    r = c.post(f"/v90gx/purchase-returns/{r.json()['return_id']}/post", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()['debit_note_no'].startswith('XPRD/')
    with engine.connect() as conn:
        assert float(conn.execute(text('SELECT SUM(quantity) FROM inventory_stock_ledger WHERE entity_id=:e AND item_master_id=:i'), {'e': s['entity_id'], 'i': item}).scalar()) == 75.0
        assert float(conn.execute(text('SELECT available_qty FROM inventory_stock_balance WHERE entity_id=:e AND item_master_id=:i'), {'e': s['entity_id'], 'i': item}).scalar()) == 75.0
    big = {**body, 'lines': [{'item_master_id': item, 'quantity': 500, 'uom': 'kg', 'rate': 90}]}
    rid = c.post('/v90gx/purchase-returns', headers=H, json=big).json()['return_id']
    assert c.post(f'/v90gx/purchase-returns/{rid}/post', headers=H).status_code == 409


class _Gateway(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        _Gateway.received.append((self.headers.get('Authorization'), body))
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"message_id":"gw-1"}')

    def log_message(self, *a):
        pass


def test_notifications_webhook_and_stub(monkeypatch):
    srv = HTTPServer(('127.0.0.1', 0), _Gateway); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv('NOTIFICATION_PROVIDER', 'webhook')
        monkeypatch.setenv('NOTIFICATION_WEBHOOK_URL', f'http://127.0.0.1:{srv.server_port}/send')
        monkeypatch.setenv('NOTIFICATION_API_KEY', 'k-123')
        monkeypatch.delenv('SMTP_HOST', raising=False)
        nid = enqueue(engine, channel='WHATSAPP', recipient='+919800000000', body='Order dispatched', reference='test-wa')
        res = process_outbox(engine)
        assert res['sent'] >= 1
        assert any(a == 'Bearer k-123' and b['notification_id'] == nid and b['channel'] == 'WHATSAPP' for a, b in _Gateway.received)
        with engine.connect() as c:
            assert c.execute(text('SELECT status,provider_message_id FROM notification_outbox WHERE notification_id=:i'), {'i': nid}).first() == ('SENT', 'gw-1')
    finally:
        srv.shutdown()
    monkeypatch.setenv('NOTIFICATION_PROVIDER', 'stub')
    nid2 = enqueue(engine, channel='SMS', recipient='+919800000001', body='x')
    process_outbox(engine)
    with engine.connect() as c:
        assert c.execute(text('SELECT status FROM notification_outbox WHERE notification_id=:i'), {'i': nid2}).scalar() == 'SKIPPED_STUB'
    key = 'same-' + str(uuid4())
    assert enqueue(engine, channel='SMS', recipient='+919800000001', body='x', dedupe_key=key) is not None
    assert enqueue(engine, channel='SMS', recipient='+919800000001', body='x', dedupe_key=key) is None


def test_fssai_expiry_alert_and_worker_cycle(monkeypatch):
    c = TestClient(app); s = scope()
    base = {'organization_id': s['organization_id'], 'address_line1': 'Gat 12', 'city': 'Pune', 'state_code': '27', 'pincode': '411001'}
    soon = (TODAY + timedelta(days=20)).isoformat()
    assert c.put(f"/v90gx/entities/{s['entity_id']}/profile", headers=H, json={**base, 'legal_name': 'Expiring Co', 'business_role': 'MANUFACTURER', 'fssai_license_no': '11526999000999',
                 'fssai_valid_to': soon, 'email': 'qa@example.com'}).status_code == 200
    monkeypatch.setenv('NOTIFICATION_PROVIDER', 'stub')
    assert enqueue_daily_alerts(engine) >= 1
    assert enqueue_daily_alerts(engine) == 0  # deduped for the same day
    from app.worker import run_cycle
    out = run_cycle(engine, {})
    assert 'skipped_stub' in out
