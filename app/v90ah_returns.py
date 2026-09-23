from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now():
    return datetime.now(timezone.utc).isoformat()


def ensure_v90ah_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS sales_returns (
            sales_return_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sales_order_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            return_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'REQUESTED',
            reason TEXT NULL,
            requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            received_at TEXT NULL,
            created_by TEXT NOT NULL,
            received_by TEXT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS sales_return_lines (
            sales_return_line_id TEXT PRIMARY KEY,
            sales_return_id TEXT NOT NULL,
            dispatch_line_id TEXT NOT NULL,
            sales_order_line_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            packed_fg_lot_id TEXT NOT NULL,
            lot_code TEXT NULL,
            requested_qty NUMERIC NOT NULL,
            received_qty NUMERIC NOT NULL DEFAULT 0,
            disposition_status TEXT NOT NULL DEFAULT 'QC_HOLD',
            reason TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS return_hold_lots (
            return_hold_id TEXT PRIMARY KEY,
            sales_return_id TEXT NOT NULL,
            sales_return_line_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            packed_fg_lot_id TEXT NOT NULL,
            lot_code TEXT NULL,
            quantity NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'QC_HOLD',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_return_no ON sales_returns(organization_id,entity_id,return_no)",
        "CREATE INDEX IF NOT EXISTS ix_sales_return_order ON sales_returns(sales_order_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_sales_return_hold_lot ON return_hold_lots(packed_fg_lot_id,status)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        # Backfill permissions for existing installations/bootstrap databases.
        conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('returns.view','View returns') ON CONFLICT(permission_id) DO NOTHING"))
        conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('returns.edit','Edit returns') ON CONFLICT(permission_id) DO NOTHING"))
        for role in ('manager','salesperson','super_admin'):
            for perm in ('returns.view','returns.edit'):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':perm})


class ReturnLineIn(BaseModel):
    dispatch_line_id: UUID
    requested_qty: float = Field(gt=0)
    reason: str | None = Field(default=None, max_length=500)


class SalesReturnCreate(BaseModel):
    return_no: str = Field(min_length=2, max_length=80)
    lines: list[ReturnLineIn] = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=500)


def _require(engine, request: Request, entity_id: str, location_id: str, write=True):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'returns.edit' if write else 'returns.view'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def register_v90ah_routes(app: FastAPI, engine) -> None:
    ensure_v90ah_schema(engine)

    @app.post('/v90ah/sales/orders/{sales_order_id}/returns')
    def create_return(sales_order_id: UUID, body: SalesReturnCreate, request: Request):
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
            if not order:
                raise HTTPException(404, 'sales order not found')
        user = _require(engine, request, str(order['entity_id']), str(order['location_id']), True)
        if str(order['status']) not in {'DISPATCHED', 'PARTIALLY_RETURNED'}:
            raise HTTPException(409, f"order is not returnable in status {order['status']}")
        if len({str(x.dispatch_line_id) for x in body.lines}) != len(body.lines):
            raise HTTPException(422, 'duplicate dispatch lines are not allowed')
        with engine.connect() as conn:
            dup = conn.execute(text('SELECT 1 FROM sales_returns WHERE organization_id=:o AND entity_id=:e AND return_no=:n'), {'o': str(order['organization_id']), 'e': str(order['entity_id']), 'n': body.return_no}).first()
            if dup:
                raise HTTPException(409, 'return number already exists')
            rows=[]
            for line in body.lines:
                d = conn.execute(text('''SELECT dl.*, d.sales_order_id, d.entity_id, d.location_id, d.warehouse_id
                    FROM dispatch_lines dl JOIN dispatches d ON d.dispatch_id=dl.dispatch_id
                    WHERE dl.dispatch_line_id=:id AND d.sales_order_id=:so AND d.status='POSTED' '''), {'id':str(line.dispatch_line_id),'so':str(sales_order_id)}).mappings().first()
                if not d:
                    raise HTTPException(422, f'dispatch line not found for sales order: {line.dispatch_line_id}')
                prev = float(conn.execute(text("SELECT COALESCE(SUM(requested_qty),0) FROM sales_return_lines WHERE dispatch_line_id=:id AND disposition_status NOT IN ('REJECTED','CANCELLED')"), {'id':str(line.dispatch_line_id)}).scalar() or 0)
                max_qty = float(d['dispatched_qty']) - prev
                if line.requested_qty > max_qty + 1e-9:
                    raise HTTPException(409, f'return qty exceeds dispatched balance for {line.dispatch_line_id}')
                rows.append((line,d,max_qty))
        ret_id = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text('''INSERT INTO sales_returns(sales_return_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,customer_id,return_no,status,reason,requested_at,created_by)
                VALUES(:id,:o,:e,:l,:w,:so,:c,:n,'REQUESTED',:r,:at,:by)'''), {'id':ret_id,'o':str(order['organization_id']),'e':str(order['entity_id']),'l':str(order['location_id']),'w':str(order['warehouse_id']),'so':str(sales_order_id),'c':str(order['customer_id']),'n':body.return_no,'r':body.reason,'at':_now(),'by':str(user.user_id)})
            for line,d,_ in rows:
                conn.execute(text('''INSERT INTO sales_return_lines(sales_return_line_id,sales_return_id,dispatch_line_id,sales_order_line_id,sku_id,packed_fg_lot_id,lot_code,requested_qty,received_qty,disposition_status,reason)
                    VALUES(:id,:r,:dl,:sl,:sku,:lot,:code,:q,0,'QC_HOLD',:reason)'''), {'id':str(uuid4()),'r':ret_id,'dl':str(line.dispatch_line_id),'sl':str(d['sales_order_line_id']),'sku':str(d['sku_id']),'lot':str(d['packed_fg_lot_id']),'code':d['lot_code'],'q':line.requested_qty,'reason':line.reason})
        return {'sales_return_id':ret_id,'return_no':body.return_no,'status':'REQUESTED','line_count':len(rows)}

    @app.post('/v90ah/returns/{sales_return_id}/receive')
    def receive_return(sales_return_id: UUID, request: Request):
        with engine.connect() as conn:
            ret = conn.execute(text('SELECT * FROM sales_returns WHERE sales_return_id=:id'), {'id':str(sales_return_id)}).mappings().first()
            if not ret:
                raise HTTPException(404,'sales return not found')
            lines = conn.execute(text('SELECT * FROM sales_return_lines WHERE sales_return_id=:id'), {'id':str(sales_return_id)}).mappings().all()
        user=_require(engine, request, str(ret['entity_id']), str(ret['location_id']), True)
        if str(ret['status']) != 'REQUESTED':
            raise HTTPException(409, f"return cannot be received in status {ret['status']}")
        with engine.begin() as conn:
            for line in lines:
                if float(line['requested_qty']) <= 0:
                    raise HTTPException(409,'invalid return quantity')
                lot=conn.execute(text('SELECT packed_fg_lot_id,sku_id,status,qc_status,entity_id,location_id,warehouse_id,lot_code FROM packed_fg_lot WHERE packed_fg_lot_id=:id'),{'id':line['packed_fg_lot_id']}).mappings().first()
                if not lot:
                    raise HTTPException(409,f"FG lot not found: {line['packed_fg_lot_id']}")
                if str(lot['entity_id'])!=str(ret['entity_id']) or str(lot['location_id'])!=str(ret['location_id']) or str(lot['warehouse_id'])!=str(ret['warehouse_id']):
                    raise HTTPException(409,'returned FG lot is outside return scope')
                conn.execute(text("UPDATE sales_return_lines SET received_qty=requested_qty, disposition_status='QC_HOLD' WHERE sales_return_line_id=:id"),{'id':line['sales_return_line_id']})
                conn.execute(text('''INSERT INTO return_hold_lots(return_hold_id,sales_return_id,sales_return_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,status,created_by)
                    VALUES(:id,:r,:rl,:o,:e,:l,:w,:sku,:lot,:code,:q,'QC_HOLD',:by)'''), {'id':str(uuid4()),'r':str(sales_return_id),'rl':line['sales_return_line_id'],'o':ret['organization_id'],'e':ret['entity_id'],'l':ret['location_id'],'w':ret['warehouse_id'],'sku':line['sku_id'],'lot':line['packed_fg_lot_id'],'code':lot['lot_code'],'q':float(line['requested_qty']),'by':str(user.user_id)})
            conn.execute(text("UPDATE sales_returns SET status='RECEIVED_QC_HOLD',received_at=CURRENT_TIMESTAMP,received_by=:u WHERE sales_return_id=:id"),{'u':str(user.user_id),'id':str(sales_return_id)})
            conn.execute(text("UPDATE sales_orders SET status='PARTIALLY_RETURNED' WHERE sales_order_id=:id AND status='DISPATCHED'"),{'id':ret['sales_order_id']})
        return {'sales_return_id':str(sales_return_id),'status':'RECEIVED_QC_HOLD','received_line_count':len(lines)}

    @app.get('/v90ah/returns/{sales_return_id}')
    def get_return(sales_return_id: UUID, request: Request):
        with engine.connect() as conn:
            ret=conn.execute(text('SELECT * FROM sales_returns WHERE sales_return_id=:id'),{'id':str(sales_return_id)}).mappings().first()
            if not ret: raise HTTPException(404,'sales return not found')
            lines=conn.execute(text('SELECT * FROM sales_return_lines WHERE sales_return_id=:id ORDER BY created_at'),{'id':str(sales_return_id)}).mappings().all()
            holds=conn.execute(text('SELECT * FROM return_hold_lots WHERE sales_return_id=:id ORDER BY created_at'),{'id':str(sales_return_id)}).mappings().all()
        _require(engine, request, str(ret['entity_id']), str(ret['location_id']), False)
        return {'return':dict(ret),'lines':[dict(x) for x in lines],'hold_lots':[dict(x) for x in holds]}
