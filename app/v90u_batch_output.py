from __future__ import annotations
from decimal import Decimal
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def ensure_v90u_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS production_batch_output (
            output_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            good_qty NUMERIC NOT NULL DEFAULT 0,
            rework_qty NUMERIC NOT NULL DEFAULT 0,
            wastage_qty NUMERIC NOT NULL DEFAULT 0,
            uom TEXT NOT NULL,
            yield_pct NUMERIC NOT NULL DEFAULT 0,
            wastage_pct NUMERIC NOT NULL DEFAULT 0,
            notes TEXT NULL,
            recorded_by TEXT NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_batch_output_batch ON production_batch_output(batch_id)",
        "CREATE INDEX IF NOT EXISTS ix_batch_output_scope ON production_batch_output(entity_id, location_id, recorded_at)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class OutputIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    good_qty: float = Field(ge=0)
    rework_qty: float = Field(ge=0)
    wastage_qty: float = Field(ge=0)
    uom: str = Field(min_length=1, max_length=20)
    notes: str | None = None


def _require(engine, request: Request, entity_id: UUID, location_id: UUID):
    user = authenticate(request)
    if 'production.edit' not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _pct(num: Decimal, den: Decimal) -> Decimal:
    return (num * Decimal('100') / den) if den > 0 else Decimal('0')


def register_v90u_routes(app: FastAPI, engine) -> None:
    ensure_v90u_schema(engine)

    @app.post('/v90u/batches/{batch_id}/output')
    def record_output(batch_id: UUID, body: OutputIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id)
        if body.good_qty + body.rework_qty + body.wastage_qty <= 0:
            raise HTTPException(422, 'at least one output quantity must be greater than zero')
        with engine.connect() as conn:
            batch = conn.execute(text('SELECT * FROM production_batch WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not batch:
                raise HTTPException(404, 'batch not found')
            if str(batch['entity_id']) != str(body.entity_id) or str(batch['location_id']) != str(body.location_id):
                raise HTTPException(422, 'batch scope mismatch')
            if batch['status'] not in ('RUNNING', 'COMPLETED'):
                raise HTTPException(409, 'batch must be running or completed before output recording')
            existing = conn.execute(text('SELECT output_id FROM production_batch_output WHERE batch_id=:b'), {'b': str(batch_id)}).first()
            if existing:
                raise HTTPException(409, 'batch output already recorded; use correction workflow')
            # A released/process-QC rejection must never silently become accepted output.
            latest = conn.execute(text('SELECT decision FROM production_process_qc_decision WHERE batch_id=:b ORDER BY decided_at DESC, decision_id DESC'), {'b': str(batch_id)}).scalar()
            if latest == 'REJECT':
                raise HTTPException(409, 'batch has a rejected process QC decision')
            planned = Decimal(str(batch['planned_qty']))
            total = Decimal(str(body.good_qty + body.rework_qty + body.wastage_qty))
            if planned > 0 and total > planned * Decimal('1.25'):
                raise HTTPException(422, 'total output exceeds 125% of planned quantity')
            good = Decimal(str(body.good_qty)); rework = Decimal(str(body.rework_qty)); waste = Decimal(str(body.wastage_qty))
            yield_pct = _pct(good, total)
            wastage_pct = _pct(waste, total)
        oid = uuid4()
        with engine.begin() as conn:
            conn.execute(text('''INSERT INTO production_batch_output(
                output_id,batch_id,organization_id,entity_id,location_id,good_qty,rework_qty,wastage_qty,uom,yield_pct,wastage_pct,notes,recorded_by)
                VALUES(:id,:b,:o,:e,:l,:g,:r,:w,:u,:yp,:wp,:n,:by)'''), {
                'id': str(oid), 'b': str(batch_id), 'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id),
                'g': body.good_qty, 'r': body.rework_qty, 'w': body.wastage_qty, 'u': body.uom,
                'yp': float(yield_pct), 'wp': float(wastage_pct), 'n': body.notes, 'by': str(user.user_id)
            })
        return {'output_id': str(oid), 'batch_id': str(batch_id), 'good_qty': body.good_qty, 'rework_qty': body.rework_qty,
                'wastage_qty': body.wastage_qty, 'yield_pct': float(yield_pct), 'wastage_pct': float(wastage_pct), 'status': 'RECORDED'}

    @app.get('/v90u/batches/{batch_id}/output')
    def get_output(batch_id: UUID, request: Request):
        user = authenticate(request)
        if 'production.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM production_batch_output WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            batch = conn.execute(text('SELECT entity_id,location_id,planned_qty,uom,status FROM production_batch WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not batch:
                raise HTTPException(404, 'batch not found')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(batch['entity_id']), str(batch['location_id']))
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
        return {'batch_id': str(batch_id), 'planned_qty': float(batch['planned_qty']), 'uom': batch['uom'],
                'batch_status': batch['status'], 'output': dict(row) if row else None}

    @app.get('/v90u/batches/{batch_id}/closure-readiness')
    def closure_readiness(batch_id: UUID, request: Request):
        user = authenticate(request)
        if 'production.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            batch = conn.execute(text('SELECT entity_id,location_id,status FROM production_batch WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            if not batch:
                raise HTTPException(404, 'batch not found')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(batch['entity_id']), str(batch['location_id']))
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
            output = conn.execute(text('SELECT * FROM production_batch_output WHERE batch_id=:b'), {'b': str(batch_id)}).mappings().first()
            latest_qc = conn.execute(text('SELECT decision FROM production_process_qc_decision WHERE batch_id=:b ORDER BY decided_at DESC, decision_id DESC'), {'b': str(batch_id)}).scalar()
        has_output = output is not None
        qc_ok = latest_qc not in ('HOLD', 'REJECT')
        ready = has_output and qc_ok
        return {'batch_id': str(batch_id), 'ready_to_close': ready, 'has_output': has_output,
                'latest_qc_decision': latest_qc, 'reason': None if ready else ('output_missing' if not has_output else 'qc_not_clear')}
