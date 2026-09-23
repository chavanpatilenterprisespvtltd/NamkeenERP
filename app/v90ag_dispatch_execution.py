from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_v90ag_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS dispatches (
            dispatch_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sales_order_id TEXT NOT NULL,
            pick_list_id TEXT NOT NULL,
            dispatch_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            vehicle_no TEXT NULL,
            transporter TEXT NULL,
            eway_bill_no TEXT NULL,
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            posted_at TEXT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS dispatch_lines (
            dispatch_line_id TEXT PRIMARY KEY,
            dispatch_id TEXT NOT NULL,
            sales_order_line_id TEXT NOT NULL,
            sales_order_allocation_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            packed_fg_lot_id TEXT NOT NULL,
            lot_code TEXT NULL,
            dispatched_qty NUMERIC NOT NULL,
            uom TEXT NOT NULL DEFAULT 'kg',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(dispatch_id) REFERENCES dispatches(dispatch_id)
        )""",
        """CREATE TABLE IF NOT EXISTS sales_invoices (
            invoice_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            sales_order_id TEXT NOT NULL,
            dispatch_id TEXT NOT NULL,
            invoice_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'POSTED',
            subtotal NUMERIC NOT NULL DEFAULT 0,
            discount_total NUMERIC NOT NULL DEFAULT 0,
            taxable_value NUMERIC NOT NULL DEFAULT 0,
            gst_total NUMERIC NOT NULL DEFAULT 0,
            grand_total NUMERIC NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS sales_invoice_lines (
            invoice_line_id TEXT PRIMARY KEY,
            invoice_id TEXT NOT NULL,
            sales_order_line_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            quantity NUMERIC NOT NULL,
            unit_price NUMERIC NOT NULL,
            discount_amount NUMERIC NOT NULL DEFAULT 0,
            taxable_amount NUMERIC NOT NULL DEFAULT 0,
            gst_rate NUMERIC NOT NULL DEFAULT 0,
            gst_amount NUMERIC NOT NULL DEFAULT 0,
            line_total NUMERIC NOT NULL DEFAULT 0,
            FOREIGN KEY(invoice_id) REFERENCES sales_invoices(invoice_id)
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_dispatch_no ON dispatches(organization_id,entity_id,dispatch_no)",
        "CREATE INDEX IF NOT EXISTS ix_dispatch_order ON dispatches(sales_order_id,status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_no ON sales_invoices(organization_id,entity_id,invoice_no)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_dispatch ON sales_invoices(dispatch_id)",
        "CREATE INDEX IF NOT EXISTS ix_dispatch_scope ON dispatches(entity_id,location_id,warehouse_id,status)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class DispatchCreate(BaseModel):
    dispatch_no: str = Field(min_length=2, max_length=80)
    invoice_no: str = Field(min_length=2, max_length=80)
    vehicle_no: str | None = Field(default=None, max_length=80)
    transporter: str | None = Field(default=None, max_length=120)
    eway_bill_no: str | None = Field(default=None, max_length=80)
    notes: str | None = None


def _require(engine, request: Request, entity_id: str, location_id: str, write: bool = True):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'dispatch.edit' if write else 'dispatch.view'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def register_v90ag_routes(app: FastAPI, engine) -> None:
    ensure_v90ag_schema(engine)

    @app.post('/v90ag/sales/orders/{sales_order_id}/dispatch')
    def execute_dispatch(sales_order_id: UUID, body: DispatchCreate, request: Request):
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
            if not order:
                raise HTTPException(404, 'sales order not found')
            pick = conn.execute(text("SELECT * FROM dispatch_pick_lists WHERE sales_order_id=:id AND status='PICKED' ORDER BY picked_at DESC"), {'id': str(sales_order_id)}).mappings().first()
            if not pick:
                raise HTTPException(409, 'picked pick list is required')
            pick_lines = conn.execute(text('SELECT * FROM dispatch_pick_lines WHERE pick_list_id=:id ORDER BY created_at'), {'id': str(pick['pick_list_id'])}).mappings().all()
            duplicate = conn.execute(text("SELECT dispatch_id,status FROM dispatches WHERE sales_order_id=:id AND status='POSTED'"), {'id': str(sales_order_id)}).mappings().first()
            invoice_dup = conn.execute(text("SELECT invoice_id FROM sales_invoices WHERE organization_id=:o AND entity_id=:e AND invoice_no=:n"), {'o': str(order['organization_id']), 'e': str(order['entity_id']), 'n': body.invoice_no}).first()
            dispatch_dup = conn.execute(text("SELECT dispatch_id FROM dispatches WHERE organization_id=:o AND entity_id=:e AND dispatch_no=:n"), {'o': str(order['organization_id']), 'e': str(order['entity_id']), 'n': body.dispatch_no}).first()
        actor = _require(engine, request, str(order['entity_id']), str(order['location_id']), True)
        actor_id = actor.user_id
        if str(order['status']) != 'APPROVED':
            raise HTTPException(409, f"cannot dispatch order in status {order['status']}")
        if duplicate:
            raise HTTPException(409, 'sales order already has a posted dispatch')
        if invoice_dup:
            raise HTTPException(409, 'invoice number already exists')
        if dispatch_dup:
            raise HTTPException(409, 'dispatch number already exists')
        if not pick_lines:
            raise HTTPException(409, 'pick list has no lines')

        dispatch_id = str(uuid4())
        invoice_id = str(uuid4())
        with engine.begin() as conn:
            for line in pick_lines:
                qty = float(line['picked_qty'])
                if qty <= 0 or str(line['status']) != 'PICKED':
                    raise HTTPException(409, 'all pick lines must be confirmed')
                lot = conn.execute(text("SELECT packed_fg_lot_id,sku_id,available_qty,status,qc_status,warehouse_id,entity_id,location_id FROM packed_fg_lot WHERE packed_fg_lot_id=:id"), {'id': line['packed_fg_lot_id']}).mappings().first()
                if not lot:
                    raise HTTPException(409, f"FG lot not found: {line['packed_fg_lot_id']}")
                if str(lot['entity_id']) != str(order['entity_id']) or str(lot['location_id']) != str(order['location_id']) or str(lot['warehouse_id']) != str(order['warehouse_id']):
                    raise HTTPException(409, 'FG lot is outside sales-order scope')
                if str(lot['status']) != 'AVAILABLE' or str(lot['qc_status']) != 'RELEASED':
                    raise HTTPException(409, f"FG lot {line['lot_code'] or line['packed_fg_lot_id']} is not dispatchable")
                if float(lot['available_qty']) < qty:
                    raise HTTPException(409, f"FG lot {line['lot_code'] or line['packed_fg_lot_id']} stock changed")
                conn.execute(text("UPDATE packed_fg_lot SET available_qty=available_qty-:q, status=CASE WHEN available_qty-:q<=0 THEN 'DISPATCHED' ELSE status END WHERE packed_fg_lot_id=:id"), {'q': qty, 'id': line['packed_fg_lot_id']})
                result = conn.execute(text("UPDATE inventory_stock_balance SET available_qty=available_qty-:q, updated_at=CURRENT_TIMESTAMP WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:i AND uom='kg' AND available_qty>=:q"), {'q': qty, 'o': order['organization_id'], 'e': order['entity_id'], 'l': order['location_id'], 'w': order['warehouse_id'], 'i': line['sku_id']})
                if result.rowcount != 1:
                    raise HTTPException(409, 'FG stock balance changed; dispatch aborted')
                conn.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:id,:o,:e,:l,:w,:i,:lot,'DISPATCH_OUT',:q,'kg','DISPATCH',:d,'POSTED',:by)"), {'id': str(uuid4()), 'o': order['organization_id'], 'e': order['entity_id'], 'l': order['location_id'], 'w': order['warehouse_id'], 'i': line['sku_id'], 'lot': line['packed_fg_lot_id'], 'q': -qty, 'd': dispatch_id, 'by': actor_id})
                conn.execute(text("UPDATE sales_order_allocations SET status='DISPATCHED' WHERE sales_order_allocation_id=:a AND status='ALLOCATED'"), {'a': line['sales_order_allocation_id']})
                conn.execute(text("UPDATE fg_fefo_allocation SET status='CONSUMED' WHERE reference_type='SALES_ORDER' AND reference_id=:so AND packed_fg_lot_id=:lot AND status='OPEN' AND quantity>=:q"), {'so': str(sales_order_id), 'lot': line['packed_fg_lot_id'], 'q': qty})
                conn.execute(text("INSERT INTO dispatch_lines(dispatch_line_id,dispatch_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,dispatched_qty,uom) VALUES(:id,:d,:sl,:a,:s,:lot,:code,:q,'kg')"), {'id': str(uuid4()), 'd': dispatch_id, 'sl': line['sales_order_line_id'], 'a': line['sales_order_allocation_id'], 's': line['sku_id'], 'lot': line['packed_fg_lot_id'], 'code': line['lot_code'], 'q': qty})

            conn.execute(text("INSERT INTO dispatches(dispatch_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,pick_list_id,dispatch_no,status,vehicle_no,transporter,eway_bill_no,notes,created_by,posted_at) VALUES(:d,:o,:e,:l,:w,:so,:p,:dn,'POSTED',:v,:t,:ew,:n,:by,CURRENT_TIMESTAMP)"), {'d': dispatch_id, 'o': order['organization_id'], 'e': order['entity_id'], 'l': order['location_id'], 'w': order['warehouse_id'], 'so': str(sales_order_id), 'p': pick['pick_list_id'], 'dn': body.dispatch_no, 'v': body.vehicle_no, 't': body.transporter, 'ew': body.eway_bill_no, 'n': body.notes, 'by': actor_id})

            conn.execute(text("INSERT INTO sales_invoices(invoice_id,organization_id,entity_id,location_id,sales_order_id,dispatch_id,invoice_no,status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_by) SELECT :i,organization_id,entity_id,location_id,sales_order_id,:d,:n,'POSTED',subtotal,discount_total,taxable_value,gst_total,grand_total,:by FROM sales_orders WHERE sales_order_id=:so"), {'i': invoice_id, 'd': dispatch_id, 'n': body.invoice_no, 'by': actor_id, 'so': str(sales_order_id)})
            conn.execute(text("INSERT INTO sales_invoice_lines(invoice_line_id,invoice_id,sales_order_line_id,sku_id,quantity,unit_price,discount_amount,taxable_amount,gst_rate,gst_amount,line_total) SELECT :id,:inv,sales_order_line_id,sku_id,quantity,unit_price,discount_amount,taxable_amount,gst_rate,gst_amount,line_total FROM sales_order_lines WHERE sales_order_id=:so"), {'id': str(uuid4()), 'inv': invoice_id, 'so': str(sales_order_id)})
            conn.execute(text("UPDATE sales_orders SET status='DISPATCHED', stock_status='DISPATCHED', hold_reason=NULL WHERE sales_order_id=:id"), {'id': str(sales_order_id)})
        return {'dispatch_id': dispatch_id, 'invoice_id': invoice_id, 'sales_order_id': str(sales_order_id), 'dispatch_no': body.dispatch_no, 'invoice_no': body.invoice_no, 'status': 'POSTED'}

    @app.get('/v90ag/dispatches/{dispatch_id}')
    def get_dispatch(dispatch_id: UUID, request: Request):
        with engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM dispatches WHERE dispatch_id=:id'), {'id': str(dispatch_id)}).mappings().first()
            if not row:
                raise HTTPException(404, 'dispatch not found')
            lines = conn.execute(text('SELECT * FROM dispatch_lines WHERE dispatch_id=:id ORDER BY created_at'), {'id': str(dispatch_id)}).mappings().all()
            invoice = conn.execute(text('SELECT * FROM sales_invoices WHERE dispatch_id=:id'), {'id': str(dispatch_id)}).mappings().first()
        _require(engine, request, str(row['entity_id']), str(row['location_id']), False)
        return {'dispatch': dict(row), 'lines': [dict(x) for x in lines], 'invoice': dict(invoice) if invoice else None}
