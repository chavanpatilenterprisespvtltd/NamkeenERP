from __future__ import annotations
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def ensure_v90aj_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS return_credit_notes (
            credit_note_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            sales_return_id TEXT NOT NULL UNIQUE,
            customer_id TEXT NOT NULL,
            credit_note_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'POSTED',
            subtotal NUMERIC NOT NULL DEFAULT 0,
            discount_total NUMERIC NOT NULL DEFAULT 0,
            taxable_value NUMERIC NOT NULL DEFAULT 0,
            gst_total NUMERIC NOT NULL DEFAULT 0,
            grand_total NUMERIC NOT NULL DEFAULT 0,
            reason TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS return_credit_note_lines (
            credit_note_line_id TEXT PRIMARY KEY,
            credit_note_id TEXT NOT NULL,
            sales_return_line_id TEXT NOT NULL,
            invoice_line_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            quantity NUMERIC NOT NULL,
            taxable_amount NUMERIC NOT NULL DEFAULT 0,
            gst_rate NUMERIC NOT NULL DEFAULT 0,
            gst_amount NUMERIC NOT NULL DEFAULT 0,
            line_total NUMERIC NOT NULL DEFAULT 0,
            UNIQUE(credit_note_id, sales_return_line_id)
        )""",
        """CREATE TABLE IF NOT EXISTS customer_credit_adjustments (
            adjustment_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            sales_return_id TEXT NOT NULL,
            credit_note_id TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            adjustment_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'POSTED',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS incentive_reversals (
            incentive_reversal_id TEXT PRIMARY KEY,
            incentive_accrual_id TEXT NOT NULL,
            sales_return_id TEXT NOT NULL,
            sales_return_line_id TEXT NOT NULL,
            salesperson_user_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            returned_quantity NUMERIC NOT NULL,
            original_quantity NUMERIC NOT NULL,
            reversal_amount NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'REVERSED',
            reason TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(incentive_accrual_id, sales_return_line_id)
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_return_credit_note_no ON return_credit_notes(organization_id,entity_id,credit_note_no)",
        "CREATE INDEX IF NOT EXISTS ix_return_credit_note_return ON return_credit_notes(sales_return_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_incentive_reversal_return ON incentive_reversals(sales_return_id,created_at)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('returns.accounting','Post return credit note and incentive reversal') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for stmt in stmts[:-1]:
            conn.execute(text(stmt))
        conn.execute(text(stmts[-1]))
        for role in ('manager', 'super_admin'):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'returns.accounting') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})


class CreditNoteCreate(BaseModel):
    credit_note_no: str = Field(min_length=2, max_length=80)
    reason: str | None = Field(default=None, max_length=500)


def _require(engine, request: Request, entity_id: str, location_id: str, write: bool = False):
    user = authenticate(request)
    needed = 'returns.accounting' if write else 'returns.view'
    if needed not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _money(v) -> float:
    return round(float(v or 0), 6)


