# FILE PATH: app/v90gx_company_gst_invoicing.py
# ─── Company Profile & GST Invoicing v1.0 (Session CS2 — X/Y legal details, FY invoice series, printable GST invoice, e-way rule, advance terms) ─
#
# [Session CS2] FEATURE — ENTITY LEGAL DETAILS, GST TAX-INVOICE NUMBERING/PRINT, E-WAY THRESHOLD AND ADVANCE-PAYMENT TERMS WERE MISSING.
# Confirmed this session by reading app/org_structure.py (erp_entities holds only code/name/type),
# app/v90ag_dispatch_execution.py (invoice_no typed by hand, eway_bill_no free text, no print) and
# the Wireframes S02 / Functional Spec BR-series (entity GSTIN, PAN, FSSAI, address, bank, invoice
# prefix; super-stockist 50% advance). No live GST portal/IRP was available; e-invoice IRN is stored
# when supplied but is NOT generated here (einvoice_status stays PENDING/NOT_APPLICABLE).
#
# THE FIX (new tables — runtime schema here, PostgreSQL migration 274_v90gx_company_gst_invoicing.sql):
#   - erp_entity_profile: legal/trade name, role (MANUFACTURER = company X, SALES_MARKETING = company Y),
#     GSTIN (format + check digit + state/PAN consistency), PAN, CIN, FSSAI licence (14 digits) and
#     validity, address, state code, bank/IFSC/UPI, invoice prefix.
#   - erp_document_series: financial-year (Apr–Mar) numbering per entity and document type, atomic
#     allocation, GST rule "max 16 characters, only A–Z 0–9 / -" enforced. Format PREFIX/YY-YY/NNNN.
#   - sales_invoice_gst_detail: seller/buyer GSTIN & state, place of supply, CGST/SGST vs IGST split,
#     e-way requirement, e-way number, e-invoice (IRN) placeholder, FSSAI no., amount in words.
#   - erp_eway_rule: consignment-value thresholds per seller state (default ₹50,000; Maharashtra
#     intra-state ₹1,00,000, inter-state ₹50,000) — configurable, not hard-coded in the gate.
#   - customer_payment_terms + sales_order_advance: ADVANCE terms (e.g. super-stockist 50%, balance
#     in 7 days) and advance receipts; dispatch is blocked until the advance is received.
# Helper functions (allocate_document_number, prepare_dispatch_invoice, finalize_invoice_gst) are
# used by app/v90ag_dispatch_execution.py. NOT touched: sales order pricing, stock ledger, returns,
# GST return modules (v90by/v90bz/…), Tally bridge.
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .access_scope import is_entity_allowed
from .auth import authenticate
from .identity import permissions_for_user

PERMS = [
    ('company.profile.view', 'View company / entity legal profile'),
    ('company.profile.manage', 'Manage company / entity legal profile and document series'),
    ('gst.invoice.view', 'View and print GST tax invoices'),
    ('gst.invoice.manage', 'Finalize GST invoice details, e-way bill and e-invoice data'),
    ('sales.terms.manage', 'Manage customer payment terms and record sales-order advances'),
]
ROLE_GRANTS = {
    'manager': ['company.profile.view', 'gst.invoice.view', 'gst.invoice.manage', 'sales.terms.manage'],
    'accounts': ['company.profile.view', 'gst.invoice.view', 'gst.invoice.manage', 'sales.terms.manage'],
    'dispatch': ['company.profile.view', 'gst.invoice.view', 'gst.invoice.manage'],
    'sales': ['company.profile.view', 'gst.invoice.view'],
    'salesperson': ['gst.invoice.view'],
}

GST_STATE_CODES = {
    '01': 'Jammu and Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh', '05': 'Uttarakhand',
    '06': 'Haryana', '07': 'Delhi', '08': 'Rajasthan', '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim',
    '12': 'Arunachal Pradesh', '13': 'Nagaland', '14': 'Manipur', '15': 'Mizoram', '16': 'Tripura', '17': 'Meghalaya',
    '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand', '21': 'Odisha', '22': 'Chhattisgarh', '23': 'Madhya Pradesh',
    '24': 'Gujarat', '26': 'Dadra and Nagar Haveli and Daman and Diu', '27': 'Maharashtra', '29': 'Karnataka',
    '30': 'Goa', '31': 'Lakshadweep', '32': 'Kerala', '33': 'Tamil Nadu', '34': 'Puducherry',
    '35': 'Andaman and Nicobar Islands', '36': 'Telangana', '37': 'Andhra Pradesh', '38': 'Ladakh', '97': 'Other Territory',
}
GSTIN_RE = re.compile(r'^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')
PAN_RE = re.compile(r'^[A-Z]{5}\d{4}[A-Z]$')
FSSAI_RE = re.compile(r'^\d{14}$')
IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
PIN_RE = re.compile(r'^\d{6}$')
DOC_NO_RE = re.compile(r'^[A-Za-z0-9/-]{1,16}$')
PREFIX_RE = re.compile(r'^[A-Za-z0-9]{1,6}$')
DOC_TYPES = ('TAX_INVOICE', 'IC_INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE', 'DELIVERY_CHALLAN', 'PURCHASE_RETURN')
DEFAULT_EWAY_RULES = [('*', 50000, 50000), ('27', 100000, 50000)]
_GSTIN_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def gstin_check_digit_ok(gstin: str) -> bool:
    """Official GSTIN mod-36 check digit (15th character)."""
    total = 0
    for i, ch in enumerate(gstin[:14]):
        v = _GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36] == gstin[14]


def validate_gstin(gstin: str, state_code: str | None = None, pan: str | None = None) -> str:
    g = (gstin or '').strip().upper()
    if not GSTIN_RE.match(g):
        raise HTTPException(422, 'GSTIN format is invalid (expected 15 characters, e.g. 27ABCDE1234F1Z5)')
    if g[:2] not in GST_STATE_CODES:
        raise HTTPException(422, 'GSTIN state code is not a valid GST state code')
    if not gstin_check_digit_ok(g):
        raise HTTPException(422, 'GSTIN check digit is invalid')
    if state_code and g[:2] != state_code:
        raise HTTPException(422, 'GSTIN state code does not match the entity state_code')
    if pan and g[2:12] != pan.strip().upper():
        raise HTTPException(422, 'GSTIN does not contain the entity PAN')
    return g


