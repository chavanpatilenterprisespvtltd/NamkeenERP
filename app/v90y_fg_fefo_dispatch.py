from __future__ import annotations
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _today() -> str:
    return date.today().isoformat()


def ensure_v90y_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS fg_fefo_allocation (
            allocation_id TEXT PRIMARY KEY,
            allocation_group_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            packed_fg_lot_id TEXT NOT NULL,
            lot_code TEXT NULL,
            reference_type TEXT NULL,
            reference_id TEXT NULL,
            quantity NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            allocated_by TEXT NOT NULL,
            allocated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            released_at TEXT NULL,
            release_reason TEXT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_fg_fefo_alloc_scope ON fg_fefo_allocation(entity_id,location_id,warehouse_id,sku_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_fg_fefo_alloc_lot ON fg_fefo_allocation(packed_fg_lot_id,status)",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


class FEFOAllocationLine(BaseModel):
    packed_fg_lot_id: UUID
    quantity: float = Field(gt=0)


class FEFOAllocationCreate(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID
    sku_id: UUID
    quantity: float = Field(gt=0)
    reference_type: str | None = Field(default=None, max_length=50)
    reference_id: str | None = Field(default=None, max_length=120)


def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write: bool):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'inventory.edit' if write else 'inventory.view'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _warehouse_ok(engine, warehouse_id: UUID, entity_id: UUID, location_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("""SELECT warehouse_id FROM erp_warehouses
            WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"""),
            {'w': str(warehouse_id), 'e': str(entity_id), 'l': str(location_id)}).first()
    if not row:
        raise HTTPException(422, 'warehouse not found in entity/location scope')


def _allocated_for_lot(engine, lot_id: str) -> float:
    with engine.connect() as conn:
        return float(conn.execute(text("""SELECT COALESCE(SUM(quantity),0) FROM fg_fefo_allocation
            WHERE packed_fg_lot_id=:l AND status='OPEN'"""), {'l': lot_id}).scalar() or 0)


def register_v90y_routes(app: FastAPI, engine) -> None:
    ensure_v90y_schema(engine)

    @app.get('/v90y/fg/fefo-preview')
    def fefo_preview(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID,
                     warehouse_id: UUID, sku_id: UUID, quantity: float):
        _require(engine, request, entity_id, location_id, False)
        _warehouse_ok(engine, warehouse_id, entity_id, location_id)
        if quantity <= 0:
            raise HTTPException(422, 'quantity must be greater than zero')
        with engine.connect() as conn:
            rows = conn.execute(text("""SELECT packed_fg_lot_id, lot_code, expiry_date, available_qty,
                mfg_date, status, qc_status FROM packed_fg_lot
                WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w
                  AND sku_id=:s AND status='AVAILABLE' AND qc_status='RELEASED' AND available_qty>0
                ORDER BY CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END,
                         CASE WHEN expiry_date < :today THEN 2 ELSE 0 END,
                         expiry_date, mfg_date, created_at"""),
                {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id), 'w': str(warehouse_id),
                 's': str(sku_id), 'today': _today()}).mappings().all()
        remaining = quantity
        allocation = []
        for row in rows:
            reserved = _allocated_for_lot(engine, str(row['packed_fg_lot_id']))
            free = max(float(row['available_qty']) - reserved, 0.0)
            if free <= 0:
                continue
            take = min(remaining, free)
            allocation.append({
                'packed_fg_lot_id': str(row['packed_fg_lot_id']),
                'lot_code': row['lot_code'],
                'expiry_date': row['expiry_date'],
                'mfg_date': row['mfg_date'],
                'available_qty': float(row['available_qty']),
                'already_allocated_qty': reserved,
                'allocatable_qty': free,
                'quantity': take,
            })
            remaining -= take
            if remaining <= 0:
                break
        return {'requested_qty': quantity, 'allocated_qty': quantity - remaining,
                'short_qty': max(remaining, 0), 'fefo': allocation,
                'expired_lots_excluded': True}

    @app.post('/v90y/fg/allocations')
    def create_allocation(body: FEFOAllocationCreate, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        _warehouse_ok(engine, body.warehouse_id, body.entity_id, body.location_id)
        preview = fefo_preview(request, body.organization_id, body.entity_id, body.location_id,
                               body.warehouse_id, body.sku_id, body.quantity)
        if preview['short_qty'] > 0:
            raise HTTPException(409, f'insufficient releasable FEFO stock: {preview["short_qty"]}')
        allocation_group_id = uuid4()
        with engine.begin() as conn:
            for line in preview['fefo']:
                allocation_id = uuid4()
                conn.execute(text("""INSERT INTO fg_fefo_allocation(
                    allocation_id,allocation_group_id,organization_id,entity_id,location_id,warehouse_id,sku_id,packed_fg_lot_id,lot_code,
                    reference_type,reference_id,quantity,status,allocated_by)
                    VALUES(:id,:gid,:o,:e,:l,:w,:s,:lot,:lotcode,:rt,:ri,:q,'OPEN',:by)"""), {
                    'id': str(allocation_id), 'gid': str(allocation_group_id), 'o': str(body.organization_id), 'e': str(body.entity_id),
                    'l': str(body.location_id), 'w': str(body.warehouse_id), 's': str(body.sku_id),
                    'lot': line['packed_fg_lot_id'], 'lotcode': line['lot_code'], 'rt': body.reference_type, 'ri': body.reference_id,
                    'q': line['quantity'], 'by': str(user.user_id)})
        return {'allocation_group_id': str(allocation_group_id), 'status': 'OPEN',
                'requested_qty': body.quantity, 'allocated_qty': body.quantity,
                'lines': preview['fefo']}

    @app.post('/v90y/fg/allocations/{allocation_group_id}/release')
    def release_allocation(allocation_group_id: UUID, request: Request, reason: str = ''):
        user = authenticate(request)
        if 'inventory.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT allocation_id, entity_id, location_id, status FROM fg_fefo_allocation WHERE allocation_group_id=:id"),
                                {'id': str(allocation_group_id)}).mappings().all()
            if not rows:
                raise HTTPException(404, 'allocation not found')
            if any(r['status'] != 'OPEN' for r in rows):
                raise HTTPException(409, 'allocation is not fully open')
            for r in rows:
                try:
                    assert_entity_location_allowed(engine, user.user_id, str(r['entity_id']), str(r['location_id']))
                except PermissionError as exc:
                    raise HTTPException(403, str(exc)) from exc
            conn.execute(text("UPDATE fg_fefo_allocation SET status='RELEASED', released_at=CURRENT_TIMESTAMP, release_reason=:reason WHERE allocation_group_id=:id"),
                         {'reason': reason, 'id': str(allocation_group_id)})
        return {'allocation_group_id': str(allocation_group_id), 'status': 'RELEASED', 'released_by': str(user.user_id)}

    @app.get('/v90y/fg/allocations')
    def list_allocations(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID,
                         warehouse_id: UUID | None = None, sku_id: UUID | None = None, status: str | None = None):
        _require(engine, request, entity_id, location_id, False)
        sql = "SELECT * FROM fg_fefo_allocation WHERE organization_id=:o AND entity_id=:e AND location_id=:l"
        params = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        if warehouse_id:
            sql += ' AND warehouse_id=:w'; params['w'] = str(warehouse_id)
        if sku_id:
            sql += ' AND sku_id=:s'; params['s'] = str(sku_id)
        if status:
            sql += ' AND status=:st'; params['st'] = status
        sql += ' ORDER BY allocated_at DESC'
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return {'items': [dict(r) for r in rows]}

    @app.get('/v90y/fg/lots/{packed_fg_lot_id}/dispatch-readiness')
    def dispatch_readiness(packed_fg_lot_id: UUID, request: Request):
        user = authenticate(request)
        if 'inventory.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM packed_fg_lot WHERE packed_fg_lot_id=:id'), {'id': str(packed_fg_lot_id)}).mappings().first()
            if not row:
                raise HTTPException(404, 'packed FG lot not found')
            allocated = float(conn.execute(text("SELECT COALESCE(SUM(quantity),0) FROM fg_fefo_allocation WHERE packed_fg_lot_id=:id AND status='OPEN'"), {'id': str(packed_fg_lot_id)}).scalar() or 0)
        try:
            assert_entity_location_allowed(engine, user.user_id, str(row['entity_id']), str(row['location_id']))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        exp = row['expiry_date']
        expired = bool(exp and str(exp) < _today())
        releasable = row['status'] == 'AVAILABLE' and row['qc_status'] == 'RELEASED' and not expired
        free = max(float(row['available_qty']) - allocated, 0.0) if releasable else 0.0
        reasons = []
        if row['status'] != 'AVAILABLE': reasons.append('not_available')
        if row['qc_status'] != 'RELEASED': reasons.append('qc_not_released')
        if expired: reasons.append('expired')
        if free <= 0: reasons.append('no_free_quantity')
        return {'packed_fg_lot_id': str(packed_fg_lot_id), 'dispatch_ready': free > 0,
                'available_qty': float(row['available_qty']), 'allocated_qty': allocated,
                'free_qty': free, 'expired': expired, 'reasons': reasons}
