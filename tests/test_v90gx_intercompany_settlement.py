# FILE PATH: tests/test_v90gx_intercompany_settlement.py
# ─── V90.gx Intercompany X→Y tests v1.0 (Session CS2 — new) ─
# [Session CS2] FEATURE — covers: no policy → pricing refused; COST_PLUS pricing with CGST/SGST;
# dispatch creates X's IC invoice + INTERCOMPANY_OUT (in transit, nothing yet at Y); short receipt at Y
# requires a reason and posts only the received quantity; elimination opened; settlement cannot exceed
# the outstanding amount; balances show X receivable = Y payable; legacy one-step post refused.
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.__main__ import app, engine
from app.auth import UserRecord, make_access_token
from app.v90gx_company_gst_invoicing import financial_year
from datetime import datetime, timezone

H = {'Authorization': 'Bearer ' + make_access_token(UserRecord('erpadmin', 'erpadmin', 'super_admin'))}
X_GSTIN, Y_GSTIN = '27AAACC1234D1ZC', '27AAFCD5678E1ZG'


def world():
    c = TestClient(app)
    o, x, y, xl, yl, xw, yw, item, lot = [str(uuid4()) for _ in range(9)]
    with engine.begin() as conn:
        for eid, code in ((x, 'X' + x[:6]), (y, 'Y' + y[:6])):
            conn.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:i,:c,:c,'legal_entity')"), {'i': eid, 'c': code})
        conn.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:id,:o,:e,:l,:w,:i,:lot,'PRODUCTION_OUTPUT',100,'kg','TEST',:r,'POSTED','erpadmin')"),
                     {'id': str(uuid4()), 'o': o, 'e': x, 'l': xl, 'w': xw, 'i': item, 'lot': lot, 'r': str(uuid4())})
    base = {'organization_id': o, 'address_line1': 'Gat 12', 'city': 'Pune', 'state_code': '27', 'pincode': '411001'}
    assert c.put(f'/v90gx/entities/{x}/profile', headers=H, json={**base, 'legal_name': 'X Manufacturing Pvt Ltd', 'business_role': 'MANUFACTURER', 'gstin': X_GSTIN, 'invoice_prefix': 'XMF'}).status_code == 200
    assert c.put(f'/v90gx/entities/{y}/profile', headers=H, json={**base, 'legal_name': 'Chavan Patil Enterprises Pvt. Ltd.', 'business_role': 'SALES_MARKETING', 'gstin': Y_GSTIN, 'invoice_prefix': 'CPE'}).status_code == 200
    r = c.post('/v90fm/intercompany/transactions', headers=H, json={'organization_id': o, 'period_key': '2026-09', 'from_entity_id': x, 'to_entity_id': y,
               'lines': [{'item_master_id': item, 'lot_id': lot, 'quantity': 40, 'uom': 'kg', 'unit_value': 0, 'from_location_id': xl, 'from_warehouse_id': xw, 'to_location_id': yl, 'to_warehouse_id': yw}]})
    assert r.status_code == 200, r.text
    return c, {'o': o, 'x': x, 'y': y, 'item': item, 'lot': lot, 'tid': r.json()['transaction_id']}


def qty(org, ent, item):
    with engine.connect() as conn:
        return float(conn.execute(text('SELECT COALESCE(SUM(quantity),0) FROM inventory_stock_ledger WHERE organization_id=:o AND entity_id=:e AND item_master_id=:i'), {'o': org, 'e': ent, 'i': item}).scalar())


