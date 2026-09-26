# FILE PATH: app/v90gx_plant_operations.py
# ─── Plant Operations Registers v1.0 (Session CS2 — oil, fuel, utilities, complaints, cartons, purchase returns) ─
#
# [Session CS2] FEATURE — DAILY FACTORY REGISTERS REQUIRED BY THE SPEC WERE MISSING.
# Confirmed this session by searching app/ for each register (no table/route found): frying-oil log
# (R004), fuel/wood log (R005), electricity & water meter log, customer complaints register (R011 / QMS —
# CAPA existed but no complaint intake), carton consumption at packing, and purchase return to supplier.
#
# THE FIX (runtime schema here; PostgreSQL migration 277_v90gx_plant_operations.sql):
#   - plant_oil_log: per fryer & business date — opening/top-up/discard/closing litres, frying temperature
#     and Total Polar Material %. FSSAI limit: oil with TPM > 25 % must not be used → status DISCARD_REQUIRED
#     (limit configurable via OIL_TPM_LIMIT_PCT). Opening + top-up − discard − closing = consumption.
#   - plant_fuel_log: wood / LPG / diesel / PNG / briquette quantity and cost per machine and date.
#   - plant_utility_log: meter readings (electricity/water/steam); units = closing − opening (no negatives),
#     cost = units × rate.
#   - customer_complaint: intake → INVESTIGATING → CLOSED with root cause and action; optional CAPA link;
#     critical food-safety categories (FOREIGN_MATTER, SPOILAGE, ILLNESS) are auto-severity HIGH.
#   - packing_carton_consumption: cartons used vs expected ceil(packs ÷ packs per carton) with variance.
#   - purchase_return (+ lines): DRAFT → POSTED; posting checks ledger stock, writes PURCHASE_RETURN_OUT,
#     updates inventory_stock_balance, and numbers a debit note from the entity's DEBIT_NOTE series when
#     the entity profile has an invoice prefix.
# Every register takes a business_date validated by app/business_date.parse_business_date.
# NOT touched: GRN/QC, packing runs, CAPA module, supplier payables (debit note value is reported for
# accounts to apply; no automatic GL posting).
from __future__ import annotations

import math
import os
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .access_scope import is_entity_allowed
from .auth import authenticate
from .business_date import parse_business_date
from .identity import permissions_for_user
from .stock_balance import apply_balance
from .v90gx_company_gst_invoicing import allocate_document_number

PERMS = [
    ('plant.logs.view', 'View plant daily registers (oil, fuel, utilities, cartons)'),
    ('plant.logs.record', 'Record plant daily registers'),
    ('complaint.view', 'View customer complaints'),
    ('complaint.manage', 'Record and close customer complaints'),
    ('purchase.return.manage', 'Create and post purchase returns to suppliers'),
]
ROLE_GRANTS = {
    'production': ['plant.logs.view', 'plant.logs.record'],
    'production_manager': ['plant.logs.view', 'plant.logs.record', 'complaint.view'],
    'operator': ['plant.logs.record'],
    'packing': ['plant.logs.view', 'plant.logs.record'],
    'quality': ['plant.logs.view', 'complaint.view', 'complaint.manage'],
    'sales': ['complaint.view', 'complaint.manage'],
    'salesperson': ['complaint.manage'],
    'purchase': ['purchase.return.manage'],
    'warehouse': ['purchase.return.manage'],
    'manager': ['plant.logs.view', 'plant.logs.record', 'complaint.view', 'complaint.manage', 'purchase.return.manage'],
}
HIGH_RISK_COMPLAINTS = {'FOREIGN_MATTER', 'SPOILAGE', 'ILLNESS'}


def _d(v, q='0.01') -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal(q), rounding=ROUND_HALF_UP)


def _tpm_limit() -> Decimal:
    return _d(os.getenv('OIL_TPM_LIMIT_PCT', '25'))