def financial_year(d: date) -> tuple[str, str]:
    """Return (long, short) Indian FY codes, e.g. ('2026-27', '26-27')."""
    start = d.year if d.month >= 4 else d.year - 1
    return f'{start}-{str(start + 1)[2:]}', f'{str(start)[2:]}-{str(start + 1)[2:]}'


def _parse_date(v, default: date | None = None) -> date:
    if not v:
        return default or datetime.now(timezone.utc).date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as exc:
        raise HTTPException(422, 'date must be YYYY-MM-DD') from exc


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve',
         'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else ''))


def _three(n: int) -> str:
    h, r = divmod(n, 100)
    return ((_ONES[h] + ' Hundred') if h else '') + ((' ' if h and r else '') + _two(r) if r else '')


def amount_in_words(amount) -> str:
    """Indian numbering (lakh/crore): 112345.50 → 'Rupees One Lakh Twelve Thousand Three Hundred Forty Five and Fifty Paise Only'."""
    a = _d(amount)
    rupees = int(a)
    paise = int((a - rupees) * 100)
    parts = []
    crore, rupees = divmod(rupees, 10_000_000)
    lakh, rupees = divmod(rupees, 100_000)
    thousand, rupees = divmod(rupees, 1000)
    if crore:
        parts.append((amount_in_words(crore).replace('Rupees ', '').replace(' Only', '')) + ' Crore')
    if lakh:
        parts.append(_two(lakh) + ' Lakh')
    if thousand:
        parts.append(_two(thousand) + ' Thousand')
    if rupees:
        parts.append(_three(rupees))
    if not parts and paise:
        return f'{_two(paise)} Paise Only'
    words = ' '.join(parts) or 'Zero'
    return f'Rupees {words}' + (f' and {_two(paise)} Paise' if paise else '') + ' Only'


class ProfileIn(BaseModel):
    organization_id: str = Field(min_length=1, max_length=64)
    legal_name: str = Field(min_length=2, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    business_role: str = Field(pattern='^(MANUFACTURER|SALES_MARKETING|BOTH)$')
    gstin: str | None = None
    pan: str | None = None
    cin: str | None = Field(default=None, max_length=30)
    fssai_license_no: str | None = None
    fssai_valid_to: str | None = None
    address_line1: str = Field(min_length=2, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=2, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    state_code: str = Field(pattern=r'^\d{2}$')
    pincode: str
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_no: str | None = Field(default=None, max_length=30)
    bank_ifsc: str | None = None
    bank_branch: str | None = Field(default=None, max_length=120)
    upi_id: str | None = Field(default=None, max_length=80)
    invoice_prefix: str | None = None
    einvoice_applicable: bool = False


class SeriesIn(BaseModel):
    entity_id: str
    doc_type: str = Field(pattern='^(' + '|'.join(DOC_TYPES) + ')$')
    prefix: str
    fy_code: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}$')
    next_no: int = Field(default=1, ge=1)
    pad_width: int = Field(default=4, ge=1, le=6)


class EwayIn(BaseModel):
    eway_bill_no: str = Field(pattern=r'^\d{12}$')
    eway_valid_upto: str | None = None
    vehicle_no: str | None = Field(default=None, max_length=20)


class EinvoiceIn(BaseModel):
    irn: str = Field(min_length=64, max_length=64)
    ack_no: str = Field(min_length=1, max_length=30)
    ack_date: str
    signed_qr: str | None = Field(default=None, max_length=4000)


class TermsIn(BaseModel):
    organization_id: str
    customer_id: str
    terms_type: str = Field(pattern='^(STANDARD|ADVANCE)$')
    advance_pct: float = Field(default=0, ge=0, le=100)
    balance_days: int = Field(default=0, ge=0, le=365)
    notes: str | None = Field(default=None, max_length=500)


class AdvanceIn(BaseModel):
    amount: float = Field(gt=0)
    mode: str = Field(pattern='^(BANK|UPI|CASH|CHEQUE)$')
    reference_no: str = Field(min_length=1, max_length=80)
    received_on: str | None = None


def ensure_v90gx_company_schema(e: Engine) -> None:
    stmts = [
        '''CREATE TABLE IF NOT EXISTS erp_entity_profile(entity_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,legal_name TEXT NOT NULL,trade_name TEXT NULL,business_role TEXT NOT NULL,gstin TEXT NULL,pan TEXT NULL,cin TEXT NULL,fssai_license_no TEXT NULL,fssai_valid_to DATE NULL,address_line1 TEXT NOT NULL,address_line2 TEXT NULL,city TEXT NOT NULL,district TEXT NULL,state_code TEXT NOT NULL,state_name TEXT NOT NULL,pincode TEXT NOT NULL,phone TEXT NULL,email TEXT NULL,bank_name TEXT NULL,bank_account_no TEXT NULL,bank_ifsc TEXT NULL,bank_branch TEXT NULL,upi_id TEXT NULL,invoice_prefix TEXT NULL,einvoice_applicable INTEGER NOT NULL DEFAULT 0,updated_by TEXT NOT NULL,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS erp_document_series(series_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,doc_type TEXT NOT NULL,fy_code TEXT NOT NULL,prefix TEXT NOT NULL,next_no INTEGER NOT NULL DEFAULT 1,pad_width INTEGER NOT NULL DEFAULT 4,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(entity_id,doc_type,fy_code))''',
        '''CREATE TABLE IF NOT EXISTS erp_document_number_log(log_id TEXT PRIMARY KEY,series_id TEXT NOT NULL,document_no TEXT NOT NULL,doc_date DATE NOT NULL,reference_type TEXT NULL,reference_id TEXT NULL,allocated_by TEXT NOT NULL,allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(series_id,document_no))''',
        '''CREATE TABLE IF NOT EXISTS sales_invoice_gst_detail(invoice_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,seller_entity_id TEXT NOT NULL,invoice_date DATE NOT NULL,seller_gstin TEXT NULL,seller_state_code TEXT NULL,buyer_customer_id TEXT NULL,buyer_name TEXT NULL,buyer_gstin TEXT NULL,buyer_state_code TEXT NULL,place_of_supply TEXT NULL,supply_type TEXT NOT NULL,taxable_value NUMERIC NOT NULL DEFAULT 0,cgst_amount NUMERIC NOT NULL DEFAULT 0,sgst_amount NUMERIC NOT NULL DEFAULT 0,igst_amount NUMERIC NOT NULL DEFAULT 0,invoice_value NUMERIC NOT NULL DEFAULT 0,eway_required INTEGER NOT NULL DEFAULT 0,eway_threshold NUMERIC NOT NULL DEFAULT 0,eway_bill_no TEXT NULL,eway_valid_upto TEXT NULL,vehicle_no TEXT NULL,einvoice_status TEXT NOT NULL DEFAULT 'NOT_APPLICABLE',irn TEXT NULL,ack_no TEXT NULL,ack_date TEXT NULL,signed_qr TEXT NULL,fssai_license_no TEXT NULL,amount_in_words TEXT NOT NULL,finalized_by TEXT NOT NULL,finalized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS erp_eway_rule(rule_id TEXT PRIMARY KEY,seller_state_code TEXT NOT NULL UNIQUE,intra_state_threshold NUMERIC NOT NULL,inter_state_threshold NUMERIC NOT NULL,notes TEXT NULL,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS customer_payment_terms(customer_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,terms_type TEXT NOT NULL DEFAULT 'STANDARD',advance_pct NUMERIC NOT NULL DEFAULT 0,balance_days INTEGER NOT NULL DEFAULT 0,notes TEXT NULL,updated_by TEXT NOT NULL,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS sales_order_advance(advance_id TEXT PRIMARY KEY,sales_order_id TEXT NOT NULL,organization_id TEXT NOT NULL,amount NUMERIC NOT NULL,mode TEXT NOT NULL,reference_no TEXT NOT NULL,received_on DATE NOT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(sales_order_id,reference_no))''',
        'CREATE INDEX IF NOT EXISTS ix_entity_profile_org ON erp_entity_profile(organization_id,business_role)',
        'CREATE INDEX IF NOT EXISTS ix_invoice_gst_scope ON sales_invoice_gst_detail(organization_id,seller_entity_id,invoice_date)',
        'CREATE INDEX IF NOT EXISTS ix_so_advance_order ON sales_order_advance(sales_order_id)',
    ]
    with e.begin() as c:
        for s in stmts:
            c.execute(text(s))
        for state, intra, inter in DEFAULT_EWAY_RULES:
            c.execute(text('INSERT INTO erp_eway_rule(rule_id,seller_state_code,intra_state_threshold,inter_state_threshold,notes) VALUES(:i,:s,:a,:b,:n) ON CONFLICT(seller_state_code) DO NOTHING'),
                      {'i': str(uuid4()), 's': state, 'a': intra, 'b': inter, 'n': 'Seeded default (Session CS2); verify against current state notification before go-live'})
        for p, n in PERMS:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'p': p})
        for role, ps in ROLE_GRANTS.items():
            for p in ps:
                c.execute(text('INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING'), {'r': role, 'p': p})


