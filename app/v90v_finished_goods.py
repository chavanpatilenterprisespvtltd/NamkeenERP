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


def ensure_v90v_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS finished_goods_lot (
            fg_lot_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            product_master_id TEXT NOT NULL,
            sku_id TEXT NULL,
            fg_lot_code TEXT NOT NULL,
            mfg_date TEXT NOT NULL,
            expiry_date TEXT NULL,
            quantity NUMERIC NOT NULL,
            available_qty NUMERIC NOT NULL,
            uom TEXT NOT NULL,
            qc_status TEXT NOT NULL DEFAULT 'RELEASED',
            status TEXT NOT NULL DEFAULT 'AVAILABLE',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_fg_lot_batch ON finished_goods_lot(batch_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_fg_lot_code ON finished_goods_lot(organization_id, entity_id, fg_lot_code)",
        "CREATE INDEX IF NOT EXISTS ix_fg_lot_scope ON finished_goods_lot(entity_id, location_id, warehouse_id, product_master_id)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class FGReceiptIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID
    fg_lot_code: str = Field(min_length=1, max_length=80)
    sku_id: UUID | None = None
    mfg_date: str | None = None
    expiry_date: str | None = None
    notes: str | None = None


def _require(engine, request: Request, entity_id: UUID, location_id: UUID):
    user = authenticate(request)
    if 'inventory.edit' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _warehouse_ok(engine, warehouse_id: UUID, entity_id: UUID, location_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT warehouse_id FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"),
                           {'w': str(warehouse_id), 'e': str(entity_id), 'l': str(location_id)}).first()
    if not row:
        raise HTTPException(422, 'warehouse not found in entity/location scope')


def register_v90v_routes(app: FastAPI, engine) -> None:
    ensure_v90v_schema(engine)

    @app.post('/v90v/batches/{batch_id}/fg')
    def create_fg_receipt(batch_id: UUID, body: FGReceiptIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id)
        _warehouse_ok(engine, body.warehouse_id, body.entity_id, body.location_id)
        with engine.connect() as conn:
            batch = conn.execute(text('SELECT * FROM production_batch WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not batch:
                raise HTTPException(404, 'batch not found')
            if str(batch['entity_id']) != str(body.entity_id) or str(batch['location_id']) != str(body.location_id):
                raise HTTPException(422, 'batch scope mismatch')
            if batch['status'] != 'COMPLETED':
                raise HTTPException(409, 'batch must be completed before FG receipt')
            output = conn.execute(text('SELECT * FROM production_batch_output WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not output:
                raise HTTPException(409, 'batch output is required before FG receipt')
            if float(output['good_qty']) <= 0:
                raise HTTPException(409, 'good output is zero; no FG can be created')
            qc = conn.execute(text("SELECT decision FROM production_process_qc_decision WHERE batch_id=:b ORDER BY decided_at DESC, decision_id DESC"), {'b': str(batch_id)}).scalar()
            if qc in ('HOLD', 'REJECT'):
                raise HTTPException(409, 'batch QC is not released for FG receipt')
            existing = conn.execute(text('SELECT fg_lot_id FROM finished_goods_lot WHERE batch_id=:b'), {'b': str(batch_id)}).first()
            if existing:
                raise HTTPException(409, 'finished goods already created for batch')
            code_exists = conn.execute(text('SELECT 1 FROM finished_goods_lot WHERE organization_id=:o AND entity_id=:e AND fg_lot_code=:c'),
                                       {'o': str(body.organization_id), 'e': str(body.entity_id), 'c': body.fg_lot_code}).first()
            if code_exists:
                raise HTTPException(409, 'FG lot code already exists')
            if body.sku_id:
                # SKU is optional at this stage; validate that it exists in the reusable master hierarchy when supplied.
                sku = conn.execute(text("SELECT master_id FROM master_record WHERE master_id=:s AND organization_id=:o AND master_type='SKU' AND active=1"),
                                   {'s': str(body.sku_id), 'o': str(body.organization_id)}).first()
                if not sku:
                    raise HTTPException(422, 'SKU not found in product master')
            qty = float(output['good_qty'])
            product_master_id = str(batch['product_master_id'])
            mfg_date = body.mfg_date or _now()
            fg_lot_id = uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO finished_goods_lot(
                fg_lot_id,organization_id,entity_id,location_id,warehouse_id,batch_id,product_master_id,sku_id,fg_lot_code,
                mfg_date,expiry_date,quantity,available_qty,uom,qc_status,status,created_by)
                VALUES(:id,:o,:e,:l,:w,:b,:p,:s,:c,:mfg,:exp,:q,:q,:u,'RELEASED','AVAILABLE',:by)"""), {
                'id': str(fg_lot_id), 'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id),
                'w': str(body.warehouse_id), 'b': str(batch_id), 'p': product_master_id, 's': str(body.sku_id) if body.sku_id else None,
                'c': body.fg_lot_code, 'mfg': mfg_date, 'exp': body.expiry_date, 'q': qty, 'u': str(output['uom']), 'by': str(user.user_id)
            })
            conn.execute(text("""INSERT INTO inventory_stock_ledger(
                movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by)
                VALUES(:id,:o,:e,:l,:w,:m,:lot,'FG_RECEIPT',:q,:u,'PRODUCTION_BATCH',:b,'POSTED',:by)"""), {
                'id': str(uuid4()), 'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id),
                'w': str(body.warehouse_id), 'm': product_master_id, 'lot': str(fg_lot_id), 'q': qty,
                'u': str(output['uom']), 'b': str(batch_id), 'by': str(user.user_id)
            })
            conn.execute(text("""INSERT INTO inventory_stock_balance(
                organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty,updated_at)
                VALUES(:o,:e,:l,:w,:m,:u,:q,CURRENT_TIMESTAMP)
                ON CONFLICT(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom)
                DO UPDATE SET available_qty=inventory_stock_balance.available_qty+excluded.available_qty, updated_at=CURRENT_TIMESTAMP"""), {
                'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id), 'w': str(body.warehouse_id),
                'm': product_master_id, 'u': str(output['uom']), 'q': qty
            })
        return {'fg_lot_id': str(fg_lot_id), 'batch_id': str(batch_id), 'fg_lot_code': body.fg_lot_code,
                'quantity': qty, 'available_qty': qty, 'uom': str(output['uom']), 'status': 'AVAILABLE', 'qc_status': 'RELEASED'}

    @app.get('/v90v/fg/{fg_lot_id}')
    def get_fg(fg_lot_id: UUID, request: Request):
        user = authenticate(request)
        if 'inventory.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM finished_goods_lot WHERE fg_lot_id=:id'), {'id': str(fg_lot_id)}).mappings().first()
            if not row:
                raise HTTPException(404, 'FG lot not found')
        try:
            assert_entity_location_allowed(engine, user.user_id, str(row['entity_id']), str(row['location_id']))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {'fg_lot': dict(row)}

    @app.get('/v90v/fg')
    def list_fg(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID | None = None):
        user = authenticate(request)
        if 'inventory.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        try:
            assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        sql = 'SELECT * FROM finished_goods_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        params = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        if warehouse_id:
            sql += ' AND warehouse_id=:w'; params['w'] = str(warehouse_id)
        sql += ' ORDER BY created_at DESC, fg_lot_id DESC'
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return {'items': [dict(x) for x in rows], 'count': len(rows)}
