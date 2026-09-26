# FILE PATH: tests/test_v90gx_company_gst_invoicing.py
# ─── V90.gx Company Profile & GST Invoicing tests v1.0 (Session CS2 — new) ─
# [Session CS2] FEATURE — covers entity profile validation, FY invoice numbering at dispatch, CGST/SGST Fixtures use TRUE (not 1) for BOOLEAN columns so the file also runs on PostgreSQL.
# vs IGST split, e-way threshold gate, advance-payment gate, printable invoice and the multi-line
# dispatch fix in app/v90ag_dispatch_execution.py. Runs on the in-memory SQLite test engine.
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.__main__ import app, engine
from app.identity import create_user
from app.v90gx_company_gst_invoicing import amount_in_words, financial_year, gstin_check_digit_ok

X_GSTIN = '27AAACC1234D1ZC'   # valid check digit, Maharashtra
KA_GSTIN = '29AABCR9999K1Z9'  # valid check digit, Karnataka


def admin():
    r = TestClient(app).post('/auth/login', json={'username': 'erpadmin', 'password': 'change-me'})
    assert r.status_code == 200, r.text
    return TestClient(app, headers={'Authorization': f"Bearer {r.json()['access_token']}"})


def setup_entity(prefix='CPE', state='27', gstin=X_GSTIN):
    org, ent, loc, wh = [str(uuid4()) for _ in range(4)]
    uid = str(uuid4()); uname = f'gx_{uid[:8]}'
    create_user(engine, uid, uname, 'pw', 'GX Tester', 'manager')
    with engine.begin() as c:
        c.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES(:i,:c,'GX','legal_entity')"), {'i': ent, 'c': ent[:8]})
        c.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type) VALUES(:i,:e,:c,'GX','site')"), {'i': loc, 'e': ent, 'c': loc[:8]})
        c.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type,active) VALUES(:i,:e,:l,:c,'GX','general',TRUE)"), {'i': wh, 'e': ent, 'l': loc, 'c': wh[:8]})
        c.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"), {'u': uid, 'e': ent})
        c.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"), {'u': uid, 'l': loc})
    a = admin()
    r = a.put(f'/v90gx/entities/{ent}/profile', json={
        'organization_id': org, 'legal_name': 'Chavan Patil Enterprises Pvt. Ltd.', 'trade_name': "Dip's-t-Chips",
        'business_role': 'SALES_MARKETING', 'gstin': gstin, 'fssai_license_no': '11526999000123', 'fssai_valid_to': '2027-03-31',
        'address_line1': 'Plot 1, MIDC', 'city': 'Pune', 'state_code': state, 'pincode': '411001',
        'bank_name': 'Test Bank', 'bank_account_no': '000111222333', 'bank_ifsc': 'SBIN0000001', 'invoice_prefix': prefix})
    assert r.status_code == 200, r.text
    tok = TestClient(app).post('/auth/login', json={'username': uname, 'password': 'pw'}).json()['access_token']
    return {'org': org, 'ent': ent, 'loc': loc, 'wh': wh, 'uid': uid, 'client': TestClient(app, headers={'Authorization': f'Bearer {tok}'}), 'admin': a}