def _user(e: Engine, r: Request, perm: str):
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if perm not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _entity_scope(e: Engine, user_id: str, entity_id: str) -> None:
    ps = permissions_for_user(e, user_id)
    if 'admin.users' in ps or 'security.rbac.manage' in ps:
        return
    if not is_entity_allowed(e, user_id, entity_id):
        raise HTTPException(403, 'entity access denied')


def get_profile(e: Engine, entity_id: str) -> dict | None:
    with e.connect() as c:
        row = c.execute(text('SELECT * FROM erp_entity_profile WHERE entity_id=:e'), {'e': str(entity_id)}).mappings().first()
    return dict(row) if row else None


def allocate_document_number(e: Engine, *, entity_id: str, doc_type: str, doc_date: date, user_id: str,
                             reference_type: str | None = None, reference_id: str | None = None, conn=None) -> str:
    """Allocate the next FY document number. Auto-creates the series from the entity invoice_prefix."""
    fy_long, fy_short = financial_year(doc_date)

    def _run(c) -> str:
        s = c.execute(text('SELECT * FROM erp_document_series WHERE entity_id=:e AND doc_type=:t AND fy_code=:f'), {'e': entity_id, 't': doc_type, 'f': fy_long}).mappings().first()
        if not s:
            prof = c.execute(text('SELECT organization_id,invoice_prefix FROM erp_entity_profile WHERE entity_id=:e'), {'e': entity_id}).mappings().first()
            if not prof or not prof['invoice_prefix']:
                raise HTTPException(409, f'no {doc_type} number series for this entity and FY {fy_long}: set the entity invoice_prefix or create a document series')
            prefix = prof['invoice_prefix'] + ({'IC_INVOICE': 'I', 'CREDIT_NOTE': 'C', 'DEBIT_NOTE': 'D', 'DELIVERY_CHALLAN': 'DC', 'PURCHASE_RETURN': 'PR'}.get(doc_type, ''))
            c.execute(text('INSERT INTO erp_document_series(series_id,organization_id,entity_id,doc_type,fy_code,prefix,next_no,pad_width,created_by) VALUES(:i,:o,:e,:t,:f,:p,1,4,:u) ON CONFLICT(entity_id,doc_type,fy_code) DO NOTHING'),
                      {'i': str(uuid4()), 'o': prof['organization_id'], 'e': entity_id, 't': doc_type, 'f': fy_long, 'p': prefix, 'u': user_id})
            s = c.execute(text('SELECT * FROM erp_document_series WHERE entity_id=:e AND doc_type=:t AND fy_code=:f'), {'e': entity_id, 't': doc_type, 'f': fy_long}).mappings().first()
        row = c.execute(text('UPDATE erp_document_series SET next_no=next_no+1 WHERE series_id=:s RETURNING next_no'), {'s': s['series_id']}).first()
        n = int(row[0]) - 1
        doc_no = f"{s['prefix']}/{fy_short}/{str(n).zfill(int(s['pad_width']))}"
        if not DOC_NO_RE.match(doc_no):
            raise HTTPException(409, f'document number {doc_no} breaks the GST rule (max 16 characters, A-Z 0-9 / -); shorten the prefix')
        c.execute(text('INSERT INTO erp_document_number_log(log_id,series_id,document_no,doc_date,reference_type,reference_id,allocated_by) VALUES(:i,:s,:n,:d,:rt,:ri,:u)'),
                  {'i': str(uuid4()), 's': s['series_id'], 'n': doc_no, 'd': doc_date.isoformat(), 'rt': reference_type, 'ri': reference_id, 'u': user_id})
        return doc_no

    if conn is not None:
        return _run(conn)
    with e.begin() as c:
        return _run(c)


