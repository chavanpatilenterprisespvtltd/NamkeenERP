from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _require(engine, request: Request, perm: str, entity_id: str, location_id: str | None):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _credit_review(engine, order):
    from .v90ac_credit_payment import _policy, _approved_sales_outstanding, _overdue_amount
    policy = _policy(engine, str(order['organization_id']), str(order['entity_id']), str(order['customer_id']))
    outstanding = _approved_sales_outstanding(engine, str(order['entity_id']), str(order['customer_id']))
    if not policy:
        return {'status': 'HOLD', 'reason': 'no approved credit policy', 'credit_limit': 0.0,
                'credit_days': 0, 'current_outstanding': outstanding, 'overdue_amount': 0.0,
                'available_credit': -float(order['grand_total'])}
    limit = float(policy['credit_limit']); days = int(policy['credit_days'])
    overdue = _overdue_amount(engine, str(order['entity_id']), str(order['customer_id']), days)
    available = limit - outstanding
    if overdue > 0:
        status, reason = 'HOLD', 'customer has overdue outstanding'
    elif float(order['grand_total']) > available:
        status, reason = 'HOLD', 'order exceeds available credit'
    else:
        status, reason = 'PASS', ''
    return {'status': status, 'reason': reason, 'credit_limit': limit, 'credit_days': days,
            'current_outstanding': outstanding, 'overdue_amount': overdue, 'available_credit': available}


def ensure_v90ad_schema(engine):
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS sales_order_control_reviews (
            control_review_id TEXT PRIMARY KEY,
            sales_order_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            pricing_status TEXT NOT NULL,
            credit_status TEXT NOT NULL,
            stock_status TEXT NOT NULL,
            overall_status TEXT NOT NULL,
            reason TEXT,
            checked_by TEXT NOT NULL,
            checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_order_control_reviews_order ON sales_order_control_reviews(sales_order_id, checked_at)"))


def register_v90ad_routes(app: FastAPI, engine):
    ensure_v90ad_schema(engine)

    @app.post('/v90ad/sales/orders/{sales_order_id}/control-check')
    def control_check(sales_order_id: UUID, request: Request):
        user = authenticate(request)
        if 'sales.edit' not in permissions_for_user(engine, user.user_id) and 'sales.approve' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
        if not order:
            raise HTTPException(404, 'sales order not found')
        try:
            assert_entity_location_allowed(engine, user.user_id, str(order['entity_id']), str(order['location_id']))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

        pricing = str(order['pricing_status'])
        credit = _credit_review(engine, order)
        stock = str(order['stock_status'])
        if pricing not in {'CHECKED', 'APPROVED', 'OK', 'PASS'}:
            pricing_status, pricing_reason = 'HOLD', 'pricing control not cleared'
        else:
            pricing_status, pricing_reason = 'PASS', ''
        stock_status = 'PASS' if stock in {'READY', 'CHECKED', 'AVAILABLE'} else 'HOLD'
        reasons = [x for x in (pricing_reason, credit['reason'] if credit['status'] == 'HOLD' else '',
                               '' if stock_status == 'PASS' else 'stock allocation not ready') if x]
        overall = 'PASS' if pricing_status == 'PASS' and credit['status'] == 'PASS' and stock_status == 'PASS' else 'HOLD'
        reason = '; '.join(reasons)
        rid = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO sales_order_control_reviews
                (control_review_id,sales_order_id,organization_id,entity_id,location_id,pricing_status,credit_status,stock_status,overall_status,reason,checked_by)
                VALUES(:id,:so,:o,:e,:l,:p,:c,:s,:overall,:reason,:u)"""), {
                'id': rid, 'so': str(sales_order_id), 'o': str(order['organization_id']), 'e': str(order['entity_id']),
                'l': str(order['location_id']), 'p': pricing_status, 'c': credit['status'], 's': stock_status,
                'overall': overall, 'reason': reason, 'u': str(user.user_id)})
            conn.execute(text("""UPDATE sales_orders SET pricing_status=:p, credit_status=:c, stock_status=:s,
                hold_reason=CASE WHEN :overall='HOLD' THEN :reason ELSE NULL END
                WHERE sales_order_id=:id"""), {'p': pricing_status, 'c': credit['status'], 's': 'READY' if stock_status == 'PASS' else 'HOLD',
                    'overall': overall, 'reason': reason, 'id': str(sales_order_id)})
        return {'sales_order_id': str(sales_order_id), 'overall_status': overall,
                'pricing_status': pricing_status, 'credit_status': credit['status'],
                'stock_status': 'READY' if stock_status == 'PASS' else 'HOLD',
                'reason': reason, 'control_review_id': rid, 'credit': credit}

    @app.post('/v90ad/sales/orders/{sales_order_id}/approve-controlled')
    def approve_controlled(sales_order_id: UUID, request: Request):
        user = authenticate(request)
        if 'sales.approve' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
        if not order:
            raise HTTPException(404, 'sales order not found')
        try:
            assert_entity_location_allowed(engine, user.user_id, str(order['entity_id']), str(order['location_id']))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        if order['status'] != 'SUBMITTED':
            raise HTTPException(409, f"cannot approve order in status {order['status']}")
        # Re-check at approval time, not only at submission time.
        with engine.begin() as conn:
            row = conn.execute(text('SELECT * FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
        check = _credit_review(engine, row)
        pricing_ok = str(row['pricing_status']) in {'CHECKED', 'APPROVED', 'OK', 'PASS'}
        stock_ok = str(row['stock_status']) in {'READY', 'CHECKED', 'AVAILABLE'}
        if not pricing_ok or check['status'] != 'PASS' or not stock_ok:
            reason = '; '.join([x for x in [
                '' if pricing_ok else 'pricing control not cleared',
                check['reason'] if check['status'] == 'HOLD' else '',
                '' if stock_ok else 'stock allocation not ready'] if x])
            with engine.begin() as conn:
                conn.execute(text("UPDATE sales_orders SET status='HOLD', credit_status=:c, hold_reason=:r WHERE sales_order_id=:id"),
                             {'c': check['status'], 'r': reason or 'commercial control failed', 'id': str(sales_order_id)})
            raise HTTPException(409, reason or 'commercial control failed')
        with engine.begin() as conn:
            conn.execute(text("""UPDATE sales_orders SET status='APPROVED', credit_status='CHECKED',
                stock_status='READY', approved_by=:u, approved_at=CURRENT_TIMESTAMP, hold_reason=NULL
                WHERE sales_order_id=:id"""), {'u': str(user.user_id), 'id': str(sales_order_id)})
        return {'sales_order_id': str(sales_order_id), 'status': 'APPROVED', 'credit_status': 'CHECKED', 'stock_status': 'READY'}

    @app.get('/v90ad/sales/orders/{sales_order_id}/control-history')
    def control_history(sales_order_id: UUID, request: Request):
        user = authenticate(request)
        if 'sales.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            order = conn.execute(text('SELECT entity_id,location_id FROM sales_orders WHERE sales_order_id=:id'), {'id': str(sales_order_id)}).mappings().first()
            if not order: raise HTTPException(404, 'sales order not found')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(order['entity_id']), str(order['location_id']))
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
            rows = conn.execute(text('SELECT * FROM sales_order_control_reviews WHERE sales_order_id=:id ORDER BY checked_at DESC'), {'id': str(sales_order_id)}).mappings().all()
        return {'items': [dict(r) for r in rows]}