def make_order(s, lines, customer_data='{}'):
    """lines: list of (qty, rate, gst_rate). Creates an APPROVED order with picked stock ready to dispatch."""
    so, cust, pick = str(uuid4()), str(uuid4()), str(uuid4())
    sub = sum(q * r for q, r, _ in lines); gst = sum(round(q * r * g / 100, 2) for q, r, g in lines)
    with engine.begin() as c:
        c.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:id,:o,'CUSTOMER',:e,TRUE,:d)"), {'id': cust, 'o': s['org'], 'e': s['ent'], 'd': customer_data})
        c.execute(text("INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) VALUES(:id,:o,:e,:l,:w,:c,:no,'APPROVED','PASS','PASS','READY',:sub,0,:sub,:g,:t,:u)"),
                  {'id': so, 'o': s['org'], 'e': s['ent'], 'l': s['loc'], 'w': s['wh'], 'c': cust, 'no': 'SO-' + so[:8], 'sub': sub, 'g': gst, 't': sub + gst, 'u': s['uid']})
        c.execute(text("INSERT INTO dispatch_pick_lists(pick_list_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,status,created_by) VALUES(:p,:o,:e,:l,:w,:so,'PICKED',:u)"), {'p': pick, 'o': s['org'], 'e': s['ent'], 'l': s['loc'], 'w': s['wh'], 'so': so, 'u': s['uid']})
        for q, r, g in lines:
            sku, lot, alloc, sl = [str(uuid4()) for _ in range(4)]
            c.execute(text("INSERT INTO master_record(master_id,organization_id,master_type,entity_id,active,data) VALUES(:id,:o,'SKU',:e,TRUE,:d)"), {'id': sku, 'o': s['org'], 'e': s['ent'], 'd': '{"name":"Special Farsan 500 g","hsn_code":"21069099","uom":"kg"}'})
            c.execute(text("INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price,discount_pct,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) VALUES(:id,:o,:s,:q,:r,0,0,:t,:g,:ga,:lt)"),
                      {'id': sl, 'o': so, 's': sku, 'q': q, 'r': r, 't': q * r, 'g': g, 'ga': round(q * r * g / 100, 2), 'lt': q * r + round(q * r * g / 100, 2)})
            c.execute(text("INSERT INTO packed_fg_lot(packed_fg_lot_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,source_fg_lot_id,sku_id,lot_code,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,created_by) VALUES(:id,:org,:e,:l,:w,:pr,:src,:s,:lc,1,:q,:q,'kg','2026-09-01',NULL,'AVAILABLE','RELEASED',:u)"),
                      {'id': lot, 'org': s['org'], 'e': s['ent'], 'l': s['loc'], 'w': s['wh'], 'pr': str(uuid4()), 'src': str(uuid4()), 's': sku, 'lc': 'L' + lot[:6], 'q': q, 'u': s['uid']})
            c.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty) VALUES(:o,:e,:l,:w,:s,'kg',:q)"), {'o': s['org'], 'e': s['ent'], 'l': s['loc'], 'w': s['wh'], 's': sku, 'q': q})
            c.execute(text("INSERT INTO sales_order_allocations(sales_order_allocation_id,sales_order_id,sales_order_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,fg_allocation_group_id,status,created_by) VALUES(:a,:o,:sl,:org,:e,:l,:w,:s,:lot,:lc,:q,:g,'ALLOCATED',:u)"),
                      {'a': alloc, 'o': so, 'sl': sl, 'org': s['org'], 'e': s['ent'], 'l': s['loc'], 'w': s['wh'], 's': sku, 'lot': lot, 'lc': 'L' + lot[:6], 'q': q, 'g': str(uuid4()), 'u': s['uid']})
            c.execute(text("INSERT INTO dispatch_pick_lines(pick_line_id,pick_list_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,allocated_qty,picked_qty,status) VALUES(:id,:p,:sl,:a,:s,:lot,:lc,:q,:q,'PICKED')"),
                      {'id': str(uuid4()), 'p': pick, 'sl': sl, 'a': alloc, 's': sku, 'lot': lot, 'lc': 'L' + lot[:6], 'q': q})
    return so, cust


def test_helpers_gstin_fy_words():
    assert gstin_check_digit_ok('27AAPFU0939F1ZV')
    assert not gstin_check_digit_ok('27AAPFU0939F1ZA')
    assert financial_year(date(2026, 9, 26)) == ('2026-27', '26-27')
    assert financial_year(date(2027, 3, 31)) == ('2026-27', '26-27')
    assert financial_year(date(2027, 4, 1)) == ('2027-28', '27-28')
    assert amount_in_words(112345.5) == 'Rupees One Lakh Twelve Thousand Three Hundred Forty Five and Fifty Paise Only'


def test_profile_validation_rejects_bad_ids():
    s = setup_entity(prefix='VAL')
    a = s['admin']
    base = {'organization_id': s['org'], 'legal_name': 'X Mfg', 'business_role': 'MANUFACTURER', 'address_line1': 'Gat 12', 'city': 'Pune', 'state_code': '27', 'pincode': '411001'}
    assert a.put(f"/v90gx/entities/{s['ent']}/profile", json={**base, 'gstin': '27AAACC1234D1ZZ'}).status_code == 422  # bad check digit
    assert a.put(f"/v90gx/entities/{s['ent']}/profile", json={**base, 'gstin': KA_GSTIN}).status_code == 422          # state mismatch
    assert a.put(f"/v90gx/entities/{s['ent']}/profile", json={**base, 'fssai_license_no': '123'}).status_code == 422
    assert a.put(f"/v90gx/entities/{s['ent']}/profile", json={**base, 'invoice_prefix': 'TOOLONGX'}).status_code == 422
    r = a.put(f"/v90gx/entities/{s['ent']}/profile", json={**base, 'gstin': X_GSTIN})
    assert r.status_code == 200 and r.json()['pan'] == 'AAACC1234D'
    prof = a.get(f"/v90gx/entities/{s['ent']}/profile").json()['profile']
    assert prof['business_role'] == 'MANUFACTURER' and prof['state_name'] == 'Maharashtra'


