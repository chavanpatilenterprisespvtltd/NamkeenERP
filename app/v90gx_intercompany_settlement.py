# FILE PATH: app/v90gx_intercompany_settlement.py
# ─── Intercompany X→Y Transfer Pricing & Settlement v1.0 (Session CS2 — transfer-price policy, GST, X invoice, in-transit, Y receipt, settlement) ─
#
# [Session CS2] FEATURE — COMPANY X MANUFACTURES, COMPANY Y SELLS: THE X→Y SALE HAD NO PRICE RULE, NO GST, NO INVOICE, NO RECEIPT AND NO SETTLEMENT.
# Confirmed this session by reading app/v90fm_intercompany_execution.py: taxable_value/tax_value are typed
# by hand, POST …/post writes INTERCOMPANY_OUT and INTERCOMPANY_IN in the same instant (no in-transit, no
# receipt by Y), and nothing records X's tax invoice to Y or Y's payment to X. The owner's decision this
# session: the X→Y price is "let them decide" — so no default price exists; a policy must be set first.
#
# THE FIX (runtime schema here; PostgreSQL migration 275_v90gx_intercompany_settlement.sql). Flow on top of
# the V90.fm transaction (created with POST /v90fm/intercompany/transactions, status DRAFT):
#   1. POST /v90gx/intercompany/policies — X and Y agree a transfer-price policy per pair (optionally per
#      item): COST_PLUS (cost × (1+markup%)), FIXED_PRICE, or SELLING_PRICE_MINUS (Y's selling price − %),
#      with the GST rate and validity dates. Without an active policy pricing is refused (HTTP 409).
#   2. POST …/transactions/{id}/price — applies the policy to each line, computes CGST+SGST (same state) or
#      IGST (different states) from both entity profiles (GSTINs are mandatory for a tax invoice).
#   3. POST …/transactions/{id}/dispatch — X ships: stock check, INTERCOMPANY_OUT at X, X's tax invoice
#      numbered from X's IC_INVOICE series (PREFIXI/YY-YY/NNNN), e-way threshold check; status IN_TRANSIT.
#   4. POST …/transactions/{id}/receive — Y receives (full or short): INTERCOMPANY_IN at Y for the received
#      quantity, shortage recorded; status POSTED (so the V90.fm elimination/period-close keeps working)
#      and an OPEN elimination is created exactly as V90.fm does.
#   5. POST /v90gx/intercompany/invoices/{id}/settlements — Y pays X (bank/UPI/cheque/netting); no
#      over-payment; invoice PARTIAL/SETTLED. GET /v90gx/intercompany/balances — X receivable = Y payable.
# The legacy one-step POST /v90fm/…/post is refused for transactions priced here (see that file).
# The older intercompany tables from migrations 148/149 are not used by this flow (documented deprecated).
# Stock: ledger rows plus inventory_stock_balance via app/stock_balance.apply_balance (X decrement at
# dispatch, Y increment at receipt).
# NOT touched: stock ledger structure, V90.fm create/list/eliminations/close routes, accounting journals
# (no automatic GL posting — same boundary as V90.fm: accounting_posting_automatic=False).
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .auth import authenticate
from .identity import permissions_for_user
from .stock_balance import apply_balance
from .v90fo_audit_approval_evidence import write_audit
from .v90gx_company_gst_invoicing import (GST_STATE_CODES, allocate_document_number, amount_in_words,
                                          eway_threshold, get_profile)

PERMS = [
    ('intercompany.policy.manage', 'Create/close intercompany transfer-price policies'),
    ('intercompany.receive', 'Receive intercompany stock at the receiving entity'),
    ('intercompany.settle', 'Record intercompany invoice settlements'),
]
ROLE_GRANTS = {
    'accounts': ['intercompany.view', 'intercompany.settle'],
    'warehouse': ['intercompany.view', 'intercompany.receive'],
    'dispatch': ['intercompany.view', 'intercompany.post'],
    'manager': ['intercompany.view', 'intercompany.manage', 'intercompany.post', 'intercompany.receive'],
}
METHODS = ('COST_PLUS', 'FIXED_PRICE', 'SELLING_PRICE_MINUS')


def _d(v, q='0.01') -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal(q), rounding=ROUND_HALF_UP)


def _today() -> date:
    return datetime.now(timezone.utc).date()


class PolicyIn(BaseModel):
    organization_id: str
    from_entity_id: str
    to_entity_id: str
    item_master_id: str | None = None
    method: str = Field(pattern='^(COST_PLUS|FIXED_PRICE|SELLING_PRICE_MINUS)$')
    markup_pct: float | None = Field(default=None, ge=0, le=500)
    fixed_price: float | None = Field(default=None, gt=0)
    discount_pct: float | None = Field(default=None, ge=0, lt=100)
    gst_rate: float = Field(ge=0, le=40)
    effective_from: str
    effective_to: str | None = None
    agreement_ref: str = Field(min_length=2, max_length=200, description='board resolution / agreement reference both companies signed')