def _customer_data(c, customer_id: str) -> dict:
    row = c.execute(text("SELECT data FROM master_record WHERE master_id=:i"), {'i': str(customer_id)}).first()
    if not row:
        return {}
    data = row[0]
    if isinstance(data, str):
        try:
            data = json.loads(data or '{}')
        except ValueError:
            data = {}
    return dict(data or {})


def _buyer_state(cust: dict, fallback: str | None) -> str | None:
    g = str(cust.get('gstin') or '').strip().upper()
    if len(g) >= 2 and g[:2].isdigit():
        return g[:2]
    sc = str(cust.get('state_code') or '').strip()
    return sc if re.fullmatch(r'\d{2}', sc) else fallback


def eway_threshold(c, seller_state: str | None, inter_state: bool) -> Decimal:
    row = c.execute(text('SELECT intra_state_threshold,inter_state_threshold FROM erp_eway_rule WHERE seller_state_code=:s'), {'s': seller_state or '*'}).first() \
        or c.execute(text("SELECT intra_state_threshold,inter_state_threshold FROM erp_eway_rule WHERE seller_state_code='*'")).first()
    if not row:
        return Decimal('50000')
    return _d(row[1] if inter_state else row[0])


def customer_terms(c, customer_id: str) -> dict | None:
    row = c.execute(text('SELECT * FROM customer_payment_terms WHERE customer_id=:c'), {'c': str(customer_id)}).mappings().first()
    return dict(row) if row else None


def prepare_dispatch_invoice(e: Engine, *, order: dict, user_id: str, invoice_no: str | None,
                             eway_bill_no: str | None, doc_date: date | None = None, conn=None) -> str:
    """Pre-posting gate used by V90.ag dispatch: advance terms, e-way threshold, FY invoice number.
    Pass the dispatch posting connection as `conn` so a failed posting does not consume a number."""
    doc_date = doc_date or datetime.now(timezone.utc).date()
    if conn is None:
        with e.begin() as c:
            return prepare_dispatch_invoice(e, order=order, user_id=user_id, invoice_no=invoice_no, eway_bill_no=eway_bill_no, doc_date=doc_date, conn=c)
    c = conn
    terms = customer_terms(c, order['customer_id'])
    if terms and terms['terms_type'] == 'ADVANCE' and _d(terms['advance_pct']) > 0:
        need = _d(_d(order['grand_total']) * _d(terms['advance_pct']) / 100)
        got = _d(c.execute(text('SELECT COALESCE(SUM(amount),0) FROM sales_order_advance WHERE sales_order_id=:s'), {'s': str(order['sales_order_id'])}).scalar())
        if got < need:
            raise HTTPException(409, {'message': 'advance payment required before dispatch', 'advance_required': float(need), 'advance_received': float(got)})
    prof = c.execute(text('SELECT state_code FROM erp_entity_profile WHERE entity_id=:e'), {'e': str(order['entity_id'])}).first()
    seller_state = prof[0] if prof else None
    buyer_state = _buyer_state(_customer_data(c, order['customer_id']), seller_state)
    inter = bool(seller_state and buyer_state and seller_state != buyer_state) or not seller_state
    limit = eway_threshold(c, seller_state, inter)
    if _d(order['grand_total']) > limit and not (eway_bill_no and re.fullmatch(r'\d{12}', eway_bill_no.strip())):
        raise HTTPException(409, {'message': 'e-way bill (12 digits) is required: consignment value exceeds threshold', 'consignment_value': float(_d(order['grand_total'])), 'threshold': float(limit)})
    if invoice_no:
        if not DOC_NO_RE.match(invoice_no):
            raise HTTPException(422, 'invoice number must be max 16 characters using only A-Z, 0-9, / and -')
        return invoice_no
    return allocate_document_number(e, entity_id=str(order['entity_id']), doc_type='TAX_INVOICE', doc_date=doc_date, user_id=user_id,
                                     reference_type='SALES_ORDER', reference_id=str(order['sales_order_id']), conn=c)