class Scope(BaseModel):
    organization_id: str
    entity_id: str
    location_id: str
    business_date: str | None = None
    shift_code: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)


class OilIn(Scope):
    fryer_id: str = Field(min_length=1, max_length=80)
    oil_item_id: str | None = None
    batch_id: str | None = None
    opening_litres: float = Field(ge=0)
    topped_up_litres: float = Field(default=0, ge=0)
    discarded_litres: float = Field(default=0, ge=0)
    closing_litres: float = Field(ge=0)
    frying_temp_c: float | None = Field(default=None, ge=0, le=260)
    tpm_pct: float | None = Field(default=None, ge=0, le=100)


class FuelIn(Scope):
    fuel_type: str = Field(pattern='^(WOOD|LPG|DIESEL|PNG|BRIQUETTE|COAL|OTHER)$')
    machine_id: str | None = Field(default=None, max_length=80)
    quantity: float = Field(gt=0)
    uom: str = Field(pattern='^(kg|litre|scm|tonne)$')
    rate: float = Field(default=0, ge=0)


class UtilityIn(Scope):
    utility_type: str = Field(pattern='^(ELECTRICITY|WATER|STEAM|OTHER)$')
    meter_id: str = Field(min_length=1, max_length=80)
    opening_reading: float = Field(ge=0)
    closing_reading: float = Field(ge=0)
    rate: float = Field(default=0, ge=0)


class CartonIn(Scope):
    packing_run_id: str | None = None
    sku_id: str
    carton_item_id: str | None = None
    packs_packed: int = Field(gt=0)
    packs_per_carton: int = Field(gt=0)
    cartons_used: int = Field(ge=0)


class ComplaintIn(BaseModel):
    organization_id: str
    entity_id: str
    customer_id: str | None = None
    customer_name: str = Field(min_length=2, max_length=160)
    contact_phone: str | None = Field(default=None, max_length=30)
    sku_id: str | None = None
    lot_code: str | None = Field(default=None, max_length=80)
    complaint_date: str | None = None
    category: str = Field(pattern='^(QUALITY|TASTE|FOREIGN_MATTER|SPOILAGE|ILLNESS|PACKAGING|SHORT_WEIGHT|EXPIRY|DELIVERY|OTHER)$')
    severity: str = Field(default='MEDIUM', pattern='^(LOW|MEDIUM|HIGH)$')
    description: str = Field(min_length=5, max_length=3000)


class ComplaintClose(BaseModel):
    root_cause: str = Field(min_length=3, max_length=2000)
    action_taken: str = Field(min_length=3, max_length=2000)
    capa_ref: str | None = Field(default=None, max_length=80)
    customer_informed: bool = True


class ReturnLine(BaseModel):
    item_master_id: str
    lot_id: str | None = None
    quantity: float = Field(gt=0)
    uom: str = Field(min_length=1, max_length=20)
    rate: float = Field(ge=0)
    gst_rate: float = Field(default=0, ge=0, le=40)


class PurchaseReturnIn(BaseModel):
    organization_id: str
    entity_id: str
    location_id: str
    warehouse_id: str
    supplier_id: str
    grn_id: str | None = None
    reason: str = Field(pattern='^(QC_REJECTED|DAMAGED|EXCESS|WRONG_ITEM|EXPIRED|OTHER)$')
    reason_note: str | None = Field(default=None, max_length=1000)
    lines: list[ReturnLine] = Field(min_length=1)