class PriceIn(BaseModel):
    unit_costs: dict[str, float] | None = None
    selling_prices: dict[str, float] | None = None
    pricing_date: str | None = None


class DispatchIn(BaseModel):
    evidence_note: str = Field(min_length=2, max_length=1000)
    vehicle_no: str | None = Field(default=None, max_length=20)
    eway_bill_no: str | None = Field(default=None, pattern=r'^\d{12}$')
    invoice_date: str | None = None


class ReceiveLine(BaseModel):
    line_id: str
    received_qty: float = Field(ge=0)


class ReceiveIn(BaseModel):
    evidence_note: str = Field(min_length=2, max_length=1000)
    lines: list[ReceiveLine] | None = None
    shortage_reason: str | None = Field(default=None, max_length=500)


class SettleIn(BaseModel):
    amount: float = Field(gt=0)
    mode: str = Field(pattern='^(BANK|UPI|CHEQUE|NETTING|CASH)$')
    reference_no: str = Field(min_length=1, max_length=80)
    settlement_date: str | None = None


def ensure_v90gx_intercompany_schema(e: Engine) -> None:
    stmts = [
        '''CREATE TABLE IF NOT EXISTS intercompany_transfer_price_policy(policy_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,from_entity_id TEXT NOT NULL,to_entity_id TEXT NOT NULL,item_master_id TEXT NULL,method TEXT NOT NULL,markup_pct NUMERIC NULL,fixed_price NUMERIC NULL,discount_pct NUMERIC NULL,gst_rate NUMERIC NOT NULL,effective_from DATE NOT NULL,effective_to DATE NULL,agreement_ref TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ACTIVE',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,closed_by TEXT NULL,closed_at TIMESTAMP NULL)''',
        '''CREATE TABLE IF NOT EXISTS intercompany_pricing(transaction_id TEXT PRIMARY KEY,pricing_date DATE NOT NULL,supply_type TEXT NOT NULL,taxable_value NUMERIC NOT NULL,cgst_amount NUMERIC NOT NULL DEFAULT 0,sgst_amount NUMERIC NOT NULL DEFAULT 0,igst_amount NUMERIC NOT NULL DEFAULT 0,total_value NUMERIC NOT NULL,priced_by TEXT NOT NULL,priced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS intercompany_pricing_line(line_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,policy_id TEXT NOT NULL,method TEXT NOT NULL,basis_value NUMERIC NOT NULL,unit_price NUMERIC NOT NULL,taxable_value NUMERIC NOT NULL,gst_rate NUMERIC NOT NULL,tax_value NUMERIC NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS intercompany_invoice(ic_invoice_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL UNIQUE,organization_id TEXT NOT NULL,from_entity_id TEXT NOT NULL,to_entity_id TEXT NOT NULL,invoice_no TEXT NOT NULL,invoice_date DATE NOT NULL,supply_type TEXT NOT NULL,taxable_value NUMERIC NOT NULL,cgst_amount NUMERIC NOT NULL DEFAULT 0,sgst_amount NUMERIC NOT NULL DEFAULT 0,igst_amount NUMERIC NOT NULL DEFAULT 0,total_value NUMERIC NOT NULL,settled_value NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'ISSUED',eway_bill_no TEXT NULL,vehicle_no TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(from_entity_id,invoice_no))''',
        '''CREATE TABLE IF NOT EXISTS intercompany_receipt(receipt_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL UNIQUE,received_by TEXT NOT NULL,received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,shortage_qty NUMERIC NOT NULL DEFAULT 0,shortage_value NUMERIC NOT NULL DEFAULT 0,shortage_reason TEXT NULL,evidence_note TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS intercompany_receipt_line(receipt_line_id TEXT PRIMARY KEY,receipt_id TEXT NOT NULL,line_id TEXT NOT NULL,dispatched_qty NUMERIC NOT NULL,received_qty NUMERIC NOT NULL,shortage_qty NUMERIC NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS intercompany_settlement(settlement_id TEXT PRIMARY KEY,ic_invoice_id TEXT NOT NULL,organization_id TEXT NOT NULL,amount NUMERIC NOT NULL,mode TEXT NOT NULL,reference_no TEXT NOT NULL,settlement_date DATE NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(ic_invoice_id,reference_no))''',
        'CREATE INDEX IF NOT EXISTS ix_ic_policy_pair ON intercompany_transfer_price_policy(organization_id,from_entity_id,to_entity_id,status)',
        'CREATE INDEX IF NOT EXISTS ix_ic_invoice_scope ON intercompany_invoice(organization_id,from_entity_id,to_entity_id,status)',
    ]
    with e.begin() as c:
        for s in stmts:
            c.execute(text(s))
        for p, n in PERMS:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})
        for p in ['intercompany.view', 'intercompany.manage', 'intercompany.post', 'intercompany.eliminate', 'intercompany.close'] + [x[0] for x in PERMS]:
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'p': p})
        for role, ps in ROLE_GRANTS.items():
            for p in ps:
                c.execute(text('INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING'), {'r': role, 'p': p})