def finalize_invoice_gst(e: Engine, invoice_id: str, user_id: str, invoice_date: date | None = None,
                         eway_bill_no: str | None = None, vehicle_no: str | None = None) -> dict:
    """Compute and store the GST split / e-way / print data for a posted sales invoice (idempotent)."""
    with e.begin() as c:
        inv = c.execute(text('SELECT * FROM sales_invoices WHERE invoice_id=:i'), {'i': invoice_id}).mappings().first()
        if not inv:
            raise HTTPException(404, 'sales invoice not found')
        so = c.execute(text('SELECT customer_id FROM sales_orders WHERE sales_order_id=:s'), {'s': inv['sales_order_id']}).mappings().first()
        cust_id = so['customer_id'] if so else None
        cust = _customer_data(c, cust_id) if cust_id else {}
        prof = c.execute(text('SELECT * FROM erp_entity_profile WHERE entity_id=:e'), {'e': inv['entity_id']}).mappings().first()
        seller_state = prof['state_code'] if prof else None
        buyer_state = _buyer_state(cust, seller_state)
        inter = bool(seller_state and buyer_state and seller_state != buyer_state)
        gst = _d(inv['gst_total'])
        if inter:
            cg = sg = Decimal('0.00'); ig = gst
        else:
            cg = _d(gst / 2); sg = gst - cg; ig = Decimal('0.00')
        value = _d(inv['grand_total'])
        limit = eway_threshold(c, seller_state, inter)
        existing = c.execute(text('SELECT eway_bill_no,irn,ack_no,ack_date,signed_qr,einvoice_status,vehicle_no FROM sales_invoice_gst_detail WHERE invoice_id=:i'), {'i': invoice_id}).mappings().first()
        if not eway_bill_no:
            ew = c.execute(text('SELECT eway_bill_no,vehicle_no FROM dispatches WHERE dispatch_id=:d'), {'d': inv['dispatch_id']}).first()
            eway_bill_no = (existing and existing['eway_bill_no']) or (ew[0] if ew else None)
            vehicle_no = vehicle_no or (existing and existing['vehicle_no']) or (ew[1] if ew else None)
        einv = (existing and existing['einvoice_status']) or ('PENDING' if prof and int(prof['einvoice_applicable'] or 0) and cust.get('gstin') else 'NOT_APPLICABLE')
        idate = invoice_date or _parse_date(str(inv['created_at'])[:10])
        row = {
            'i': invoice_id, 'o': inv['organization_id'], 'se': inv['entity_id'], 'd': idate.isoformat(),
            'sg': prof['gstin'] if prof else None, 'ss': seller_state, 'bc': cust_id, 'bn': cust.get('name') or cust.get('legal_name'),
            'bg': (str(cust.get('gstin') or '').upper() or None), 'bs': buyer_state,
            'pos': f"{buyer_state}-{GST_STATE_CODES.get(buyer_state or '', '')}" if buyer_state else None,
            'st': 'INTER_STATE' if inter else 'INTRA_STATE', 'tv': float(_d(inv['taxable_value'])), 'cg': float(cg), 'sgst': float(sg), 'ig': float(ig),
            'iv': float(value), 'er': 1 if value > limit else 0, 'et': float(limit), 'ew': eway_bill_no, 'vn': vehicle_no, 'es': einv,
            'fs': prof['fssai_license_no'] if prof else None, 'w': amount_in_words(value), 'u': user_id,
        }
        c.execute(text('DELETE FROM sales_invoice_gst_detail WHERE invoice_id=:i'), {'i': invoice_id})
        c.execute(text('''INSERT INTO sales_invoice_gst_detail(invoice_id,organization_id,seller_entity_id,invoice_date,seller_gstin,seller_state_code,buyer_customer_id,buyer_name,buyer_gstin,buyer_state_code,place_of_supply,supply_type,taxable_value,cgst_amount,sgst_amount,igst_amount,invoice_value,eway_required,eway_threshold,eway_bill_no,vehicle_no,einvoice_status,irn,ack_no,ack_date,signed_qr,fssai_license_no,amount_in_words,finalized_by)
            VALUES(:i,:o,:se,:d,:sg,:ss,:bc,:bn,:bg,:bs,:pos,:st,:tv,:cg,:sgst,:ig,:iv,:er,:et,:ew,:vn,:es,:irn,:ack,:ackd,:qr,:fs,:w,:u)'''),
                  {**row, 'irn': existing['irn'] if existing else None, 'ack': existing['ack_no'] if existing else None,
                   'ackd': existing['ack_date'] if existing else None, 'qr': existing['signed_qr'] if existing else None})
    return {'invoice_id': invoice_id, 'supply_type': row['st'], 'cgst': row['cg'], 'sgst': row['sgst'], 'igst': row['ig'],
            'invoice_value': row['iv'], 'eway_required': bool(row['er']), 'eway_threshold': row['et'], 'amount_in_words': row['w'],
            'einvoice_status': einv}


def _sku_info(c, sku_id: str) -> dict:
    d = _customer_data(c, sku_id)
    return {'name': d.get('name') or d.get('sku_name') or d.get('code') or sku_id, 'hsn': d.get('hsn_code') or d.get('hsn') or '', 'uom': d.get('uom') or 'kg'}


def render_invoice_html(e: Engine, invoice_id: str) -> str:
    with e.connect() as c:
        inv = c.execute(text('SELECT * FROM sales_invoices WHERE invoice_id=:i'), {'i': invoice_id}).mappings().first()
        g = c.execute(text('SELECT * FROM sales_invoice_gst_detail WHERE invoice_id=:i'), {'i': invoice_id}).mappings().first()
        if not inv or not g:
            raise HTTPException(404, 'invoice not found or GST details not finalized')
        prof = c.execute(text('SELECT * FROM erp_entity_profile WHERE entity_id=:e'), {'e': inv['entity_id']}).mappings().first()
        lines = c.execute(text('SELECT * FROM sales_invoice_lines WHERE invoice_id=:i'), {'i': invoice_id}).mappings().all()
        cust = _customer_data(c, g['buyer_customer_id']) if g['buyer_customer_id'] else {}
        skus = {l['sku_id']: _sku_info(c, l['sku_id']) for l in lines}
    p = dict(prof) if prof else {}
    x = lambda v: escape(str(v if v is not None else ''))
    inter = g['supply_type'] == 'INTER_STATE'
    rows = ''.join(
        f"<tr><td>{i}</td><td>{x(skus[l['sku_id']]['name'])}</td><td>{x(skus[l['sku_id']]['hsn'])}</td><td class=r>{x(l['quantity'])} {x(skus[l['sku_id']]['uom'])}</td>"
        f"<td class=r>{_d(l['unit_price'])}</td><td class=r>{_d(l['discount_amount'])}</td><td class=r>{_d(l['taxable_amount'])}</td><td class=r>{x(l['gst_rate'])}%</td>"
        f"<td class=r>{_d(l['gst_amount'])}</td><td class=r>{_d(l['line_total'])}</td></tr>" for i, l in enumerate(lines, 1))
    tax_rows = (f"<tr><td>IGST</td><td class=r>{_d(g['igst_amount'])}</td></tr>" if inter else
                f"<tr><td>CGST</td><td class=r>{_d(g['cgst_amount'])}</td></tr><tr><td>SGST</td><td class=r>{_d(g['sgst_amount'])}</td></tr>")
    addr = lambda d: ', '.join(str(d.get(k)) for k in ('address_line1', 'address_line2', 'city', 'district', 'pincode') if d.get(k))
    irn = f"<p><b>IRN:</b> {x(g['irn'])} · Ack {x(g['ack_no'])} {x(g['ack_date'])}</p>" if g['irn'] else ''
    return f"""<!doctype html><html><head><meta charset=utf-8><title>Tax Invoice {x(inv['invoice_no'])}</title>
<style>body{{font:13px Arial,sans-serif;margin:24px;color:#111}}h1{{font-size:18px;text-align:center;margin:0 0 8px}}table{{width:100%;border-collapse:collapse;margin:8px 0}}td,th{{border:1px solid #444;padding:4px 6px;vertical-align:top}}th{{background:#eee}}.r{{text-align:right}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.box{{border:1px solid #444;padding:6px}}.muted{{color:#555}}@media print{{button{{display:none}}}}</style></head><body>
<button onclick="print()">Print</button><h1>TAX INVOICE</h1>
<div class=grid><div class=box><b>{x(p.get('legal_name') or 'Seller profile not set')}</b>{('<br>Trade name: ' + x(p.get('trade_name'))) if p.get('trade_name') else ''}<br>{x(addr(p))}<br>State: {x(p.get('state_name'))} ({x(p.get('state_code'))})<br>GSTIN: <b>{x(g['seller_gstin'])}</b> · PAN: {x(p.get('pan'))}<br>FSSAI Lic. No.: {x(g['fssai_license_no'])}{('<br>CIN: ' + x(p.get('cin'))) if p.get('cin') else ''}</div>
<div class=box>Invoice No.: <b>{x(inv['invoice_no'])}</b><br>Invoice Date: {x(g['invoice_date'])}<br>Place of Supply: {x(g['place_of_supply'])}<br>Supply: {x(g['supply_type'].replace('_', '-').title())}<br>E-way Bill: {x(g['eway_bill_no'] or ('REQUIRED' if g['eway_required'] else 'Not required'))}{(' · Vehicle ' + x(g['vehicle_no'])) if g['vehicle_no'] else ''}</div></div>
<div class=box style="margin-top:8px"><b>Bill to:</b> {x(g['buyer_name'] or g['buyer_customer_id'])}<br>{x(addr(cust))}<br>GSTIN: {x(g['buyer_gstin'] or 'Unregistered')} · State code: {x(g['buyer_state_code'])}</div>
<table><tr><th>#</th><th>Description</th><th>HSN</th><th>Qty</th><th>Rate</th><th>Discount</th><th>Taxable</th><th>GST</th><th>Tax</th><th>Total</th></tr>{rows}</table>
<div class=grid><div class=box><b>Amount in words:</b><br>{x(g['amount_in_words'])}<br><br><b>Bank:</b> {x(p.get('bank_name'))} · A/c {x(p.get('bank_account_no'))} · IFSC {x(p.get('bank_ifsc'))}{(' · UPI ' + x(p.get('upi_id'))) if p.get('upi_id') else ''}</div>
<table><tr><td>Taxable value</td><td class=r>{_d(g['taxable_value'])}</td></tr>{tax_rows}<tr><th>Invoice total</th><th class=r>₹ {_d(g['invoice_value'])}</th></tr></table></div>
{irn}<p class=muted>Certified that the particulars given above are true and correct. Goods once sold are subject to the terms agreed with the buyer.</p>
<p style="text-align:right;margin-top:40px">For {x(p.get('legal_name'))}<br><br>Authorised Signatory</p></body></html>"""