def test_x_to_y_full_cycle():
    c, w = world()
    # 1. no agreed policy → refused ("let them decide")
    r = c.post(f"/v90gx/intercompany/transactions/{w['tid']}/price", headers=H, json={'unit_costs': {w['item']: 120}})
    assert r.status_code == 409 and 'policy' in r.text
    # 2. X and Y agree cost + 10 %, GST 5 %
    r = c.post('/v90gx/intercompany/policies', headers=H, json={'organization_id': w['o'], 'from_entity_id': w['x'], 'to_entity_id': w['y'], 'method': 'COST_PLUS', 'markup_pct': 10,
               'gst_rate': 5, 'effective_from': '2026-04-01', 'agreement_ref': 'Board resolution BR-2026-07'})
    assert r.status_code == 200, r.text
    dup = c.post('/v90gx/intercompany/policies', headers=H, json={'organization_id': w['o'], 'from_entity_id': w['x'], 'to_entity_id': w['y'], 'method': 'COST_PLUS', 'markup_pct': 12,
                 'gst_rate': 5, 'effective_from': '2026-05-01', 'agreement_ref': 'dup'})
    assert dup.status_code == 409
    r = c.post(f"/v90gx/intercompany/transactions/{w['tid']}/price", headers=H, json={'unit_costs': {w['item']: 120}, 'pricing_date': '2026-09-26'})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p['lines'][0]['unit_price'] == 132.0 and p['taxable_value'] == 5280.0
    assert p['supply_type'] == 'INTRA_STATE' and p['cgst'] == 132.0 and p['sgst'] == 132.0 and p['total_value'] == 5544.0
    # legacy one-step post is refused once priced
    assert c.post(f"/v90fm/intercompany/transactions/{w['tid']}/post", headers=H, json={'evidence_note': 'x'}).status_code == 409
    # 3. X dispatches → invoice, stock leaves X, nothing at Y yet
    r = c.post(f"/v90gx/intercompany/transactions/{w['tid']}/dispatch", headers=H, json={'evidence_note': 'Truck MH12 left factory'})
    assert r.status_code == 200, r.text
    d = r.json()
    fy = financial_year(datetime.now(timezone.utc).date())[1]
    assert d['status'] == 'IN_TRANSIT' and d['invoice_no'] == f'XMFI/{fy}/0001'
    assert qty(w['o'], w['x'], w['item']) == 60.0 and qty(w['o'], w['y'], w['item']) == 0.0
    assert 'XMFI/' in c.get(d['print_url'], headers=H).text
    # 4. Y receives 38 kg: reason required, then only 38 posted
    with engine.connect() as conn:
        line_id = conn.execute(text('SELECT line_id FROM intercompany_transaction_line WHERE transaction_id=:t'), {'t': w['tid']}).scalar()
    body = {'evidence_note': 'GRN at depot', 'lines': [{'line_id': line_id, 'received_qty': 38}]}
    assert c.post(f"/v90gx/intercompany/transactions/{w['tid']}/receive", headers=H, json=body).status_code == 422
    r = c.post(f"/v90gx/intercompany/transactions/{w['tid']}/receive", headers=H, json={**body, 'shortage_reason': '2 kg damaged in transit'})
    assert r.status_code == 200, r.text
    assert r.json()['shortage_qty'] == 2.0 and r.json()['shortage_value'] == 264.0
    assert qty(w['o'], w['y'], w['item']) == 38.0
    with engine.connect() as conn:  # inventory_stock_balance kept in step at Y (app/stock_balance.py)
        assert float(conn.execute(text('SELECT available_qty FROM inventory_stock_balance WHERE entity_id=:e AND item_master_id=:i'), {'e': w['y'], 'i': w['item']}).scalar()) == 38.0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM intercompany_elimination WHERE transaction_id=:t"), {'t': w['tid']}).scalar() == 'OPEN'
    # 5. Y pays X
    iid = d['ic_invoice_id']
    assert c.post(f'/v90gx/intercompany/invoices/{iid}/settlements', headers=H, json={'amount': 9999, 'mode': 'BANK', 'reference_no': 'UTR1'}).status_code == 409
    r = c.post(f'/v90gx/intercompany/invoices/{iid}/settlements', headers=H, json={'amount': 3000, 'mode': 'BANK', 'reference_no': 'UTR1'})
    assert r.json()['status'] == 'PARTIALLY_SETTLED' and r.json()['outstanding'] == 2544.0
    bal = c.get('/v90gx/intercompany/balances', headers=H, params={'organization_id': w['o']}).json()['balances'][0]
    assert bal['seller_receivable'] == 2544.0 and bal['buyer_payable'] == 2544.0
    r = c.post(f'/v90gx/intercompany/invoices/{iid}/settlements', headers=H, json={'amount': 2544, 'mode': 'UPI', 'reference_no': 'UTR2'})
    assert r.json()['status'] == 'SETTLED' and r.json()['outstanding'] == 0.0


def test_dispatch_requires_pricing_and_stock():
    c, w = world()
    assert c.post(f"/v90gx/intercompany/transactions/{w['tid']}/dispatch", headers=H, json={'evidence_note': 'x1'}).status_code == 409
    c.post('/v90gx/intercompany/policies', headers=H, json={'organization_id': w['o'], 'from_entity_id': w['x'], 'to_entity_id': w['y'], 'item_master_id': w['item'], 'method': 'FIXED_PRICE',
           'fixed_price': 3000, 'gst_rate': 5, 'effective_from': '2026-04-01', 'agreement_ref': 'Price list 2026'})
    r = c.post(f"/v90gx/intercompany/transactions/{w['tid']}/price", headers=H, json={})
    assert r.status_code == 200 and r.json()['total_value'] == 126000.0
    r = c.post(f"/v90gx/intercompany/transactions/{w['tid']}/dispatch", headers=H, json={'evidence_note': 'x1'})
    assert r.status_code == 409 and 'e-way' in r.text   # 1,26,000 > ₹1,00,000 intra-MH
    r = c.post(f"/v90gx/intercompany/transactions/{w['tid']}/dispatch", headers=H, json={'evidence_note': 'x1', 'eway_bill_no': '331000123456'})
    assert r.status_code == 200, r.text