def _perm(e: Engine, r: Request, p: str):
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _date(v, default: date | None = None) -> date:
    if not v:
        return default or _today()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as exc:
        raise HTTPException(422, 'dates must be YYYY-MM-DD') from exc


def _policy_for(c, org: str, fe: str, te: str, item: str, on: date):
    rows = c.execute(text("""SELECT * FROM intercompany_transfer_price_policy WHERE organization_id=:o AND from_entity_id=:f AND to_entity_id=:t
        AND status='ACTIVE' AND (item_master_id=:i OR item_master_id IS NULL) AND effective_from<=:d AND (effective_to IS NULL OR effective_to>=:d)"""),
                     {'o': org, 'f': fe, 't': te, 'i': item, 'd': on.isoformat()}).mappings().all()
    specific = [x for x in rows if x['item_master_id'] is not None]
    pool = specific or [x for x in rows if x['item_master_id'] is None]
    return max(pool, key=lambda x: str(x['effective_from'])) if pool else None


def _supply(e: Engine, fe: str, te: str) -> tuple[str, dict, dict]:
    pf, pt = get_profile(e, fe), get_profile(e, te)
    if not pf or not pt or not pf.get('gstin') or not pt.get('gstin'):
        raise HTTPException(409, 'both entities need a saved profile with GSTIN before an intercompany tax invoice (see /ui/company-profile)')
    return ('INTRA_STATE' if pf['state_code'] == pt['state_code'] else 'INTER_STATE'), pf, pt


