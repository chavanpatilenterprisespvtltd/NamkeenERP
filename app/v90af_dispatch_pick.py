from __future__ import annotations
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def ensure_v90af_schema(engine):
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS dispatch_pick_lists (
            pick_list_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sales_order_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            picked_at TEXT NULL,
            confirmed_by TEXT NULL
        )"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS dispatch_pick_lines (
            pick_line_id TEXT PRIMARY KEY,
            pick_list_id TEXT NOT NULL,
            sales_order_line_id TEXT NOT NULL,
            sales_order_allocation_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            packed_fg_lot_id TEXT NOT NULL,
            lot_code TEXT NULL,
            allocated_qty NUMERIC NOT NULL,
            picked_qty NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_pick_order ON dispatch_pick_lists(sales_order_id,status)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_pick_line_alloc ON dispatch_pick_lines(sales_order_allocation_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pick_scope ON dispatch_pick_lists(entity_id,location_id,warehouse_id,status)"))


def _require(engine, request: Request, entity_id: str, location_id: str, write: bool):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'dispatch.edit' if write else 'dispatch.view'
    if needed not in perms and not ('inventory.edit' if write else 'inventory.view') in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def register_v90af_routes(app: FastAPI, engine):
    ensure_v90af_schema(engine)

    @app.post('/v90af/sales/orders/{sales_order_id}/pick-list')
    def create_pick_list(sales_order_id: UUID, request: Request):
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
            if not order:
                raise HTTPException(404, 'sales order not found')
        _require(engine, request, str(order['entity_id']), str(order['location_id']), True)
        if str(order['status']) != 'APPROVED':
            raise HTTPException(409, f"cannot pick order in status {order['status']}")
        with engine.connect() as conn:
            existing = conn.execute(text("SELECT pick_list_id,status FROM dispatch_pick_lists WHERE sales_order_id=:id AND status IN ('OPEN','PICKED')"), {'id': str(sales_order_id)}).mappings().first()
            if existing:
                raise HTTPException(409, 'active pick list already exists')
            allocs = conn.execute(text("""SELECT a.sales_order_allocation_id,a.sales_order_line_id,a.sku_id,a.packed_fg_lot_id,a.lot_code,a.quantity,
                                              l.status AS lot_status,l.qc_status,l.available_qty
                                       FROM sales_order_allocations a
                                       JOIN packed_fg_lot l ON l.packed_fg_lot_id=a.packed_fg_lot_id
                                       WHERE a.sales_order_id=:id AND a.status='ALLOCATED'
                                       ORDER BY a.created_at"""), {'id': str(sales_order_id)}).mappings().all()
        if not allocs:
            raise HTTPException(409, 'no active stock allocations')
        pick_id = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO dispatch_pick_lists(pick_list_id,organization_id,entity_id,location_id,warehouse_id,sales_order_id,status,created_by)
                                VALUES(:p,:o,:e,:l,:w,:so,'OPEN',:by)"""), {'p': pick_id,'o':str(order['organization_id']),'e':str(order['entity_id']),'l':str(order['location_id']),'w':str(order['warehouse_id']),'so':str(sales_order_id),'by':str(request.state.user_id) if hasattr(request.state,'user_id') else authenticate(request).user_id})
            for a in allocs:
                if str(a['lot_status']) != 'AVAILABLE' or str(a['qc_status']) != 'RELEASED':
                    raise HTTPException(409, f"lot {a['lot_code'] or a['packed_fg_lot_id']} is not dispatchable")
                conn.execute(text("""INSERT INTO dispatch_pick_lines(pick_line_id,pick_list_id,sales_order_line_id,sales_order_allocation_id,sku_id,packed_fg_lot_id,lot_code,allocated_qty,picked_qty,status)
                                    VALUES(:pl,:p,:sl,:aid,:s,:lot,:code,:q,0,'OPEN')"""), {'pl':str(uuid4()),'p':pick_id,'sl':str(a['sales_order_line_id']),'aid':str(a['sales_order_allocation_id']),'s':str(a['sku_id']),'lot':str(a['packed_fg_lot_id']),'code':a['lot_code'],'q':float(a['quantity'])})
        return {'pick_list_id': pick_id, 'sales_order_id': str(sales_order_id), 'status': 'OPEN', 'line_count': len(allocs)}

    @app.get('/v90af/pick-lists/{pick_list_id}')
    def get_pick_list(pick_list_id: UUID, request: Request):
        with engine.connect() as conn:
            pick = conn.execute(text('SELECT * FROM dispatch_pick_lists WHERE pick_list_id=:id'), {'id':str(pick_list_id)}).mappings().first()
            if not pick:
                raise HTTPException(404,'pick list not found')
        _require(engine, request, str(pick['entity_id']), str(pick['location_id']), False)
        with engine.connect() as conn:
            lines = conn.execute(text('SELECT * FROM dispatch_pick_lines WHERE pick_list_id=:id ORDER BY created_at'), {'id':str(pick_list_id)}).mappings().all()
        return {'pick_list':dict(pick), 'lines':[dict(x) for x in lines]}

    @app.post('/v90af/pick-lists/{pick_list_id}/confirm')
    def confirm_pick_list(pick_list_id: UUID, request: Request):
        with engine.connect() as conn:
            pick = conn.execute(text('SELECT * FROM dispatch_pick_lists WHERE pick_list_id=:id'), {'id':str(pick_list_id)}).mappings().first()
            if not pick:
                raise HTTPException(404,'pick list not found')
            lines = conn.execute(text('SELECT * FROM dispatch_pick_lines WHERE pick_list_id=:id'), {'id':str(pick_list_id)}).mappings().all()
        user = _require(engine, request, str(pick['entity_id']), str(pick['location_id']), True)
        if str(pick['status']) != 'OPEN':
            raise HTTPException(409, f"cannot confirm pick list in status {pick['status']}")
        if not lines:
            raise HTTPException(409,'pick list has no lines')
        with engine.begin() as conn:
            for line in lines:
                if float(line['allocated_qty']) <= 0:
                    raise HTTPException(409,'invalid allocated quantity')
                conn.execute(text("UPDATE dispatch_pick_lines SET picked_qty=allocated_qty,status='PICKED' WHERE pick_line_id=:id"), {'id':str(line['pick_line_id'])})
            conn.execute(text("UPDATE dispatch_pick_lists SET status='PICKED',picked_at=CURRENT_TIMESTAMP,confirmed_by=:u WHERE pick_list_id=:id"), {'u':str(user.user_id),'id':str(pick_list_id)})
            conn.execute(text("UPDATE sales_orders SET stock_status='PICKED' WHERE sales_order_id=:id"), {'id':str(pick['sales_order_id'])})
        return {'pick_list_id':str(pick_list_id),'status':'PICKED','sales_order_id':str(pick['sales_order_id'])}

    @app.get('/v90af/sales/orders/{sales_order_id}/dispatch-readiness')
    def dispatch_readiness(sales_order_id: UUID, request: Request):
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id':str(sales_order_id)}).mappings().first()
            if not order:
                raise HTTPException(404,'sales order not found')
            pick = conn.execute(text("SELECT * FROM dispatch_pick_lists WHERE sales_order_id=:id AND status='PICKED' ORDER BY picked_at DESC"), {'id':str(sales_order_id)}).mappings().first()
        _require(engine, request, str(order['entity_id']), str(order['location_id']), False)
        reasons=[]
        if str(order['status'])!='APPROVED': reasons.append('order_not_approved')
        if not pick: reasons.append('pick_list_not_confirmed')
        ready = not reasons
        return {'sales_order_id':str(sales_order_id),'dispatch_ready':ready,'reasons':reasons,'pick_list_id': str(pick['pick_list_id']) if pick else None}