def register_v90gx_company_routes(app: FastAPI, e: Engine):
    ensure_v90gx_company_schema(e)

    @app.get('/v90gx/entities')
    def entities(r: Request):
        u = _user(e, r, 'company.profile.view')
        ps = permissions_for_user(e, u.user_id)
        with e.connect() as c:
            rows = [dict(x) for x in c.execute(text('''SELECT en.entity_id,en.entity_code,en.entity_name,p.organization_id,p.legal_name,p.trade_name,p.business_role,p.gstin,p.state_code,p.invoice_prefix,p.fssai_license_no,p.fssai_valid_to
                FROM erp_entities en LEFT JOIN erp_entity_profile p ON p.entity_id=en.entity_id ORDER BY en.entity_code''')).mappings().all()]
        if not ('admin.users' in ps or 'security.rbac.manage' in ps):
            rows = [x for x in rows if is_entity_allowed(e, u.user_id, str(x['entity_id']))]
        return {'entities': rows}

    @app.get('/v90gx/entities/{entity_id}/profile')
    def profile(entity_id: str, r: Request):
        u = _user(e, r, 'company.profile.view'); _entity_scope(e, u.user_id, entity_id)
        p = get_profile(e, entity_id)
        if not p:
            raise HTTPException(404, 'entity profile not set')
        return {'profile': p}

    @app.put('/v90gx/entities/{entity_id}/profile')
    def save_profile(entity_id: str, b: ProfileIn, r: Request):
        u = _user(e, r, 'company.profile.manage'); _entity_scope(e, u.user_id, entity_id)
        with e.connect() as c:
            if not c.execute(text('SELECT 1 FROM erp_entities WHERE entity_id=:e'), {'e': entity_id}).first():
                raise HTTPException(404, 'entity not found')
        if b.state_code not in GST_STATE_CODES:
            raise HTTPException(422, 'state_code is not a valid GST state code (Maharashtra = 27)')
        pan = (b.pan or '').strip().upper() or None
        if pan and not PAN_RE.match(pan):
            raise HTTPException(422, 'PAN format is invalid')
        gstin = validate_gstin(b.gstin, b.state_code, pan) if b.gstin else None
        if gstin and not pan:
            pan = gstin[2:12]
        fssai = (b.fssai_license_no or '').strip() or None
        if fssai and not FSSAI_RE.match(fssai):
            raise HTTPException(422, 'FSSAI licence number must be 14 digits')
        ifsc = (b.bank_ifsc or '').strip().upper() or None
        if ifsc and not IFSC_RE.match(ifsc):
            raise HTTPException(422, 'IFSC format is invalid')
        if not PIN_RE.match(b.pincode.strip()):
            raise HTTPException(422, 'pincode must be 6 digits')
        prefix = (b.invoice_prefix or '').strip().upper() or None
        if prefix and not PREFIX_RE.match(prefix):
            raise HTTPException(422, 'invoice_prefix must be 1-6 letters/digits (PREFIX/YY-YY/NNNN must fit the 16-character GST limit)')
        valid_to = _parse_date(b.fssai_valid_to).isoformat() if b.fssai_valid_to else None
        vals = {**b.model_dump(), 'e': entity_id, 'gstin': gstin, 'pan': pan, 'fssai_license_no': fssai, 'bank_ifsc': ifsc,
                'invoice_prefix': prefix, 'fssai_valid_to': valid_to, 'state_name': GST_STATE_CODES[b.state_code],
                'einvoice_applicable': 1 if b.einvoice_applicable else 0, 'pincode': b.pincode.strip(), 'u': u.user_id}
        cols = ['organization_id', 'legal_name', 'trade_name', 'business_role', 'gstin', 'pan', 'cin', 'fssai_license_no', 'fssai_valid_to',
                'address_line1', 'address_line2', 'city', 'district', 'state_code', 'state_name', 'pincode', 'phone', 'email', 'bank_name',
                'bank_account_no', 'bank_ifsc', 'bank_branch', 'upi_id', 'invoice_prefix', 'einvoice_applicable']
        with e.begin() as c:
            c.execute(text('DELETE FROM erp_entity_profile WHERE entity_id=:e'), {'e': entity_id})
            c.execute(text(f"INSERT INTO erp_entity_profile(entity_id,{','.join(cols)},updated_by) VALUES(:e,{','.join(':' + k for k in cols)},:u)"), vals)
            # erp_security_entity_organization is created by V90.fn, which is registered before this module.
            mapped = c.execute(text('SELECT organization_id FROM erp_security_entity_organization WHERE entity_id=:e'), {'e': entity_id}).first()
            if mapped and str(mapped[0]) != b.organization_id:
                raise HTTPException(409, 'entity is mapped to a different organization')
            if not mapped:
                c.execute(text('INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by) VALUES(:e,:o,:u)'), {'e': entity_id, 'o': b.organization_id, 'u': u.user_id})
            c.execute(text('UPDATE erp_entities SET entity_name=:n WHERE entity_id=:e'), {'n': (b.trade_name or b.legal_name)[:160], 'e': entity_id})
        return {'entity_id': entity_id, 'saved': True, 'gstin': gstin, 'pan': pan, 'state_name': vals['state_name']}

    @app.post('/v90gx/document-series')
    def create_series(b: SeriesIn, r: Request):
        u = _user(e, r, 'company.profile.manage'); _entity_scope(e, u.user_id, b.entity_id)
        prefix = b.prefix.strip().upper()
        if not re.fullmatch(r'[A-Z0-9]{1,8}', prefix):
            raise HTTPException(422, 'prefix must be 1-8 letters/digits')
        fy = b.fy_code or financial_year(datetime.now(timezone.utc).date())[0]
        sample = f"{prefix}/{fy[2:4]}-{fy[5:7]}/{'9' * b.pad_width}"
        if not DOC_NO_RE.match(sample):
            raise HTTPException(422, f'{sample} would exceed the 16-character GST limit; shorten prefix or pad_width')
        p = get_profile(e, b.entity_id)
        if not p:
            raise HTTPException(409, 'save the entity profile first')
        with e.begin() as c:
            if c.execute(text('SELECT 1 FROM erp_document_series WHERE entity_id=:e AND doc_type=:t AND fy_code=:f'), {'e': b.entity_id, 't': b.doc_type, 'f': fy}).first():
                raise HTTPException(409, 'series already exists for this entity, document type and FY')
            sid = str(uuid4())
            c.execute(text('INSERT INTO erp_document_series(series_id,organization_id,entity_id,doc_type,fy_code,prefix,next_no,pad_width,created_by) VALUES(:i,:o,:e,:t,:f,:p,:n,:w,:u)'),
                      {'i': sid, 'o': p['organization_id'], 'e': b.entity_id, 't': b.doc_type, 'f': fy, 'p': prefix, 'n': b.next_no, 'w': b.pad_width, 'u': u.user_id})
        return {'series_id': sid, 'fy_code': fy, 'sample': sample}

    @app.get('/v90gx/document-series')
    def list_series(entity_id: str, r: Request):
        u = _user(e, r, 'company.profile.view'); _entity_scope(e, u.user_id, entity_id)
        with e.connect() as c:
            rows = [dict(x) for x in c.execute(text('SELECT * FROM erp_document_series WHERE entity_id=:e ORDER BY fy_code DESC,doc_type'), {'e': entity_id}).mappings().all()]
        return {'series': rows}

    @app.post('/v90gx/sales-invoices/{invoice_id}/gst-finalize')
    def gst_finalize(invoice_id: str, r: Request, body: dict | None = None):
        u = _user(e, r, 'gst.invoice.manage')
        with e.connect() as c:
            inv = c.execute(text('SELECT entity_id FROM sales_invoices WHERE invoice_id=:i'), {'i': invoice_id}).first()
        if not inv:
            raise HTTPException(404, 'sales invoice not found')
        _entity_scope(e, u.user_id, str(inv[0]))
        b = body or {}
        return finalize_invoice_gst(e, invoice_id, u.user_id, _parse_date(b['invoice_date']) if b.get('invoice_date') else None)

    @app.get('/v90gx/sales-invoices/{invoice_id}/gst')
    def gst_detail(invoice_id: str, r: Request):
        u = _user(e, r, 'gst.invoice.view')
        with e.connect() as c:
            g = c.execute(text('SELECT * FROM sales_invoice_gst_detail WHERE invoice_id=:i'), {'i': invoice_id}).mappings().first()
        if not g:
            raise HTTPException(404, 'GST details not finalized')
        _entity_scope(e, u.user_id, str(g['seller_entity_id']))
        return {'gst': dict(g)}

    @app.get('/v90gx/sales-invoices/{invoice_id}/print', response_class=HTMLResponse)
    def print_invoice(invoice_id: str, r: Request):
        u = _user(e, r, 'gst.invoice.view')
        with e.connect() as c:
            inv = c.execute(text('SELECT entity_id FROM sales_invoices WHERE invoice_id=:i'), {'i': invoice_id}).first()
        if not inv:
            raise HTTPException(404, 'sales invoice not found')
        _entity_scope(e, u.user_id, str(inv[0]))
        return HTMLResponse(render_invoice_html(e, invoice_id))

    @app.post('/v90gx/sales-invoices/{invoice_id}/eway')
    def record_eway(invoice_id: str, b: EwayIn, r: Request):
        u = _user(e, r, 'gst.invoice.manage')
        with e.connect() as c:
            g = c.execute(text('SELECT seller_entity_id FROM sales_invoice_gst_detail WHERE invoice_id=:i'), {'i': invoice_id}).first()
        if not g:
            raise HTTPException(404, 'finalize GST details first')
        _entity_scope(e, u.user_id, str(g[0]))
        with e.begin() as c:
            c.execute(text('UPDATE sales_invoice_gst_detail SET eway_bill_no=:n,eway_valid_upto=:v,vehicle_no=COALESCE(:vn,vehicle_no) WHERE invoice_id=:i'),
                      {'n': b.eway_bill_no, 'v': b.eway_valid_upto, 'vn': b.vehicle_no, 'i': invoice_id})
        return {'invoice_id': invoice_id, 'eway_bill_no': b.eway_bill_no}

    @app.post('/v90gx/sales-invoices/{invoice_id}/einvoice')
    def record_einvoice(invoice_id: str, b: EinvoiceIn, r: Request):
        u = _user(e, r, 'gst.invoice.manage')
        with e.connect() as c:
            g = c.execute(text('SELECT seller_entity_id FROM sales_invoice_gst_detail WHERE invoice_id=:i'), {'i': invoice_id}).first()
        if not g:
            raise HTTPException(404, 'finalize GST details first')
        _entity_scope(e, u.user_id, str(g[0]))
        with e.begin() as c:
            c.execute(text("UPDATE sales_invoice_gst_detail SET irn=:irn,ack_no=:a,ack_date=:d,signed_qr=:q,einvoice_status='GENERATED' WHERE invoice_id=:i"),
                      {'irn': b.irn, 'a': b.ack_no, 'd': b.ack_date, 'q': b.signed_qr, 'i': invoice_id})
        return {'invoice_id': invoice_id, 'einvoice_status': 'GENERATED', 'note': 'IRN recorded from the IRP; this ERP does not call the IRP itself'}

    @app.get('/v90gx/eway-rules')
    def eway_rules(r: Request):
        _user(e, r, 'gst.invoice.view')
        with e.connect() as c:
            return {'rules': [dict(x) for x in c.execute(text('SELECT * FROM erp_eway_rule ORDER BY seller_state_code')).mappings().all()]}

    @app.put('/v90gx/eway-rules/{state_code}')
    def set_eway_rule(state_code: str, body: dict, r: Request):
        _user(e, r, 'company.profile.manage')
        if state_code != '*' and state_code not in GST_STATE_CODES:
            raise HTTPException(422, 'unknown state code')
        intra, inter = _d(body.get('intra_state_threshold')), _d(body.get('inter_state_threshold'))
        if intra <= 0 or inter <= 0:
            raise HTTPException(422, 'thresholds must be positive')
        with e.begin() as c:
            c.execute(text('DELETE FROM erp_eway_rule WHERE seller_state_code=:s'), {'s': state_code})
            c.execute(text('INSERT INTO erp_eway_rule(rule_id,seller_state_code,intra_state_threshold,inter_state_threshold,notes) VALUES(:i,:s,:a,:b,:n)'),
                      {'i': str(uuid4()), 's': state_code, 'a': float(intra), 'b': float(inter), 'n': body.get('notes')})
        return {'seller_state_code': state_code, 'intra_state_threshold': float(intra), 'inter_state_threshold': float(inter)}

    @app.put('/v90gx/customers/{customer_id}/payment-terms')
    def set_terms(customer_id: str, b: TermsIn, r: Request):
        u = _user(e, r, 'sales.terms.manage')
        if customer_id != b.customer_id:
            raise HTTPException(422, 'customer_id mismatch')
        if b.terms_type == 'ADVANCE' and b.advance_pct <= 0:
            raise HTTPException(422, 'advance_pct must be > 0 for ADVANCE terms')
        with e.begin() as c:
            c.execute(text('DELETE FROM customer_payment_terms WHERE customer_id=:c'), {'c': customer_id})
            c.execute(text('INSERT INTO customer_payment_terms(customer_id,organization_id,terms_type,advance_pct,balance_days,notes,updated_by) VALUES(:c,:o,:t,:p,:d,:n,:u)'),
                      {'c': customer_id, 'o': b.organization_id, 't': b.terms_type, 'p': b.advance_pct, 'd': b.balance_days, 'n': b.notes, 'u': u.user_id})
        return {'customer_id': customer_id, 'terms_type': b.terms_type, 'advance_pct': b.advance_pct, 'balance_days': b.balance_days}

    @app.get('/v90gx/customers/{customer_id}/payment-terms')
    def get_terms(customer_id: str, r: Request):
        _user(e, r, 'gst.invoice.view')
        with e.connect() as c:
            t = customer_terms(c, customer_id)
        return {'terms': t or {'customer_id': customer_id, 'terms_type': 'STANDARD', 'advance_pct': 0, 'balance_days': 0}}

    @app.post('/v90gx/sales-orders/{sales_order_id}/advances')
    def record_advance(sales_order_id: str, b: AdvanceIn, r: Request):
        u = _user(e, r, 'sales.terms.manage')
        with e.connect() as c:
            so = c.execute(text('SELECT organization_id,entity_id,grand_total,customer_id FROM sales_orders WHERE sales_order_id=:s'), {'s': sales_order_id}).mappings().first()
        if not so:
            raise HTTPException(404, 'sales order not found')
        _entity_scope(e, u.user_id, str(so['entity_id']))
        with e.begin() as c:
            if c.execute(text('SELECT 1 FROM sales_order_advance WHERE sales_order_id=:s AND reference_no=:r'), {'s': sales_order_id, 'r': b.reference_no}).first():
                raise HTTPException(409, 'this payment reference is already recorded for the order')
            c.execute(text('INSERT INTO sales_order_advance(advance_id,sales_order_id,organization_id,amount,mode,reference_no,received_on,recorded_by) VALUES(:i,:s,:o,:a,:m,:r,:d,:u)'),
                      {'i': str(uuid4()), 's': sales_order_id, 'o': so['organization_id'], 'a': b.amount, 'm': b.mode, 'r': b.reference_no,
                       'd': _parse_date(b.received_on).isoformat(), 'u': u.user_id})
            got = _d(c.execute(text('SELECT COALESCE(SUM(amount),0) FROM sales_order_advance WHERE sales_order_id=:s'), {'s': sales_order_id}).scalar())
            t = customer_terms(c, so['customer_id'])
        need = _d(_d(so['grand_total']) * _d(t['advance_pct']) / 100) if t and t['terms_type'] == 'ADVANCE' else Decimal('0')
        due = (_parse_date(None) + timedelta(days=int(t['balance_days']))).isoformat() if t and t['terms_type'] == 'ADVANCE' else None
        return {'sales_order_id': sales_order_id, 'advance_received': float(got), 'advance_required': float(need),
                'dispatch_allowed_by_terms': got >= need, 'balance_due_by_if_dispatched_today': due}

    @app.get('/ui/company-profile')
    def ui():
        from pathlib import Path
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'company-profile.html')
