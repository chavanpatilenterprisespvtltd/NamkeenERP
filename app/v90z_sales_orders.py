from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def ensure_v90z_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS sales_orders (
            sales_order_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            order_no TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            pricing_status TEXT NOT NULL DEFAULT 'PENDING',
            credit_status TEXT NOT NULL DEFAULT 'PENDING',
            stock_status TEXT NOT NULL DEFAULT 'PENDING',
            subtotal NUMERIC NOT NULL DEFAULT 0,
            discount_total NUMERIC NOT NULL DEFAULT 0,
            taxable_value NUMERIC NOT NULL DEFAULT 0,
            gst_total NUMERIC NOT NULL DEFAULT 0,
            grand_total NUMERIC NOT NULL DEFAULT 0,
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            submitted_at TEXT NULL,
            approved_by TEXT NULL,
            approved_at TEXT NULL,
            hold_reason TEXT NULL,
            rejected_reason TEXT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS sales_order_lines (
            sales_order_line_id TEXT PRIMARY KEY,
            sales_order_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            quantity NUMERIC NOT NULL,
            unit_price NUMERIC NOT NULL,
            discount_pct NUMERIC NOT NULL DEFAULT 0,
            discount_amount NUMERIC NOT NULL DEFAULT 0,
            taxable_amount NUMERIC NOT NULL DEFAULT 0,
            gst_rate NUMERIC NOT NULL DEFAULT 0,
            gst_amount NUMERIC NOT NULL DEFAULT 0,
            line_total NUMERIC NOT NULL DEFAULT 0,
            price_source TEXT NULL,
            margin_status TEXT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_sales_orders_scope ON sales_orders(entity_id,location_id,warehouse_id,customer_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_sales_order_lines_order ON sales_order_lines(sales_order_id)",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


class SalesOrderLineIn(BaseModel):
    sku_id: UUID
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)
    discount_pct: float = Field(default=0, ge=0, le=100)
    gst_rate: float = Field(default=0, ge=0, le=100)
    price_source: str | None = Field(default=None, max_length=50)
    margin_status: str | None = Field(default=None, max_length=30)


class SalesOrderCreate(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID
    customer_id: UUID
    order_no: str = Field(min_length=2, max_length=60)
    lines: list[SalesOrderLineIn] = Field(min_length=1)
    notes: str | None = None


def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write: bool):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'sales.edit' if write else 'sales.view'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _warehouse_ok(engine, warehouse_id: UUID, entity_id: UUID, location_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT warehouse_id FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"), {'w': str(warehouse_id), 'e': str(entity_id), 'l': str(location_id)}).first()
    if not row:
        raise HTTPException(422, 'warehouse not found in entity/location scope')


def register_v90z_routes(app: FastAPI, engine) -> None:
    ensure_v90z_schema(engine)

    @app.post('/v90z/sales/orders')
    def create_sales_order(body: SalesOrderCreate, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        _warehouse_ok(engine, body.warehouse_id, body.entity_id, body.location_id)
        with engine.connect() as conn:
            dup = conn.execute(text("SELECT sales_order_id FROM sales_orders WHERE order_no=:n"), {'n': body.order_no}).first()
            if dup:
                raise HTTPException(409, 'order number already exists')
            cust = conn.execute(text("SELECT 1 FROM master_record WHERE master_id=:id AND master_type='CUSTOMER' AND active=1"), {'id': str(body.customer_id)}).first()
            if not cust:
                raise HTTPException(422, 'customer not found or inactive')
            sku_ids = [str(x.sku_id) for x in body.lines]
            if len(sku_ids) != len(set(sku_ids)):
                raise HTTPException(422, 'duplicate SKU lines are not allowed')
            for sku in sku_ids:
                if not conn.execute(text("SELECT 1 FROM master_record WHERE master_id=:id AND master_type='SKU' AND active=1"), {'id': sku}).first():
                    raise HTTPException(422, f'SKU not found or inactive: {sku}')
        subtotal = 0.0; discount_total = 0.0; taxable_value = 0.0; gst_total = 0.0; grand_total = 0.0
        for line in body.lines:
            gross = line.quantity * line.unit_price
            disc = gross * line.discount_pct / 100
            taxable = gross - disc
            gst = taxable * line.gst_rate / 100
            total = taxable + gst
            subtotal += gross; discount_total += disc; taxable_value += taxable; gst_total += gst; grand_total += total
        order_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO sales_orders(sales_order_id,organization_id,entity_id,location_id,warehouse_id,customer_id,order_no,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,notes,created_by,created_at)
                VALUES(:id,:o,:e,:l,:w,:c,:n,'DRAFT','PENDING','PENDING','PENDING',:sub,:disc,:tax,:gst,:tot,:notes,:by,:at)"""), {
                    'id': order_id, 'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id), 'w': str(body.warehouse_id), 'c': str(body.customer_id), 'n': body.order_no,
                    'sub': subtotal, 'disc': discount_total, 'tax': taxable_value, 'gst': gst_total, 'tot': grand_total, 'notes': body.notes, 'by': str(user.user_id), 'at': now})
            for line in body.lines:
                gross = line.quantity * line.unit_price; disc = gross * line.discount_pct / 100; taxable = gross - disc; gst = taxable * line.gst_rate / 100; total = taxable + gst
                conn.execute(text("""INSERT INTO sales_order_lines(sales_order_line_id,sales_order_id,sku_id,quantity,unit_price,discount_pct,discount_amount,taxable_amount,gst_rate,gst_amount,line_total,price_source,margin_status)
                    VALUES(:id,:oid,:sku,:q,:p,:dp,:da,:ta,:gr,:ga,:lt,:ps,:ms)"""), {'id': str(uuid4()), 'oid': order_id, 'sku': str(line.sku_id), 'q': line.quantity, 'p': line.unit_price, 'dp': line.discount_pct, 'da': disc, 'ta': taxable, 'gr': line.gst_rate, 'ga': gst, 'lt': total, 'ps': line.price_source, 'ms': line.margin_status})
        return {'sales_order_id': order_id, 'order_no': body.order_no, 'status': 'DRAFT', 'subtotal': subtotal, 'discount_total': discount_total, 'taxable_value': taxable_value, 'gst_total': gst_total, 'grand_total': grand_total}

    @app.post('/v90z/sales/orders/{sales_order_id}/submit')
    def submit_sales_order(sales_order_id: UUID, request: Request):
        user = authenticate(request)
        if 'sales.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM sales_orders WHERE sales_order_id=:id"), {'id': str(sales_order_id)}).mappings().first()
            if not row: raise HTTPException(404, 'sales order not found')
        try: assert_entity_location_allowed(engine, user.user_id, str(row['entity_id']), str(row['location_id']))
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
        if row['status'] != 'DRAFT': raise HTTPException(409, f"cannot submit order in status {row['status']}")
        with engine.begin() as conn:
            conn.execute(text("UPDATE sales_orders SET status='SUBMITTED', submitted_at=CURRENT_TIMESTAMP WHERE sales_order_id=:id"), {'id': str(sales_order_id)})
        return {'sales_order_id': str(sales_order_id), 'status': 'SUBMITTED'}

    @app.post('/v90z/sales/orders/{sales_order_id}/approve')
    def approve_sales_order(sales_order_id: UUID, request: Request):
        user = authenticate(request)
        if 'sales.approve' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM sales_orders WHERE sales_order_id=:id"), {'id': str(sales_order_id)}).mappings().first()
        if not row: raise HTTPException(404, 'sales order not found')
        if row['status'] != 'SUBMITTED': raise HTTPException(409, f"cannot approve order in status {row['status']}")
        with engine.begin() as conn:
            conn.execute(text("UPDATE sales_orders SET status='APPROVED', pricing_status='CHECKED', credit_status='CHECKED', stock_status='READY', approved_by=:u, approved_at=CURRENT_TIMESTAMP WHERE sales_order_id=:id"), {'id': str(sales_order_id), 'u': str(user.user_id)})
        return {'sales_order_id': str(sales_order_id), 'status': 'APPROVED', 'pricing_status': 'CHECKED', 'credit_status': 'CHECKED', 'stock_status': 'READY'}

    @app.post('/v90z/sales/orders/{sales_order_id}/hold')
    def hold_sales_order(sales_order_id: UUID, request: Request, reason: str = ''):
        user = authenticate(request)
        if 'sales.approve' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM sales_orders WHERE sales_order_id=:id"), {'id': str(sales_order_id)}).mappings().first()
        if not row: raise HTTPException(404, 'sales order not found')
        try: assert_entity_location_allowed(engine, user.user_id, str(row['entity_id']), str(row['location_id']))
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
        if row['status'] not in ('SUBMITTED','APPROVED'): raise HTTPException(409, 'only submitted/approved orders can be held')
        with engine.begin() as conn:
            conn.execute(text("UPDATE sales_orders SET status='HOLD', hold_reason=:r WHERE sales_order_id=:id"), {'id': str(sales_order_id), 'r': reason})
        return {'sales_order_id': str(sales_order_id), 'status': 'HOLD', 'reason': reason}

    @app.get('/v90z/sales/orders/{sales_order_id}')
    def get_sales_order(sales_order_id: UUID, request: Request):
        user = authenticate(request)
        if 'sales.view' not in permissions_for_user(engine, user.user_id): raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM sales_orders WHERE sales_order_id=:id"), {'id': str(sales_order_id)}).mappings().first()
            if not row: raise HTTPException(404, 'sales order not found')
            lines = conn.execute(text("SELECT * FROM sales_order_lines WHERE sales_order_id=:id"), {'id': str(sales_order_id)}).mappings().all()
        try: assert_entity_location_allowed(engine, user.user_id, str(row['entity_id']), str(row['location_id']))
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
        return {'order': dict(row), 'lines': [dict(x) for x in lines]}
