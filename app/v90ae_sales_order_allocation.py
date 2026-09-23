from __future__ import annotations
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed
from .v90y_fg_fefo_dispatch import _allocated_for_lot, _today, _warehouse_ok


def ensure_v90ae_schema(engine):
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS sales_order_allocations (
            sales_order_allocation_id TEXT PRIMARY KEY,
            sales_order_id TEXT NOT NULL,
            sales_order_line_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            packed_fg_lot_id TEXT NOT NULL,
            lot_code TEXT NULL,
            quantity NUMERIC NOT NULL,
            fg_allocation_group_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ALLOCATED',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            released_at TEXT NULL,
            release_reason TEXT NULL
        )"""))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_so_alloc_line_lot ON sales_order_allocations(sales_order_line_id, packed_fg_lot_id, status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_so_alloc_order ON sales_order_allocations(sales_order_id,status)"))


def _require(engine, request: Request, entity_id: str, location_id: str):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    if 'inventory.edit' not in perms and 'sales.edit' not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def register_v90ae_routes(app: FastAPI, engine):
    ensure_v90ae_schema(engine)

    @app.post('/v90ae/sales/orders/{sales_order_id}/allocate')
    def allocate_order(sales_order_id: UUID, request: Request):
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
            if not order:
                raise HTTPException(404, 'sales order not found')
            lines = conn.execute(text('SELECT * FROM sales_order_lines WHERE sales_order_id=:id ORDER BY sales_order_line_id'), {'id': str(sales_order_id)}).mappings().all()
        user = _require(engine, request, str(order['entity_id']), str(order['location_id']))
        _warehouse_ok(engine, UUID(str(order['warehouse_id'])), UUID(str(order['entity_id'])), UUID(str(order['location_id'])))
        if str(order['status']) != 'APPROVED':
            raise HTTPException(409, f"cannot allocate order in status {order['status']}")
        if not lines:
            raise HTTPException(409, 'sales order has no lines')

        created = []
        shortages = []
        for line in lines:
            already = 0.0
            with engine.connect() as conn:
                already = float(conn.execute(text("""SELECT COALESCE(SUM(quantity),0) FROM sales_order_allocations
                    WHERE sales_order_line_id=:line AND status='ALLOCATED'"""), {'line': str(line['sales_order_line_id'])}).scalar() or 0)
            remaining_qty = max(float(line['quantity']) - already, 0.0)
            if remaining_qty <= 0:
                continue
            with engine.connect() as conn:
                rows = conn.execute(text("""SELECT packed_fg_lot_id, lot_code, expiry_date, available_qty, mfg_date, status, qc_status
                    FROM packed_fg_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND sku_id=:s
                      AND status='AVAILABLE' AND qc_status='RELEASED' AND available_qty>0
                    ORDER BY CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END, expiry_date, mfg_date, created_at"""), {
                    'o': str(order['organization_id']), 'e': str(order['entity_id']), 'l': str(order['location_id']), 'w': str(order['warehouse_id']), 's': str(line['sku_id'])
                }).mappings().all()
            remaining = remaining_qty
            group_id = uuid4()
            for row in rows:
                if remaining <= 0:
                    break
                exp = row['expiry_date']
                if exp and str(exp) < _today():
                    continue
                reserved = _allocated_for_lot(engine, str(row['packed_fg_lot_id']))
                free = max(float(row['available_qty']) - reserved, 0.0)
                if free <= 0:
                    continue
                take = min(remaining, free)
                with engine.begin() as conn:
                    aid = str(uuid4())
                    conn.execute(text("""INSERT INTO fg_fefo_allocation(
                        allocation_id,allocation_group_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,
                        reference_type,reference_id,quantity,status,allocated_by)
                        VALUES(:id,:gid,:o,:e,:l,:w,:s,:lot,:code,'SALES_ORDER',:ref,:q,'OPEN',:by)"""), {
                        'id': aid, 'gid': str(group_id), 'o': str(order['organization_id']), 'e': str(order['entity_id']), 'l': str(order['location_id']),
                        'w': str(order['warehouse_id']), 's': str(line['sku_id']), 'lot': str(row['packed_fg_lot_id']), 'code': row['lot_code'],
                        'ref': str(sales_order_id), 'q': take, 'by': str(user.user_id)
                    })
                    conn.execute(text("""INSERT INTO sales_order_allocations(
                        sales_order_allocation_id,sales_order_id,sales_order_line_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,quantity,fg_allocation_group_id,status,created_by)
                        VALUES(:id,:so,:line,:o,:e,:l,:w,:s,:lot,:code,:q,:gid,'ALLOCATED',:by)"""), {
                        'id': str(uuid4()), 'so': str(sales_order_id), 'line': str(line['sales_order_line_id']), 'o': str(order['organization_id']), 'e': str(order['entity_id']),
                        'l': str(order['location_id']), 'w': str(order['warehouse_id']), 's': str(line['sku_id']), 'lot': str(row['packed_fg_lot_id']), 'code': row['lot_code'],
                        'q': take, 'gid': str(group_id), 'by': str(user.user_id)
                    })
                created.append({'sales_order_line_id': str(line['sales_order_line_id']), 'packed_fg_lot_id': str(row['packed_fg_lot_id']), 'lot_code': row['lot_code'], 'quantity': take, 'allocation_group_id': str(group_id)})
                remaining -= take
            if remaining > 0:
                shortages.append({'sales_order_line_id': str(line['sales_order_line_id']), 'requested_qty': float(line['quantity']), 'already_allocated_qty': already, 'short_qty': remaining})

        overall = 'ALLOCATED' if not shortages else ('PARTIAL' if created else 'HOLD')
        with engine.begin() as conn:
            conn.execute(text("UPDATE sales_orders SET stock_status=:s, hold_reason=CASE WHEN :s='HOLD' THEN 'insufficient releasable stock' WHEN :s='PARTIAL' THEN 'partial stock allocation' ELSE NULL END WHERE sales_order_id=:id"), {'s': 'READY' if overall == 'ALLOCATED' else overall, 'id': str(sales_order_id)})
        return {'sales_order_id': str(sales_order_id), 'status': overall, 'allocated_lines': created, 'shortages': shortages}

    @app.get('/v90ae/sales/orders/{sales_order_id}/allocation')
    def order_allocation(sales_order_id: UUID, request: Request):
        user = authenticate(request)
        if 'inventory.view' not in permissions_for_user(engine, user.user_id) and 'sales.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            order = conn.execute(text('SELECT entity_id,location_id FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
            if not order: raise HTTPException(404, 'sales order not found')
            try: assert_entity_location_allowed(engine, user.user_id, str(order['entity_id']), str(order['location_id']))
            except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
            rows = conn.execute(text('SELECT * FROM sales_order_allocations WHERE sales_order_id=:id ORDER BY created_at'), {'id': str(sales_order_id)}).mappings().all()
        return {'sales_order_id': str(sales_order_id), 'items': [dict(r) for r in rows]}

    @app.post('/v90ae/sales/orders/{sales_order_id}/allocation/release')
    def release_order_allocation(sales_order_id: UUID, request: Request, reason: str = ''):
        user = authenticate(request)
        if 'inventory.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            order = conn.execute(text('SELECT entity_id,location_id FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
            if not order: raise HTTPException(404, 'sales order not found')
        try: assert_entity_location_allowed(engine, user.user_id, str(order['entity_id']), str(order['location_id']))
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT fg_allocation_group_id FROM sales_order_allocations WHERE sales_order_id=:id AND status='ALLOCATED'"), {'id': str(sales_order_id)}).mappings().all()
            for r in rows:
                conn.execute(text("UPDATE fg_fefo_allocation SET status='RELEASED', released_at=CURRENT_TIMESTAMP, release_reason=:reason WHERE allocation_group_id=:gid AND status='OPEN'"), {'gid': r['fg_allocation_group_id'], 'reason': reason})
            conn.execute(text("UPDATE sales_order_allocations SET status='RELEASED', released_at=CURRENT_TIMESTAMP, release_reason=:reason WHERE sales_order_id=:id AND status='ALLOCATED'"), {'id': str(sales_order_id), 'reason': reason})
            conn.execute(text("UPDATE sales_orders SET stock_status='HOLD', hold_reason=:reason WHERE sales_order_id=:id"), {'id': str(sales_order_id), 'reason': reason or 'sales allocation released'})
        return {'sales_order_id': str(sales_order_id), 'status': 'RELEASED', 'released_by': str(user.user_id)}