def ensure_v90gx_plant_schema(e: Engine) -> None:
    common = 'organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NOT NULL,business_date DATE NOT NULL,shift_code TEXT NULL,notes TEXT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
    stmts = [
        f'''CREATE TABLE IF NOT EXISTS plant_oil_log(log_id TEXT PRIMARY KEY,{common},fryer_id TEXT NOT NULL,oil_item_id TEXT NULL,batch_id TEXT NULL,opening_litres NUMERIC NOT NULL,topped_up_litres NUMERIC NOT NULL DEFAULT 0,discarded_litres NUMERIC NOT NULL DEFAULT 0,closing_litres NUMERIC NOT NULL,consumed_litres NUMERIC NOT NULL,frying_temp_c NUMERIC NULL,tpm_pct NUMERIC NULL,status TEXT NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS plant_fuel_log(log_id TEXT PRIMARY KEY,{common},fuel_type TEXT NOT NULL,machine_id TEXT NULL,quantity NUMERIC NOT NULL,uom TEXT NOT NULL,rate NUMERIC NOT NULL DEFAULT 0,amount NUMERIC NOT NULL DEFAULT 0)''',
        f'''CREATE TABLE IF NOT EXISTS plant_utility_log(log_id TEXT PRIMARY KEY,{common},utility_type TEXT NOT NULL,meter_id TEXT NOT NULL,opening_reading NUMERIC NOT NULL,closing_reading NUMERIC NOT NULL,units NUMERIC NOT NULL,rate NUMERIC NOT NULL DEFAULT 0,amount NUMERIC NOT NULL DEFAULT 0)''',
        f'''CREATE TABLE IF NOT EXISTS packing_carton_consumption(record_id TEXT PRIMARY KEY,{common},packing_run_id TEXT NULL,sku_id TEXT NOT NULL,carton_item_id TEXT NULL,packs_packed INTEGER NOT NULL,packs_per_carton INTEGER NOT NULL,expected_cartons INTEGER NOT NULL,cartons_used INTEGER NOT NULL,variance_cartons INTEGER NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS customer_complaint(complaint_id TEXT PRIMARY KEY,complaint_no TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,customer_id TEXT NULL,customer_name TEXT NOT NULL,contact_phone TEXT NULL,sku_id TEXT NULL,lot_code TEXT NULL,complaint_date DATE NOT NULL,category TEXT NOT NULL,severity TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',assigned_to TEXT NULL,root_cause TEXT NULL,action_taken TEXT NULL,capa_ref TEXT NULL,customer_informed INTEGER NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,closed_by TEXT NULL,closed_at TIMESTAMP NULL,UNIQUE(entity_id,complaint_no))''',
        '''CREATE TABLE IF NOT EXISTS purchase_return(return_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NOT NULL,warehouse_id TEXT NOT NULL,supplier_id TEXT NOT NULL,grn_id TEXT NULL,reason TEXT NOT NULL,reason_note TEXT NULL,status TEXT NOT NULL DEFAULT 'DRAFT',taxable_value NUMERIC NOT NULL DEFAULT 0,gst_value NUMERIC NOT NULL DEFAULT 0,total_value NUMERIC NOT NULL DEFAULT 0,debit_note_no TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,posted_by TEXT NULL,posted_at TIMESTAMP NULL)''',
        '''CREATE TABLE IF NOT EXISTS purchase_return_line(line_id TEXT PRIMARY KEY,return_id TEXT NOT NULL,item_master_id TEXT NOT NULL,lot_id TEXT NULL,quantity NUMERIC NOT NULL,uom TEXT NOT NULL,rate NUMERIC NOT NULL,gst_rate NUMERIC NOT NULL DEFAULT 0,taxable_value NUMERIC NOT NULL,gst_value NUMERIC NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS ix_oil_log_scope ON plant_oil_log(entity_id,location_id,business_date)',
        'CREATE INDEX IF NOT EXISTS ix_fuel_log_scope ON plant_fuel_log(entity_id,location_id,business_date)',
        'CREATE INDEX IF NOT EXISTS ix_utility_log_scope ON plant_utility_log(entity_id,location_id,business_date)',
        'CREATE INDEX IF NOT EXISTS ix_complaint_scope ON customer_complaint(entity_id,status,complaint_date)',
        'CREATE INDEX IF NOT EXISTS ix_purchase_return_scope ON purchase_return(entity_id,status,supplier_id)',
    ]
    with e.begin() as c:
        for s in stmts:
            c.execute(text(s))
        for p, n in PERMS:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'p': p})
        for role, ps in ROLE_GRANTS.items():
            for p in ps:
                c.execute(text('INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING'), {'r': role, 'p': p})


def _user(e: Engine, r: Request, perm: str, entity_id: str | None = None):
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if perm not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    if entity_id and not ('admin.users' in ps or 'security.rbac.manage' in ps) and not is_entity_allowed(e, u.user_id, entity_id):
        raise HTTPException(403, 'entity access denied')
    return u


def _bdate(v) -> str:
    from datetime import datetime, timezone
    return parse_business_date(v) or datetime.now(timezone.utc).date().isoformat()


def _list(e: Engine, table: str, entity_id: str, date_from: str | None, date_to: str | None, date_col: str = 'business_date'):
    q = f'SELECT * FROM {table} WHERE entity_id=:e'; p = {'e': entity_id}
    if date_from:
        q += f' AND {date_col}>=:f'; p['f'] = date_from
    if date_to:
        q += f' AND {date_col}<=:t'; p['t'] = date_to
    with e.connect() as c:
        return [dict(x) for x in c.execute(text(q + f' ORDER BY {date_col} DESC'), p).mappings().all()]


def register_v90gx_plant_routes(app: FastAPI, e: Engine):
    ensure_v90gx_plant_schema(e)

    @app.post('/v90gx/plant/oil-log')
    def oil(b: OilIn, r: Request):
        u = _user(e, r, 'plant.logs.record', b.entity_id)
        consumed = _d(b.opening_litres) + _d(b.topped_up_litres) - _d(b.discarded_litres) - _d(b.closing_litres)
        if consumed < 0:
            raise HTTPException(422, 'closing litres exceed opening + top-up − discarded; check the readings')
        status = 'OK'
        if b.tpm_pct is not None and _d(b.tpm_pct) > _tpm_limit():
            status = 'DISCARD_REQUIRED'
        elif b.tpm_pct is not None and _d(b.tpm_pct) > _tpm_limit() - 3:
            status = 'NEAR_LIMIT'
        lid = str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO plant_oil_log(log_id,organization_id,entity_id,location_id,business_date,shift_code,notes,recorded_by,fryer_id,oil_item_id,batch_id,opening_litres,topped_up_litres,discarded_litres,closing_litres,consumed_litres,frying_temp_c,tpm_pct,status)
                VALUES(:i,:o,:e,:l,:d,:s,:n,:u,:f,:oi,:b,:op,:tu,:di,:cl,:co,:t,:tpm,:st)'''),
                      {'i': lid, 'o': b.organization_id, 'e': b.entity_id, 'l': b.location_id, 'd': _bdate(b.business_date), 's': b.shift_code, 'n': b.notes, 'u': u.user_id,
                       'f': b.fryer_id, 'oi': b.oil_item_id, 'b': b.batch_id, 'op': b.opening_litres, 'tu': b.topped_up_litres, 'di': b.discarded_litres, 'cl': b.closing_litres,
                       'co': float(consumed), 't': b.frying_temp_c, 'tpm': b.tpm_pct, 'st': status})
        return {'log_id': lid, 'consumed_litres': float(consumed), 'status': status, 'tpm_limit_pct': float(_tpm_limit())}

    @app.post('/v90gx/plant/fuel-log')
    def fuel(b: FuelIn, r: Request):
        u = _user(e, r, 'plant.logs.record', b.entity_id)
        amt = _d(_d(b.quantity, '0.001') * _d(b.rate, '0.0001'))
        lid = str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO plant_fuel_log(log_id,organization_id,entity_id,location_id,business_date,shift_code,notes,recorded_by,fuel_type,machine_id,quantity,uom,rate,amount)
                VALUES(:i,:o,:e,:l,:d,:s,:n,:u,:ft,:m,:q,:uom,:r,:a)'''),
                      {'i': lid, 'o': b.organization_id, 'e': b.entity_id, 'l': b.location_id, 'd': _bdate(b.business_date), 's': b.shift_code, 'n': b.notes, 'u': u.user_id,
                       'ft': b.fuel_type, 'm': b.machine_id, 'q': b.quantity, 'uom': b.uom, 'r': b.rate, 'a': float(amt)})
        return {'log_id': lid, 'amount': float(amt)}

    @app.post('/v90gx/plant/utility-log')
    def utility(b: UtilityIn, r: Request):
        u = _user(e, r, 'plant.logs.record', b.entity_id)
        units = _d(b.closing_reading, '0.001') - _d(b.opening_reading, '0.001')
        if units < 0:
            raise HTTPException(422, 'closing reading is lower than opening reading (meter replaced? record the new meter separately)')
        amt = _d(units * _d(b.rate, '0.0001'))
        lid = str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO plant_utility_log(log_id,organization_id,entity_id,location_id,business_date,shift_code,notes,recorded_by,utility_type,meter_id,opening_reading,closing_reading,units,rate,amount)
                VALUES(:i,:o,:e,:l,:d,:s,:n,:u,:t,:m,:op,:cl,:un,:r,:a)'''),
                      {'i': lid, 'o': b.organization_id, 'e': b.entity_id, 'l': b.location_id, 'd': _bdate(b.business_date), 's': b.shift_code, 'n': b.notes, 'u': u.user_id,
                       't': b.utility_type, 'm': b.meter_id, 'op': b.opening_reading, 'cl': b.closing_reading, 'un': float(units), 'r': b.rate, 'a': float(amt)})
        return {'log_id': lid, 'units': float(units), 'amount': float(amt)}

    @app.post('/v90gx/plant/carton-consumption')
    def cartons(b: CartonIn, r: Request):
        u = _user(e, r, 'plant.logs.record', b.entity_id)
        expected = math.ceil(b.packs_packed / b.packs_per_carton)
        var = b.cartons_used - expected
        rid = str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO packing_carton_consumption(record_id,organization_id,entity_id,location_id,business_date,shift_code,notes,recorded_by,packing_run_id,sku_id,carton_item_id,packs_packed,packs_per_carton,expected_cartons,cartons_used,variance_cartons)
                VALUES(:i,:o,:e,:l,:d,:s,:n,:u,:pr,:sku,:ci,:pp,:ppc,:ex,:cu,:v)'''),
                      {'i': rid, 'o': b.organization_id, 'e': b.entity_id, 'l': b.location_id, 'd': _bdate(b.business_date), 's': b.shift_code, 'n': b.notes, 'u': u.user_id,
                       'pr': b.packing_run_id, 'sku': b.sku_id, 'ci': b.carton_item_id, 'pp': b.packs_packed, 'ppc': b.packs_per_carton, 'ex': expected, 'cu': b.cartons_used, 'v': var})
        return {'record_id': rid, 'expected_cartons': expected, 'cartons_used': b.cartons_used, 'variance_cartons': var}

    @app.get('/v90gx/plant/registers/{register}')
    def registers(register: str, entity_id: str, r: Request, date_from: str | None = None, date_to: str | None = None):
        _user(e, r, 'plant.logs.view', entity_id)
        table = {'oil': 'plant_oil_log', 'fuel': 'plant_fuel_log', 'utility': 'plant_utility_log', 'cartons': 'packing_carton_consumption'}.get(register)
        if not table:
            raise HTTPException(404, 'register must be oil, fuel, utility or cartons')
        return {'register': register, 'rows': _list(e, table, entity_id, date_from, date_to)}

    @app.get('/v90gx/plant/daily-summary')
    def daily(entity_id: str, business_date: str, r: Request):
        _user(e, r, 'plant.logs.view', entity_id)
        d = parse_business_date(business_date) if business_date else None
        with e.connect() as c:
            oil = c.execute(text('SELECT COALESCE(SUM(consumed_litres),0),COALESCE(SUM(topped_up_litres),0),COUNT(*),SUM(CASE WHEN status=\'DISCARD_REQUIRED\' THEN 1 ELSE 0 END) FROM plant_oil_log WHERE entity_id=:e AND business_date=:d'), {'e': entity_id, 'd': d}).first()
            fuel = c.execute(text('SELECT fuel_type,uom,COALESCE(SUM(quantity),0),COALESCE(SUM(amount),0) FROM plant_fuel_log WHERE entity_id=:e AND business_date=:d GROUP BY fuel_type,uom'), {'e': entity_id, 'd': d}).all()
            util = c.execute(text('SELECT utility_type,COALESCE(SUM(units),0),COALESCE(SUM(amount),0) FROM plant_utility_log WHERE entity_id=:e AND business_date=:d GROUP BY utility_type'), {'e': entity_id, 'd': d}).all()
            batches = c.execute(text('SELECT COUNT(*) FROM production_batch WHERE entity_id=:e AND business_date=:d'), {'e': entity_id, 'd': d}).scalar()
        return {'business_date': d, 'production_batches': int(batches or 0),
                'oil': {'consumed_litres': float(oil[0] or 0), 'topped_up_litres': float(oil[1] or 0), 'entries': int(oil[2] or 0), 'discard_required': int(oil[3] or 0)},
                'fuel': [{'fuel_type': x[0], 'uom': x[1], 'quantity': float(x[2]), 'amount': float(x[3])} for x in fuel],
                'utilities': [{'utility_type': x[0], 'units': float(x[1]), 'amount': float(x[2])} for x in util]}

    @app.post('/v90gx/complaints')
    def complaint(b: ComplaintIn, r: Request):
        u = _user(e, r, 'complaint.manage', b.entity_id)
        from datetime import datetime, timezone
        cdate = (parse_business_date(b.complaint_date) if b.complaint_date else None) or datetime.now(timezone.utc).date().isoformat()
        severity = 'HIGH' if b.category in HIGH_RISK_COMPLAINTS else b.severity
        cid = str(uuid4())
        with e.begin() as c:
            n = int(c.execute(text('SELECT COUNT(*) FROM customer_complaint WHERE entity_id=:e'), {'e': b.entity_id}).scalar() or 0) + 1
            no = f'CC-{cdate[:4]}-{n:05d}'
            c.execute(text('''INSERT INTO customer_complaint(complaint_id,complaint_no,organization_id,entity_id,customer_id,customer_name,contact_phone,sku_id,lot_code,complaint_date,category,severity,description,created_by)
                VALUES(:i,:no,:o,:e,:c,:cn,:ph,:s,:lot,:d,:cat,:sev,:desc,:u)'''),
                      {'i': cid, 'no': no, 'o': b.organization_id, 'e': b.entity_id, 'c': b.customer_id, 'cn': b.customer_name, 'ph': b.contact_phone, 's': b.sku_id, 'lot': b.lot_code,
                       'd': cdate, 'cat': b.category, 'sev': severity, 'desc': b.description, 'u': u.user_id})
        return {'complaint_id': cid, 'complaint_no': no, 'severity': severity, 'status': 'OPEN',
                'next_step': 'Trace the lot and hold remaining stock if food-safety risk' if severity == 'HIGH' else 'Investigate', 'lot_code': b.lot_code}

    @app.post('/v90gx/complaints/{complaint_id}/investigate')
    def investigate(complaint_id: str, r: Request, body: dict | None = None):
        u = _user(e, r, 'complaint.manage')
        with e.begin() as c:
            res = c.execute(text("UPDATE customer_complaint SET status='INVESTIGATING',assigned_to=:a WHERE complaint_id=:i AND status='OPEN' RETURNING complaint_id"),
                            {'a': (body or {}).get('assigned_to') or u.user_id, 'i': complaint_id}).first()
        if not res:
            raise HTTPException(404, 'open complaint not found')
        return {'complaint_id': complaint_id, 'status': 'INVESTIGATING'}

    @app.post('/v90gx/complaints/{complaint_id}/close')
    def close_complaint(complaint_id: str, b: ComplaintClose, r: Request):
        u = _user(e, r, 'complaint.manage')
        with e.begin() as c:
            row = c.execute(text('SELECT severity,status FROM customer_complaint WHERE complaint_id=:i'), {'i': complaint_id}).mappings().first()
            if not row or row['status'] == 'CLOSED':
                raise HTTPException(404, 'open complaint not found')
            if row['severity'] == 'HIGH' and not b.capa_ref:
                raise HTTPException(422, 'HIGH severity complaints need a CAPA reference before closing')
            c.execute(text("UPDATE customer_complaint SET status='CLOSED',root_cause=:rc,action_taken=:a,capa_ref=:cr,customer_informed=:ci,closed_by=:u,closed_at=CURRENT_TIMESTAMP WHERE complaint_id=:i"),
                      {'rc': b.root_cause, 'a': b.action_taken, 'cr': b.capa_ref, 'ci': 1 if b.customer_informed else 0, 'u': u.user_id, 'i': complaint_id})
        return {'complaint_id': complaint_id, 'status': 'CLOSED'}

    @app.get('/v90gx/complaints')
    def complaints(entity_id: str, r: Request, status: str | None = None):
        _user(e, r, 'complaint.view', entity_id)
        q = 'SELECT * FROM customer_complaint WHERE entity_id=:e'; p = {'e': entity_id}
        if status:
            q += ' AND status=:s'; p['s'] = status.upper()
        with e.connect() as c:
            return {'complaints': [dict(x) for x in c.execute(text(q + ' ORDER BY complaint_date DESC,complaint_no DESC'), p).mappings().all()]}

    @app.post('/v90gx/purchase-returns')
    def create_return(b: PurchaseReturnIn, r: Request):
        u = _user(e, r, 'purchase.return.manage', b.entity_id)
        rid = str(uuid4()); taxable = gst = Decimal('0')
        with e.begin() as c:
            for l in b.lines:
                tv = _d(_d(l.quantity, '0.0001') * _d(l.rate, '0.0001')); gv = _d(tv * _d(l.gst_rate) / 100)
                taxable += tv; gst += gv
                c.execute(text('INSERT INTO purchase_return_line(line_id,return_id,item_master_id,lot_id,quantity,uom,rate,gst_rate,taxable_value,gst_value) VALUES(:i,:r,:it,:lot,:q,:u,:rt,:g,:tv,:gv)'),
                          {'i': str(uuid4()), 'r': rid, 'it': l.item_master_id, 'lot': l.lot_id, 'q': l.quantity, 'u': l.uom, 'rt': l.rate, 'g': l.gst_rate, 'tv': float(tv), 'gv': float(gv)})
            c.execute(text('''INSERT INTO purchase_return(return_id,organization_id,entity_id,location_id,warehouse_id,supplier_id,grn_id,reason,reason_note,taxable_value,gst_value,total_value,created_by)
                VALUES(:i,:o,:e,:l,:w,:s,:g,:r,:rn,:tv,:gv,:t,:u)'''),
                      {'i': rid, 'o': b.organization_id, 'e': b.entity_id, 'l': b.location_id, 'w': b.warehouse_id, 's': b.supplier_id, 'g': b.grn_id, 'r': b.reason, 'rn': b.reason_note,
                       'tv': float(taxable), 'gv': float(gst), 't': float(taxable + gst), 'u': u.user_id})
        return {'return_id': rid, 'status': 'DRAFT', 'total_value': float(taxable + gst)}

    @app.post('/v90gx/purchase-returns/{return_id}/post')
    def post_return(return_id: str, r: Request):
        with e.connect() as c:
            head = c.execute(text("SELECT entity_id FROM purchase_return WHERE return_id=:i AND status='DRAFT'"), {'i': return_id}).first()
        if not head:
            raise HTTPException(404, 'draft purchase return not found')
        u = _user(e, r, 'purchase.return.manage', str(head[0]))
        # Everything below uses only `c` (no second connection inside the posting transaction).
        with e.begin() as c:
            pr = c.execute(text("SELECT * FROM purchase_return WHERE return_id=:i AND status='DRAFT'"), {'i': return_id}).mappings().first()
            if not pr:
                raise HTTPException(409, 'purchase return was posted by another user')
            lines = c.execute(text('SELECT * FROM purchase_return_line WHERE return_id=:i'), {'i': return_id}).mappings().all()
            for l in lines:
                lot_sql = 'lot_id=:lot' if l['lot_id'] else 'lot_id IS NULL'
                prm = {'o': pr['organization_id'], 'e': pr['entity_id'], 'l': pr['location_id'], 'w': pr['warehouse_id'], 'i': l['item_master_id']}
                if l['lot_id']:
                    prm['lot'] = l['lot_id']
                bal = c.execute(text(f"SELECT COALESCE(SUM(quantity),0) FROM inventory_stock_ledger WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND {lot_sql} AND status='POSTED'"), prm).scalar() or 0
                if _d(bal, '0.0001') < _d(l['quantity'], '0.0001'):
                    raise HTTPException(409, f"insufficient stock to return item {l['item_master_id']}")
                c.execute(text("""INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by)
                    VALUES(:m,:o,:e,:l,:w,:i,:lot,'PURCHASE_RETURN_OUT',:q,:u,'PURCHASE_RETURN',:r,'POSTED',:by)"""),
                          {'m': str(uuid4()), 'o': pr['organization_id'], 'e': pr['entity_id'], 'l': pr['location_id'], 'w': pr['warehouse_id'], 'i': l['item_master_id'], 'lot': l['lot_id'],
                           'q': -float(l['quantity']), 'u': l['uom'], 'r': return_id, 'by': u.user_id})
                apply_balance(c, organization_id=pr['organization_id'], entity_id=pr['entity_id'], location_id=pr['location_id'], warehouse_id=pr['warehouse_id'],
                              item_master_id=l['item_master_id'], uom=l['uom'], delta=-float(l['quantity']))
            dn = None
            prof = c.execute(text('SELECT invoice_prefix FROM erp_entity_profile WHERE entity_id=:e'), {'e': pr['entity_id']}).mappings().first()
            if prof and prof['invoice_prefix']:
                from datetime import datetime, timezone
                dn = allocate_document_number(e, entity_id=str(pr['entity_id']), doc_type='DEBIT_NOTE', doc_date=datetime.now(timezone.utc).date(), user_id=u.user_id,
                                              reference_type='PURCHASE_RETURN', reference_id=return_id, conn=c)
            c.execute(text("UPDATE purchase_return SET status='POSTED',debit_note_no=:dn,posted_by=:u,posted_at=CURRENT_TIMESTAMP WHERE return_id=:i"), {'dn': dn, 'u': u.user_id, 'i': return_id})
        return {'return_id': return_id, 'status': 'POSTED', 'debit_note_no': dn, 'debit_note_value': float(_d(pr['total_value'])),
                'accounting_posting_automatic': False}

    @app.get('/v90gx/purchase-returns')
    def list_returns(entity_id: str, r: Request, status: str | None = None):
        _user(e, r, 'purchase.return.manage', entity_id)
        q = 'SELECT * FROM purchase_return WHERE entity_id=:e'; p = {'e': entity_id}
        if status:
            q += ' AND status=:s'; p['s'] = status.upper()
        with e.connect() as c:
            return {'returns': [dict(x) for x in c.execute(text(q + ' ORDER BY created_at DESC'), p).mappings().all()]}

    @app.get('/ui/plant-registers')
    def ui():
        from pathlib import Path
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'plant-registers.html')