def test_multi_line_dispatch_auto_invoice_number_and_intra_state_split():
    s = setup_entity(prefix='CPE')
    so, _ = make_order(s, [(10, 100, 5), (4, 250, 5)], '{"name":"Local Retailer","state_code":"27"}')
    r = s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6]})
    assert r.status_code == 200, r.text
    fy_short = financial_year(datetime.now(timezone.utc).date())[1]
    assert r.json()['invoice_no'] == f'CPE/{fy_short}/0001'
    g = r.json()['gst']
    assert g['supply_type'] == 'INTRA_STATE' and g['cgst'] == 50.0 and g['sgst'] == 50.0 and g['igst'] == 0.0
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM sales_invoice_lines WHERE invoice_id=:i'), {'i': r.json()['invoice_id']}).scalar() == 2
    so2, _ = make_order(s, [(1, 100, 5)])
    r2 = s['client'].post(f'/v90ag/sales/orders/{so2}/dispatch', json={'dispatch_no': 'D-' + so2[:6]})
    assert r2.json()['invoice_no'] == f'CPE/{fy_short}/0002'
    html = s['client'].get(r.json()['print_url'])
    assert html.status_code == 200
    assert f'CPE/{fy_short}/0001' in html.text and X_GSTIN in html.text and 'Rupees Two Thousand One Hundred Only' in html.text and 'CGST' in html.text


def test_inter_state_customer_gets_igst():
    s = setup_entity(prefix='IGS')
    so, _ = make_order(s, [(10, 100, 5)], '{"name":"Bengaluru Distributor","gstin":"%s"}' % KA_GSTIN)
    r = s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6]})
    assert r.status_code == 200, r.text
    g = r.json()['gst']
    assert g['supply_type'] == 'INTER_STATE' and g['igst'] == 50.0 and g['cgst'] == 0.0


def test_eway_threshold_gate():
    s = setup_entity(prefix='EWB')
    so, _ = make_order(s, [(1000, 100, 5)], '{"name":"Local SS","state_code":"27"}')  # 1,05,000 intra-MH > 1,00,000
    r = s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6]})
    assert r.status_code == 409 and 'e-way' in str(r.json()['detail'])
    r = s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6], 'eway_bill_no': '123456789012', 'vehicle_no': 'MH12AB1234'})
    assert r.status_code == 200, r.text
    assert r.json()['gst']['eway_required'] is True
    so2, _ = make_order(s, [(900, 100, 5)], '{"name":"Local SS","state_code":"27"}')  # 94,500 intra-MH: not required
    assert s['client'].post(f'/v90ag/sales/orders/{so2}/dispatch', json={'dispatch_no': 'D-' + so2[:6]}).status_code == 200
    so3, _ = make_order(s, [(500, 100, 5)], '{"name":"Goa SS","state_code":"30"}')  # 52,500 inter-state > 50,000
    assert s['client'].post(f'/v90ag/sales/orders/{so3}/dispatch', json={'dispatch_no': 'D-' + so3[:6]}).status_code == 409


def test_advance_terms_block_dispatch_until_paid():
    s = setup_entity(prefix='ADV')
    so, cust = make_order(s, [(10, 100, 5)], '{"name":"Super Stockist","state_code":"27"}')
    r = s['client'].put(f'/v90gx/customers/{cust}/payment-terms', json={'organization_id': s['org'], 'customer_id': cust, 'terms_type': 'ADVANCE', 'advance_pct': 50, 'balance_days': 7})
    assert r.status_code == 200, r.text
    r = s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6]})
    assert r.status_code == 409 and r.json()['detail']['advance_required'] == 525.0
    r = s['client'].post(f'/v90gx/sales-orders/{so}/advances', json={'amount': 525, 'mode': 'UPI', 'reference_no': 'UTR123'})
    assert r.status_code == 200 and r.json()['dispatch_allowed_by_terms'] is True
    assert s['client'].post(f'/v90gx/sales-orders/{so}/advances', json={'amount': 1, 'mode': 'UPI', 'reference_no': 'UTR123'}).status_code == 409
    assert s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6]}).status_code == 200


def test_manual_invoice_number_must_fit_gst_limit():
    s = setup_entity(prefix='MAN')
    so, _ = make_order(s, [(1, 100, 5)])
    r = s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6], 'invoice_no': 'INV_2026#1'})
    assert r.status_code == 422


def test_record_eway_and_einvoice_after_dispatch():
    s = setup_entity(prefix='REC')
    so, _ = make_order(s, [(2, 100, 5)])
    inv = s['client'].post(f'/v90ag/sales/orders/{so}/dispatch', json={'dispatch_no': 'D-' + so[:6]}).json()['invoice_id']
    assert s['client'].post(f'/v90gx/sales-invoices/{inv}/eway', json={'eway_bill_no': '12345'}).status_code == 422
    assert s['client'].post(f'/v90gx/sales-invoices/{inv}/eway', json={'eway_bill_no': '123456789012', 'vehicle_no': 'MH14XY0001'}).status_code == 200
    r = s['admin'].post(f'/v90gx/sales-invoices/{inv}/einvoice', json={'irn': 'a' * 64, 'ack_no': '112010000000001', 'ack_date': '2026-09-26'})
    assert r.status_code == 200 and r.json()['einvoice_status'] == 'GENERATED'
    g = s['client'].get(f'/v90gx/sales-invoices/{inv}/gst').json()['gst']
    assert g['eway_bill_no'] == '123456789012' and g['irn'] == 'a' * 64
    assert 'IRN:' in s['client'].get(f'/v90gx/sales-invoices/{inv}/print').text