def register_v90aj_routes(app: FastAPI, engine) -> None:
    ensure_v90aj_schema(engine)

    @app.post('/v90aj/returns/{sales_return_id}/credit-note')
    def post_credit_note(sales_return_id: UUID, body: CreditNoteCreate, request: Request):
        with engine.connect() as conn:
            ret = conn.execute(text('SELECT * FROM sales_returns WHERE sales_return_id=:r'), {'r': str(sales_return_id)}).mappings().first()
            if not ret:
                raise HTTPException(404, 'sales return not found')
            existing = conn.execute(text('SELECT * FROM return_credit_notes WHERE sales_return_id=:r'), {'r': str(sales_return_id)}).mappings().first()
        user = _require(engine, request, str(ret['entity_id']), str(ret['location_id']), write=True)
        if existing:
            return {'status': 'POSTED', 'credit_note_id': existing['credit_note_id'], 'credit_note_no': existing['credit_note_no'], 'idempotent': True}
        if str(ret['status']) != 'DISPOSITIONED':
            raise HTTPException(409, 'return must be fully dispositioned before credit note')

        with engine.connect() as conn:
            lines = conn.execute(text("""SELECT l.*, d.dispatch_line_id, il.invoice_line_id, il.quantity AS invoice_qty,
                    il.taxable_amount AS invoice_taxable, il.gst_rate AS invoice_gst_rate, il.gst_amount AS invoice_gst,
                    il.line_total AS invoice_line_total
                FROM sales_return_lines l
                JOIN dispatch_lines d ON d.dispatch_line_id=l.dispatch_line_id
                JOIN sales_invoices si ON si.dispatch_id=d.dispatch_id
                JOIN sales_invoice_lines il ON il.invoice_id=si.invoice_id AND il.sales_order_line_id=l.sales_order_line_id AND il.sku_id=l.sku_id
                WHERE l.sales_return_id=:r
                ORDER BY l.created_at, l.sales_return_line_id"""), {'r': str(sales_return_id)}).mappings().all()
        if not lines:
            raise HTTPException(409, 'return has no invoice-linked lines')
        if any(float(x['received_qty']) <= 0 for x in lines):
            raise HTTPException(409, 'all credit note lines require received quantity')

        credit_id = str(uuid4())
        totals = {'taxable': 0.0, 'gst': 0.0, 'grand': 0.0, 'discount': 0.0}
        with engine.begin() as conn:
            # Recheck idempotency inside transaction.
            dup = conn.execute(text('SELECT credit_note_id,credit_note_no,sales_return_id FROM return_credit_notes WHERE sales_return_id=:r OR (organization_id=:o AND entity_id=:e AND credit_note_no=:n)'),
                                {'r': str(sales_return_id), 'o': str(ret['organization_id']), 'e': str(ret['entity_id']), 'n': body.credit_note_no}).mappings().first()
            if dup:
                if str(dup['sales_return_id']) == str(sales_return_id):
                    return {'status': 'POSTED', 'credit_note_id': dup['credit_note_id'], 'credit_note_no': dup['credit_note_no'], 'idempotent': True}
                raise HTTPException(409, 'credit note number already exists')
            for x in lines:
                qty = float(x['received_qty'])
                invoice_qty = float(x['invoice_qty'])
                if invoice_qty <= 0 or qty > invoice_qty + 1e-9:
                    raise HTTPException(409, 'return quantity exceeds invoiced quantity')
                taxable = float(x['invoice_taxable']) * qty / invoice_qty
                gst = float(x['invoice_gst']) * qty / invoice_qty
                total = float(x['invoice_line_total']) * qty / invoice_qty
                totals['taxable'] += taxable; totals['gst'] += gst; totals['grand'] += total
                conn.execute(text("""INSERT INTO return_credit_note_lines
                    (credit_note_line_id,credit_note_id,sales_return_line_id,invoice_line_id,sku_id,quantity,taxable_amount,gst_rate,gst_amount,line_total)
                    VALUES(:id,:cn,:rl,:il,:sku,:q,:tax,:rate,:gst,:total)"""), {
                    'id': str(uuid4()), 'cn': credit_id, 'rl': str(x['sales_return_line_id']), 'il': str(x['invoice_line_id']), 'sku': str(x['sku_id']),
                    'q': qty, 'tax': taxable, 'rate': float(x['invoice_gst_rate'] or 0), 'gst': gst, 'total': total})
            conn.execute(text("""INSERT INTO return_credit_notes
                (credit_note_id,organization_id,entity_id,location_id,sales_return_id,customer_id,credit_note_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,reason,created_by)
                VALUES(:id,:o,:e,:l,:r,:c,:n,'POSTED',:sub,:disc,:tax,:gst,:grand,:reason,:u)"""), {
                'id': credit_id, 'o': str(ret['organization_id']), 'e': str(ret['entity_id']), 'l': str(ret['location_id']), 'r': str(sales_return_id),
                'c': str(ret['customer_id']), 'n': body.credit_note_no, 'sub': totals['taxable'], 'disc': totals['discount'], 'tax': totals['taxable'],
                'gst': totals['gst'], 'grand': totals['grand'], 'reason': body.reason, 'u': str(user.user_id)})
            # Customer receivable is reduced through the posted credit note; keep it explicit rather than mutating original invoice.
            conn.execute(text("""INSERT INTO customer_credit_adjustments
                (adjustment_id,organization_id,entity_id,customer_id,sales_return_id,credit_note_id,amount,adjustment_type,status,created_by)
                VALUES(:id,:o,:e,:c,:r,:cn,:a,'RETURN_CREDIT_NOTE','POSTED',:u)"""), {
                'id': str(uuid4()), 'o': str(ret['organization_id']), 'e': str(ret['entity_id']), 'c': str(ret['customer_id']), 'r': str(sales_return_id), 'cn': credit_id, 'a': totals['grand'], 'u': str(user.user_id)})
        # Incentive reversal is proportional to returned quantity and tied to the original accrual; duplicate-safe by unique key.
        with engine.begin() as conn:
            for x in lines:
                qty = float(x['received_qty'])
                accruals = conn.execute(text("""SELECT * FROM incentive_accruals
                    WHERE sales_order_id=:so AND sku_id=:sku AND status IN ('ACCRUED','APPROVED','PAID') AND quantity>0
                    ORDER BY created_at"""), {'so': str(ret['sales_order_id']), 'sku': str(x['sku_id'])}).mappings().all()
                remaining = qty
                for acc in accruals:
                    already = float(conn.execute(text("SELECT COALESCE(SUM(returned_quantity),0) FROM incentive_reversals WHERE incentive_accrual_id=:a"), {'a': acc['incentive_accrual_id']}).scalar() or 0)
                    allocatable = max(float(acc['quantity']) - already, 0.0)
                    take = min(remaining, allocatable)
                    if take <= 1e-9:
                        continue
                    reversal = float(acc['incentive_amount']) * take / float(acc['quantity'])
                    conn.execute(text("""INSERT INTO incentive_reversals
                        (incentive_reversal_id,incentive_accrual_id,sales_return_id,sales_return_line_id,salesperson_user_id,sku_id,returned_quantity,original_quantity,reversal_amount,status,reason,created_by)
                        VALUES(:id,:a,:r,:rl,:sp,:sku,:q,:orig,:amt,'REVERSED','sales return',:u)"""), {
                        'id': str(uuid4()), 'a': str(acc['incentive_accrual_id']), 'r': str(sales_return_id), 'rl': str(x['sales_return_line_id']),
                        'sp': str(acc['salesperson_user_id']), 'sku': str(x['sku_id']), 'q': take, 'orig': float(acc['quantity']), 'amt': reversal, 'u': str(user.user_id)})
                    remaining -= take
                    if remaining <= 1e-9:
                        break
        with engine.connect() as conn:
            adj = conn.execute(text('SELECT COALESCE(SUM(amount),0) FROM customer_credit_adjustments WHERE sales_return_id=:r'), {'r': str(sales_return_id)}).scalar_one()
            rev = conn.execute(text('SELECT COALESCE(SUM(reversal_amount),0) FROM incentive_reversals WHERE sales_return_id=:r'), {'r': str(sales_return_id)}).scalar_one()
        return {'status': 'POSTED', 'credit_note_id': credit_id, 'credit_note_no': body.credit_note_no,
                'taxable_value': round(totals['taxable'], 2), 'gst_total': round(totals['gst'], 2), 'grand_total': round(totals['grand'], 2),
                'customer_credit_adjustment': round(float(adj), 2), 'incentive_reversal_total': round(float(rev), 2)}

    @app.get('/v90aj/returns/{sales_return_id}/accounting')
    def get_return_accounting(sales_return_id: UUID, request: Request):
        with engine.connect() as conn:
            ret = conn.execute(text('SELECT entity_id,location_id FROM sales_returns WHERE sales_return_id=:r'), {'r': str(sales_return_id)}).mappings().first()
            if not ret:
                raise HTTPException(404, 'sales return not found')
        _require(engine, request, str(ret['entity_id']), str(ret['location_id']), write=False)
        with engine.connect() as conn:
            cn = conn.execute(text('SELECT * FROM return_credit_notes WHERE sales_return_id=:r'), {'r': str(sales_return_id)}).mappings().first()
            lines = conn.execute(text('SELECT * FROM return_credit_note_lines WHERE credit_note_id=:c ORDER BY credit_note_line_id'), {'c': cn['credit_note_id'] if cn else ''}).mappings().all() if cn else []
            adjustments = conn.execute(text('SELECT * FROM customer_credit_adjustments WHERE sales_return_id=:r ORDER BY created_at'), {'r': str(sales_return_id)}).mappings().all()
            reversals = conn.execute(text('SELECT * FROM incentive_reversals WHERE sales_return_id=:r ORDER BY created_at'), {'r': str(sales_return_id)}).mappings().all()
        return {'credit_note': dict(cn) if cn else None, 'lines': [dict(x) for x in lines],
                'customer_credit_adjustments': [dict(x) for x in adjustments], 'incentive_reversals': [dict(x) for x in reversals]}