def register_v90gx_intercompany_routes(app: FastAPI, e: Engine):
    ensure_v90gx_intercompany_schema(e)

    @app.post('/v90gx/intercompany/policies')
    def create_policy(b: PolicyIn, r: Request):
        u = _perm(e, r, 'intercompany.policy.manage')
        if b.from_entity_id == b.to_entity_id:
            raise HTTPException(422, 'from and to entity must differ')
        if b.method == 'COST_PLUS' and b.markup_pct is None:
            raise HTTPException(422, 'markup_pct is required for COST_PLUS')
        if b.method == 'FIXED_PRICE' and not b.item_master_id:
            raise HTTPException(422, 'FIXED_PRICE policies must name the item')
        if b.method == 'FIXED_PRICE' and b.fixed_price is None:
            raise HTTPException(422, 'fixed_price is required for FIXED_PRICE')
        if b.method == 'SELLING_PRICE_MINUS' and b.discount_pct is None:
            raise HTTPException(422, 'discount_pct is required for SELLING_PRICE_MINUS')
        ef = _date(b.effective_from); et = _date(b.effective_to) if b.effective_to else None
        if et and et < ef:
            raise HTTPException(422, 'effective_to is before effective_from')
        pid = str(uuid4())
        with e.begin() as c:
            # Conditions built in Python: ":x IS NULL" with an untyped parameter fails on PostgreSQL.
            q = """SELECT policy_id FROM intercompany_transfer_price_policy WHERE organization_id=:o AND from_entity_id=:f AND to_entity_id=:t AND status='ACTIVE'
                AND (effective_to IS NULL OR effective_to>=:ef)"""
            prm = {'o': b.organization_id, 'f': b.from_entity_id, 't': b.to_entity_id, 'ef': ef.isoformat()}
            q += ' AND item_master_id=:i' if b.item_master_id else ' AND item_master_id IS NULL'
            if b.item_master_id:
                prm['i'] = b.item_master_id
            if et:
                q += ' AND effective_from<=:et'; prm['et'] = et.isoformat()
            overlap = c.execute(text(q), prm).first()
            if overlap:
                raise HTTPException(409, 'an active policy already covers this pair/item for these dates; close it first')
            c.execute(text('''INSERT INTO intercompany_transfer_price_policy(policy_id,organization_id,from_entity_id,to_entity_id,item_master_id,method,markup_pct,fixed_price,discount_pct,gst_rate,effective_from,effective_to,agreement_ref,created_by)
                VALUES(:id,:o,:f,:t,:i,:m,:mk,:fp,:dp,:g,:ef,:et,:a,:u)'''),
                      {'id': pid, 'o': b.organization_id, 'f': b.from_entity_id, 't': b.to_entity_id, 'i': b.item_master_id, 'm': b.method, 'mk': b.markup_pct, 'fp': b.fixed_price,
                       'dp': b.discount_pct, 'g': b.gst_rate, 'ef': ef.isoformat(), 'et': et.isoformat() if et else None, 'a': b.agreement_ref, 'u': u.user_id})
        write_audit(e, actor_user_id=u.user_id, module_name='INTERCOMPANY', action_code='TRANSFER_PRICE_POLICY_CREATE', outcome='SUCCESS', organization_id=b.organization_id,
                    subject_type='IC_POLICY', subject_id=pid, details={'method': b.method, 'agreement_ref': b.agreement_ref})
        return {'policy_id': pid, 'status': 'ACTIVE'}

    @app.get('/v90gx/intercompany/policies')
    def list_policies(organization_id: str, r: Request, status: str = 'ACTIVE'):
        _perm(e, r, 'intercompany.view')
        with e.connect() as c:
            rows = c.execute(text('SELECT * FROM intercompany_transfer_price_policy WHERE organization_id=:o AND status=:s ORDER BY created_at DESC'), {'o': organization_id, 's': status.upper()}).mappings().all()
        return {'policies': [dict(x) for x in rows]}

    @app.post('/v90gx/intercompany/policies/{policy_id}/close')
    def close_policy(policy_id: str, r: Request):
        u = _perm(e, r, 'intercompany.policy.manage')
        with e.begin() as c:
            res = c.execute(text("UPDATE intercompany_transfer_price_policy SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP WHERE policy_id=:p AND status='ACTIVE' RETURNING policy_id"), {'u': u.user_id, 'p': policy_id}).first()
        if not res:
            raise HTTPException(404, 'active policy not found')
        return {'policy_id': policy_id, 'status': 'CLOSED'}

    @app.post('/v90gx/intercompany/transactions/{transaction_id}/price')
    def price(transaction_id: str, b: PriceIn, r: Request):
        u = _perm(e, r, 'intercompany.manage')
        on = _date(b.pricing_date)
        with e.connect() as c:
            tx = c.execute(text("SELECT * FROM intercompany_transaction WHERE transaction_id=:t"), {'t': transaction_id}).mappings().first()
        if not tx:
            raise HTTPException(404, 'intercompany transaction not found')
        if tx['status'] != 'DRAFT':
            raise HTTPException(409, f"only DRAFT transactions can be priced (status {tx['status']})")
        supply, _, _ = _supply(e, tx['from_entity_id'], tx['to_entity_id'])
        with e.begin() as c:
            lines = c.execute(text('SELECT * FROM intercompany_transaction_line WHERE transaction_id=:t ORDER BY line_id'), {'t': transaction_id}).mappings().all()
            c.execute(text('DELETE FROM intercompany_pricing_line WHERE transaction_id=:t'), {'t': transaction_id})
            taxable = tax = Decimal('0.00'); out = []
            for l in lines:
                pol = _policy_for(c, tx['organization_id'], tx['from_entity_id'], tx['to_entity_id'], l['item_master_id'], on)
                if not pol:
                    raise HTTPException(409, f"no active transfer-price policy for item {l['item_master_id']} on {on} — X and Y must agree and record one first")
                item = str(l['item_master_id'])
                if pol['method'] == 'COST_PLUS':
                    basis = _d((b.unit_costs or {}).get(item, l['unit_value']), '0.0001')
                    if basis <= 0:
                        raise HTTPException(409, f'unit cost needed for COST_PLUS item {item}')
                    unit = _d(basis * (1 + _d(pol['markup_pct'], '0.0001') / 100), '0.0001')
                elif pol['method'] == 'FIXED_PRICE':
                    basis = _d(pol['fixed_price'], '0.0001'); unit = basis
                else:
                    basis = _d((b.selling_prices or {}).get(item, l['unit_value']), '0.0001')
                    if basis <= 0:
                        raise HTTPException(409, f'selling price needed for SELLING_PRICE_MINUS item {item}')
                    unit = _d(basis * (1 - _d(pol['discount_pct'], '0.0001') / 100), '0.0001')
                lt = _d(_d(l['quantity'], '0.0001') * unit); lx = _d(lt * _d(pol['gst_rate'], '0.0001') / 100)
                taxable += lt; tax += lx
                c.execute(text('UPDATE intercompany_transaction_line SET unit_value=:u,line_value=:v WHERE line_id=:l'), {'u': float(unit), 'v': float(lt), 'l': l['line_id']})
                c.execute(text('INSERT INTO intercompany_pricing_line(line_id,transaction_id,policy_id,method,basis_value,unit_price,taxable_value,gst_rate,tax_value) VALUES(:l,:t,:p,:m,:b,:u,:tv,:g,:x)'),
                          {'l': l['line_id'], 't': transaction_id, 'p': pol['policy_id'], 'm': pol['method'], 'b': float(basis), 'u': float(unit), 'tv': float(lt), 'g': float(_d(pol['gst_rate'])), 'x': float(lx)})
                out.append({'line_id': l['line_id'], 'item_master_id': item, 'method': pol['method'], 'basis': float(basis), 'unit_price': float(unit), 'taxable': float(lt), 'gst_rate': float(_d(pol['gst_rate'])), 'tax': float(lx)})
            if supply == 'INTRA_STATE':
                cg = _d(tax / 2); sg = tax - cg; ig = Decimal('0.00')
            else:
                cg = sg = Decimal('0.00'); ig = tax
            total = taxable + tax
            c.execute(text('UPDATE intercompany_transaction SET taxable_value=:a,tax_value=:b,total_value=:t WHERE transaction_id=:id'), {'a': float(taxable), 'b': float(tax), 't': float(total), 'id': transaction_id})
            c.execute(text('DELETE FROM intercompany_pricing WHERE transaction_id=:t'), {'t': transaction_id})
            c.execute(text('INSERT INTO intercompany_pricing(transaction_id,pricing_date,supply_type,taxable_value,cgst_amount,sgst_amount,igst_amount,total_value,priced_by) VALUES(:t,:d,:s,:a,:cg,:sg,:ig,:tot,:u)'),
                      {'t': transaction_id, 'd': on.isoformat(), 's': supply, 'a': float(taxable), 'cg': float(cg), 'sg': float(sg), 'ig': float(ig), 'tot': float(total), 'u': u.user_id})
        return {'transaction_id': transaction_id, 'supply_type': supply, 'taxable_value': float(taxable), 'cgst': float(cg), 'sgst': float(sg), 'igst': float(ig), 'total_value': float(total), 'lines': out}

    @app.post('/v90gx/intercompany/transactions/{transaction_id}/dispatch')
    def dispatch(transaction_id: str, b: DispatchIn, r: Request):
        u = _perm(e, r, 'intercompany.post')
        inv_date = _date(b.invoice_date)
        with e.begin() as c:
            tx = c.execute(text("SELECT * FROM intercompany_transaction WHERE transaction_id=:t AND status='DRAFT'"), {'t': transaction_id}).mappings().first()
            if not tx:
                raise HTTPException(404, 'draft intercompany transaction not found')
            pr = c.execute(text('SELECT * FROM intercompany_pricing WHERE transaction_id=:t'), {'t': transaction_id}).mappings().first()
            if not pr:
                raise HTTPException(409, 'price the transaction with the agreed transfer-price policy first')
            pf = c.execute(text('SELECT state_code FROM erp_entity_profile WHERE entity_id=:e'), {'e': tx['from_entity_id']}).first()
            limit = eway_threshold(c, pf[0] if pf else None, pr['supply_type'] == 'INTER_STATE')
            if _d(pr['total_value']) > limit and not b.eway_bill_no:
                raise HTTPException(409, {'message': 'e-way bill (12 digits) is required: consignment value exceeds threshold', 'consignment_value': float(_d(pr['total_value'])), 'threshold': float(limit)})
            lines = c.execute(text('SELECT * FROM intercompany_transaction_line WHERE transaction_id=:t ORDER BY line_id'), {'t': transaction_id}).mappings().all()
            for l in lines:
                q = _d(l['quantity'], '0.0001')
                lot_sql = 'lot_id=:lot' if l['lot_id'] else 'lot_id IS NULL'
                bal = c.execute(text(f"SELECT COALESCE(SUM(quantity),0) FROM inventory_stock_ledger WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND {lot_sql} AND status='POSTED'"),
                                {'o': tx['organization_id'], 'e': tx['from_entity_id'], 'l': l['from_location_id'], 'w': l['from_warehouse_id'], 'i': l['item_master_id'], **({'lot': l['lot_id']} if l['lot_id'] else {})}).scalar() or 0
                if _d(bal, '0.0001') < q:
                    raise HTTPException(409, f"insufficient stock at the manufacturing entity for item {l['item_master_id']}")
                c.execute(text("""INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by)
                    VALUES(:a,:o,:fe,:fl,:fw,:i,:lot,'INTERCOMPANY_OUT',:q,:u,'INTERCOMPANY',:t,'POSTED',:by)"""),
                          {'a': str(uuid4()), 'o': tx['organization_id'], 'fe': tx['from_entity_id'], 'fl': l['from_location_id'], 'fw': l['from_warehouse_id'], 'i': l['item_master_id'], 'lot': l['lot_id'], 'q': float(-q), 'u': l['uom'], 't': transaction_id, 'by': u.user_id})
                apply_balance(c, organization_id=tx['organization_id'], entity_id=tx['from_entity_id'], location_id=l['from_location_id'], warehouse_id=l['from_warehouse_id'], item_master_id=l['item_master_id'], uom=l['uom'], delta=float(-q))
            inv_no = allocate_document_number(e, entity_id=str(tx['from_entity_id']), doc_type='IC_INVOICE', doc_date=inv_date, user_id=u.user_id, reference_type='INTERCOMPANY', reference_id=transaction_id, conn=c)
            iid = str(uuid4())
            c.execute(text('''INSERT INTO intercompany_invoice(ic_invoice_id,transaction_id,organization_id,from_entity_id,to_entity_id,invoice_no,invoice_date,supply_type,taxable_value,cgst_amount,sgst_amount,igst_amount,total_value,eway_bill_no,vehicle_no,created_by)
                VALUES(:i,:t,:o,:f,:to,:n,:d,:s,:a,:cg,:sg,:ig,:tot,:ew,:v,:u)'''),
                      {'i': iid, 't': transaction_id, 'o': tx['organization_id'], 'f': tx['from_entity_id'], 'to': tx['to_entity_id'], 'n': inv_no, 'd': inv_date.isoformat(), 's': pr['supply_type'],
                       'a': float(_d(pr['taxable_value'])), 'cg': float(_d(pr['cgst_amount'])), 'sg': float(_d(pr['sgst_amount'])), 'ig': float(_d(pr['igst_amount'])), 'tot': float(_d(pr['total_value'])),
                       'ew': b.eway_bill_no, 'v': b.vehicle_no, 'u': u.user_id})
            c.execute(text("UPDATE intercompany_transaction SET status='IN_TRANSIT',posting_date=:d,narration=COALESCE(narration,'') || ' | Dispatch: ' || :ev WHERE transaction_id=:t"), {'d': inv_date.isoformat(), 'ev': b.evidence_note, 't': transaction_id})
        write_audit(e, actor_user_id=u.user_id, module_name='INTERCOMPANY', action_code='IC_DISPATCH', outcome='SUCCESS', organization_id=str(tx['organization_id']),
                    subject_type='INTERCOMPANY_TRANSACTION', subject_id=transaction_id, details={'invoice_no': inv_no})
        return {'transaction_id': transaction_id, 'status': 'IN_TRANSIT', 'ic_invoice_id': iid, 'invoice_no': inv_no, 'total_value': float(_d(pr['total_value'])),
                'print_url': f'/v90gx/intercompany/invoices/{iid}/print'}

    @app.post('/v90gx/intercompany/transactions/{transaction_id}/receive')
    def receive(transaction_id: str, b: ReceiveIn, r: Request):
        u = _perm(e, r, 'intercompany.receive')
        with e.begin() as c:
            tx = c.execute(text("SELECT * FROM intercompany_transaction WHERE transaction_id=:t AND status='IN_TRANSIT'"), {'t': transaction_id}).mappings().first()
            if not tx:
                raise HTTPException(404, 'in-transit intercompany transaction not found')
            lines = {str(l['line_id']): l for l in c.execute(text('SELECT * FROM intercompany_transaction_line WHERE transaction_id=:t'), {'t': transaction_id}).mappings().all()}
            got = {x.line_id: _d(x.received_qty, '0.0001') for x in (b.lines or [])}
            unknown = set(got) - set(lines)
            if unknown:
                raise HTTPException(422, f'unknown line_id(s): {sorted(unknown)}')
            rid = str(uuid4()); short_q = short_v = Decimal('0')
            for lid, l in lines.items():
                sent = _d(l['quantity'], '0.0001'); rec = got.get(lid, sent)
                if rec > sent:
                    raise HTTPException(422, 'received quantity cannot exceed dispatched quantity')
                sq = sent - rec
                short_q += sq; short_v += _d(sq * _d(l['unit_value'], '0.0001'))
                if rec > 0:
                    c.execute(text("""INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by)
                        VALUES(:a,:o,:te,:tl,:tw,:i,:lot,'INTERCOMPANY_IN',:q,:u,'INTERCOMPANY',:t,'POSTED',:by)"""),
                              {'a': str(uuid4()), 'o': tx['organization_id'], 'te': tx['to_entity_id'], 'tl': l['to_location_id'], 'tw': l['to_warehouse_id'], 'i': l['item_master_id'], 'lot': l['lot_id'], 'q': float(rec), 'u': l['uom'], 't': transaction_id, 'by': u.user_id})
                    apply_balance(c, organization_id=tx['organization_id'], entity_id=tx['to_entity_id'], location_id=l['to_location_id'], warehouse_id=l['to_warehouse_id'], item_master_id=l['item_master_id'], uom=l['uom'], delta=float(rec))
                c.execute(text('INSERT INTO intercompany_receipt_line(receipt_line_id,receipt_id,line_id,dispatched_qty,received_qty,shortage_qty) VALUES(:i,:r,:l,:d,:q,:s)'),
                          {'i': str(uuid4()), 'r': rid, 'l': lid, 'd': float(sent), 'q': float(rec), 's': float(sq)})
            if short_q > 0 and not b.shortage_reason:
                raise HTTPException(422, 'shortage_reason is required when received quantity is less than dispatched')
            c.execute(text('INSERT INTO intercompany_receipt(receipt_id,transaction_id,received_by,shortage_qty,shortage_value,shortage_reason,evidence_note) VALUES(:r,:t,:u,:sq,:sv,:sr,:ev)'),
                      {'r': rid, 't': transaction_id, 'u': u.user_id, 'sq': float(short_q), 'sv': float(short_v), 'sr': b.shortage_reason, 'ev': b.evidence_note})
            c.execute(text("UPDATE intercompany_transaction SET status='POSTED',posted_by=:u,posted_at=CURRENT_TIMESTAMP,narration=COALESCE(narration,'') || ' | Receipt: ' || :ev WHERE transaction_id=:t"), {'u': u.user_id, 'ev': b.evidence_note, 't': transaction_id})
            c.execute(text("UPDATE intercompany_invoice SET status='RECEIVED' WHERE transaction_id=:t AND status='ISSUED'"), {'t': transaction_id})
            c.execute(text("INSERT INTO intercompany_elimination(elimination_id,organization_id,period_key,transaction_id,from_entity_id,to_entity_id,amount,status,evidence_note,created_by) VALUES(:id,:o,:p,:t,:f,:to,:a,'OPEN',:ev,:u)"),
                      {'id': str(uuid4()), 'o': tx['organization_id'], 'p': tx['period_key'], 't': transaction_id, 'f': tx['from_entity_id'], 'to': tx['to_entity_id'], 'a': float(_d(tx['total_value'])), 'ev': b.evidence_note, 'u': u.user_id})
        write_audit(e, actor_user_id=u.user_id, module_name='INTERCOMPANY', action_code='IC_RECEIPT', outcome='SUCCESS', organization_id=str(tx['organization_id']),
                    subject_type='INTERCOMPANY_TRANSACTION', subject_id=transaction_id, details={'shortage_qty': float(short_q)})
        return {'transaction_id': transaction_id, 'status': 'POSTED', 'receipt_id': rid, 'shortage_qty': float(short_q), 'shortage_value': float(short_v), 'elimination_status': 'OPEN'}

    @app.get('/v90gx/intercompany/transactions/{transaction_id}')
    def get_tx(transaction_id: str, r: Request):
        _perm(e, r, 'intercompany.view')
        with e.connect() as c:
            tx = c.execute(text('SELECT * FROM intercompany_transaction WHERE transaction_id=:t'), {'t': transaction_id}).mappings().first()
            if not tx:
                raise HTTPException(404, 'intercompany transaction not found')
            lines = [dict(x) for x in c.execute(text('SELECT * FROM intercompany_transaction_line WHERE transaction_id=:t ORDER BY line_id'), {'t': transaction_id}).mappings().all()]
            pr = c.execute(text('SELECT * FROM intercompany_pricing WHERE transaction_id=:t'), {'t': transaction_id}).mappings().first()
            inv = c.execute(text('SELECT * FROM intercompany_invoice WHERE transaction_id=:t'), {'t': transaction_id}).mappings().first()
        return {'transaction': dict(tx), 'lines': lines, 'pricing': dict(pr) if pr else None, 'invoice': dict(inv) if inv else None}

    @app.post('/v90gx/intercompany/invoices/{ic_invoice_id}/settlements')
    def settle(ic_invoice_id: str, b: SettleIn, r: Request):
        u = _perm(e, r, 'intercompany.settle')
        amt = _d(b.amount)
        with e.begin() as c:
            inv = c.execute(text('SELECT * FROM intercompany_invoice WHERE ic_invoice_id=:i'), {'i': ic_invoice_id}).mappings().first()
            if not inv:
                raise HTTPException(404, 'intercompany invoice not found')
            outstanding = _d(inv['total_value']) - _d(inv['settled_value'])
            if amt > outstanding:
                raise HTTPException(409, {'message': 'settlement exceeds outstanding', 'outstanding': float(outstanding)})
            if c.execute(text('SELECT 1 FROM intercompany_settlement WHERE ic_invoice_id=:i AND reference_no=:r'), {'i': ic_invoice_id, 'r': b.reference_no}).first():
                raise HTTPException(409, 'payment reference already recorded for this invoice')
            c.execute(text('INSERT INTO intercompany_settlement(settlement_id,ic_invoice_id,organization_id,amount,mode,reference_no,settlement_date,created_by) VALUES(:s,:i,:o,:a,:m,:r,:d,:u)'),
                      {'s': str(uuid4()), 'i': ic_invoice_id, 'o': inv['organization_id'], 'a': float(amt), 'm': b.mode, 'r': b.reference_no, 'd': _date(b.settlement_date).isoformat(), 'u': u.user_id})
            new_settled = _d(inv['settled_value']) + amt
            status = 'SETTLED' if new_settled >= _d(inv['total_value']) else 'PARTIALLY_SETTLED'
            c.execute(text('UPDATE intercompany_invoice SET settled_value=:v,status=:s WHERE ic_invoice_id=:i'), {'v': float(new_settled), 's': status, 'i': ic_invoice_id})
        write_audit(e, actor_user_id=u.user_id, module_name='INTERCOMPANY', action_code='IC_SETTLEMENT', outcome='SUCCESS', organization_id=str(inv['organization_id']),
                    subject_type='IC_INVOICE', subject_id=ic_invoice_id, details={'amount': float(amt), 'mode': b.mode})
        return {'ic_invoice_id': ic_invoice_id, 'settled_value': float(new_settled), 'outstanding': float(_d(inv['total_value']) - new_settled), 'status': status}

    @app.get('/v90gx/intercompany/balances')
    def balances(organization_id: str, r: Request):
        _perm(e, r, 'intercompany.view')
        with e.connect() as c:
            rows = c.execute(text('''SELECT from_entity_id,to_entity_id,COUNT(*) invoices,COALESCE(SUM(total_value),0) invoiced,COALESCE(SUM(settled_value),0) settled,
                COALESCE(SUM(CASE WHEN status='ISSUED' THEN total_value ELSE 0 END),0) in_transit_value FROM intercompany_invoice WHERE organization_id=:o GROUP BY from_entity_id,to_entity_id'''), {'o': organization_id}).mappings().all()
        out = []
        for x in rows:
            o = _d(x['invoiced']) - _d(x['settled'])
            out.append({'seller_entity_id': x['from_entity_id'], 'buyer_entity_id': x['to_entity_id'], 'invoices': int(x['invoices']), 'invoiced': float(_d(x['invoiced'])),
                        'settled': float(_d(x['settled'])), 'seller_receivable': float(o), 'buyer_payable': float(o), 'in_transit_value': float(_d(x['in_transit_value']))})
        return {'balances': out}

    @app.get('/v90gx/intercompany/invoices')
    def list_invoices(organization_id: str, r: Request, status: str | None = None):
        _perm(e, r, 'intercompany.view')
        q = 'SELECT * FROM intercompany_invoice WHERE organization_id=:o'; p = {'o': organization_id}
        if status:
            q += ' AND status=:s'; p['s'] = status.upper()
        with e.connect() as c:
            return {'invoices': [dict(x) for x in c.execute(text(q + ' ORDER BY created_at DESC'), p).mappings().all()]}

    @app.get('/v90gx/intercompany/invoices/{ic_invoice_id}/print', response_class=HTMLResponse)
    def print_ic(ic_invoice_id: str, r: Request):
        _perm(e, r, 'intercompany.view')
        with e.connect() as c:
            inv = c.execute(text('SELECT * FROM intercompany_invoice WHERE ic_invoice_id=:i'), {'i': ic_invoice_id}).mappings().first()
            if not inv:
                raise HTTPException(404, 'intercompany invoice not found')
            lines = c.execute(text('''SELECT l.item_master_id,l.quantity,l.uom,p.unit_price,p.taxable_value,p.gst_rate,p.tax_value FROM intercompany_transaction_line l
                JOIN intercompany_pricing_line p ON p.line_id=l.line_id WHERE l.transaction_id=:t'''), {'t': inv['transaction_id']}).mappings().all()
        s, b = get_profile(e, inv['from_entity_id']) or {}, get_profile(e, inv['to_entity_id']) or {}
        x = lambda v: escape(str(v if v is not None else ''))
        rows = ''.join(f"<tr><td>{x(l['item_master_id'])}</td><td>{x(l['quantity'])} {x(l['uom'])}</td><td>{_d(l['unit_price'], '0.0001')}</td><td>{_d(l['taxable_value'])}</td><td>{x(l['gst_rate'])}%</td><td>{_d(l['tax_value'])}</td></tr>" for l in lines)
        tax = (f"IGST {_d(inv['igst_amount'])}" if inv['supply_type'] == 'INTER_STATE' else f"CGST {_d(inv['cgst_amount'])} · SGST {_d(inv['sgst_amount'])}")
        return HTMLResponse(f"""<!doctype html><html><head><meta charset=utf-8><title>IC Invoice {x(inv['invoice_no'])}</title><style>body{{font:13px Arial;margin:24px}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #444;padding:4px}}</style></head><body>
<h2 style="text-align:center">TAX INVOICE (Intercompany)</h2><p><b>{x(s.get('legal_name'))}</b> · GSTIN {x(s.get('gstin'))} · FSSAI {x(s.get('fssai_license_no'))}<br>{x(s.get('address_line1'))}, {x(s.get('city'))} {x(s.get('pincode'))}</p>
<p>Invoice {x(inv['invoice_no'])} · Date {x(inv['invoice_date'])} · Place of supply {x(b.get('state_code'))}-{x(GST_STATE_CODES.get(b.get('state_code') or '', ''))}</p>
<p><b>Buyer:</b> {x(b.get('legal_name'))} · GSTIN {x(b.get('gstin'))}</p>
<table><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Taxable</th><th>GST</th><th>Tax</th></tr>{rows}</table>
<p>Taxable {_d(inv['taxable_value'])} · {tax} · <b>Total ₹ {_d(inv['total_value'])}</b><br>{x(amount_in_words(inv['total_value']))}</p>
<p>E-way bill: {x(inv['eway_bill_no'] or '—')} · Vehicle {x(inv['vehicle_no'] or '—')}</p><p style="text-align:right">For {x(s.get('legal_name'))}<br><br>Authorised Signatory</p></body></html>""")

    @app.get('/ui/intercompany-xy')
    def ui():
        from pathlib import Path
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'intercompany-xy.html')
