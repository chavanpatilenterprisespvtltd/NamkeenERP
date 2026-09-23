from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now(): return datetime.now(timezone.utc).isoformat()


def ensure_v90x_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS packing_qc_inspection (
            inspection_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            packing_run_id TEXT NOT NULL,
            packed_fg_lot_id TEXT NOT NULL,
            net_weight_target NUMERIC NULL,
            net_weight_actual NUMERIC NULL,
            weight_tolerance_pct NUMERIC NULL,
            seal_status TEXT NULL,
            label_status TEXT NULL,
            nitrogen_status TEXT NULL,
            visual_status TEXT NULL,
            overall_status TEXT NOT NULL DEFAULT 'PENDING',
            hold_reason TEXT NULL,
            released_by TEXT NULL,
            released_at TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(packing_run_id, packed_fg_lot_id)
        )""",
        """CREATE TABLE IF NOT EXISTS packing_qc_checks (
            check_id TEXT PRIMARY KEY,
            inspection_id TEXT NOT NULL,
            parameter TEXT NOT NULL,
            observed_value TEXT NULL,
            status TEXT NOT NULL,
            remarks TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(inspection_id) REFERENCES packing_qc_inspection(inspection_id)
        )""",
        """CREATE INDEX IF NOT EXISTS ix_packing_qc_scope ON packing_qc_inspection(entity_id,location_id,warehouse_id,overall_status)""",
        """CREATE INDEX IF NOT EXISTS ix_packing_qc_lot ON packing_qc_inspection(packed_fg_lot_id)""",
    ]
    with engine.begin() as c:
        for s in stmts: c.execute(text(s))


class PackingQCCheck(BaseModel):
    parameter: str = Field(min_length=1, max_length=80)
    observed_value: str | None = Field(default=None, max_length=200)
    status: str = Field(pattern=r"^(PASS|FAIL|NA)$")
    remarks: str | None = Field(default=None, max_length=500)


class PackingQCCreate(BaseModel):
    net_weight_target: float | None = Field(default=None, gt=0)
    net_weight_actual: float | None = Field(default=None, gt=0)
    weight_tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    seal_status: str | None = Field(default=None, pattern=r"^(PASS|FAIL|NA)$")
    label_status: str | None = Field(default=None, pattern=r"^(PASS|FAIL|NA)$")
    nitrogen_status: str | None = Field(default=None, pattern=r"^(PASS|FAIL|NA)$")
    visual_status: str | None = Field(default=None, pattern=r"^(PASS|FAIL|NA)$")
    checks: list[PackingQCCheck] = Field(default_factory=list)
    hold_reason: str | None = None


def _auth_scope(engine, request: Request, entity_id: str, location_id: str):
    u = authenticate(request)
    p = permissions_for_user(engine, u.user_id)
    if 'inventory.edit' not in p and 'production.edit' not in p:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, u.user_id, entity_id, location_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return u


def register_v90x_routes(app: FastAPI, engine):
    ensure_v90x_schema(engine)

    @app.post('/v90x/packing-runs/{packing_run_id}/qc')
    def create_or_update_qc(packing_run_id: UUID, body: PackingQCCreate, request: Request):
        with engine.connect() as c:
            run = c.execute(text("SELECT * FROM packing_run WHERE packing_run_id=:id"), {'id': str(packing_run_id)}).mappings().first()
        if not run:
            raise HTTPException(404, 'packing run not found')
        user = _auth_scope(engine, request, str(run['entity_id']), str(run['location_id']))
        with engine.connect() as c:
            lot = c.execute(text("SELECT * FROM packed_fg_lot WHERE packing_run_id=:r"), {'r': str(packing_run_id)}).mappings().first()
        if not lot:
            raise HTTPException(409, 'packing run must be completed before packing QC')

        statuses = [body.seal_status, body.label_status, body.nitrogen_status, body.visual_status]
        if any(s == 'FAIL' for s in statuses) or any(ch.status == 'FAIL' for ch in body.checks):
            overall = 'HOLD'
        else:
            overall = 'PASS'
        if body.net_weight_target is not None and body.net_weight_actual is not None and body.weight_tolerance_pct is not None:
            variance_pct = abs(body.net_weight_actual - body.net_weight_target) / body.net_weight_target * 100
            if variance_pct > body.weight_tolerance_pct:
                overall = 'HOLD'

        with engine.connect() as c:
            existing = c.execute(text("SELECT inspection_id FROM packing_qc_inspection WHERE packing_run_id=:r AND packed_fg_lot_id=:l"), {'r': str(packing_run_id), 'l': lot['packed_fg_lot_id']}).scalar()
        inspection_id = UUID(existing) if existing else uuid4()
        with engine.begin() as c:
            if existing:
                c.execute(text("DELETE FROM packing_qc_checks WHERE inspection_id=:i"), {'i': str(inspection_id)})
                c.execute(text("UPDATE packing_qc_inspection SET net_weight_target=:t,net_weight_actual=:a,weight_tolerance_pct=:tol,seal_status=:seal,label_status=:label,nitrogen_status=:n2,visual_status=:visual,overall_status=:s,hold_reason=:hr WHERE inspection_id=:i"), {
                    't': body.net_weight_target, 'a': body.net_weight_actual, 'tol': body.weight_tolerance_pct,
                    'seal': body.seal_status, 'label': body.label_status, 'n2': body.nitrogen_status, 'visual': body.visual_status,
                    's': overall, 'hr': body.hold_reason, 'i': str(inspection_id)})
            else:
                c.execute(text("INSERT INTO packing_qc_inspection(inspection_id,organization_id,entity_id,location_id,warehouse_id,packing_run_id,packed_fg_lot_id,net_weight_target,net_weight_actual,weight_tolerance_pct,seal_status,label_status,nitrogen_status,visual_status,overall_status,hold_reason,created_by) VALUES(:i,:o,:e,:l,:w,:r,:lot,:t,:a,:tol,:seal,:label,:n2,:visual,:s,:hr,:by)"), {
                    'i': str(inspection_id), 'o': run['organization_id'], 'e': run['entity_id'], 'l': run['location_id'], 'w': run['warehouse_id'],
                    'r': str(packing_run_id), 'lot': lot['packed_fg_lot_id'], 't': body.net_weight_target, 'a': body.net_weight_actual,
                    'tol': body.weight_tolerance_pct, 'seal': body.seal_status, 'label': body.label_status, 'n2': body.nitrogen_status,
                    'visual': body.visual_status, 's': overall, 'hr': body.hold_reason, 'by': str(user.user_id)})
            for ch in body.checks:
                c.execute(text("INSERT INTO packing_qc_checks(check_id,inspection_id,parameter,observed_value,status,remarks) VALUES(:id,:i,:p,:v,:s,:r)"), {
                    'id': str(uuid4()), 'i': str(inspection_id), 'p': ch.parameter, 'v': ch.observed_value, 's': ch.status, 'r': ch.remarks})
            if overall == 'HOLD':
                c.execute(text("UPDATE packed_fg_lot SET qc_status='HOLD',status='HOLD' WHERE packed_fg_lot_id=:id"), {'id': lot['packed_fg_lot_id']})
            else:
                c.execute(text("UPDATE packed_fg_lot SET qc_status='RELEASED',status='AVAILABLE' WHERE packed_fg_lot_id=:id"), {'id': lot['packed_fg_lot_id']})
        return {'inspection_id': str(inspection_id), 'packing_run_id': str(packing_run_id), 'packed_fg_lot_id': str(lot['packed_fg_lot_id']), 'overall_status': overall}

    @app.post('/v90x/packing-runs/{packing_run_id}/qc/release')
    def release_qc(packing_run_id: UUID, request: Request):
        with engine.connect() as c:
            row = c.execute(text("SELECT i.*, r.entity_id AS run_entity, r.location_id AS run_location FROM packing_qc_inspection i JOIN packing_run r ON r.packing_run_id=i.packing_run_id WHERE i.packing_run_id=:r"), {'r': str(packing_run_id)}).mappings().first()
        if not row: raise HTTPException(404, 'packing QC inspection not found')
        u = _auth_scope(engine, request, str(row['run_entity']), str(row['run_location']))
        if row['overall_status'] != 'PASS':
            raise HTTPException(409, 'packing QC is not PASS')
        with engine.begin() as c:
            c.execute(text("UPDATE packing_qc_inspection SET released_by=:u,released_at=CURRENT_TIMESTAMP WHERE inspection_id=:i"), {'u': str(u.user_id), 'i': row['inspection_id']})
            c.execute(text("UPDATE packed_fg_lot SET qc_status='RELEASED',status='AVAILABLE' WHERE packed_fg_lot_id=:lot"), {'lot': row['packed_fg_lot_id']})
        return {'packing_run_id': str(packing_run_id), 'status': 'RELEASED', 'inspection_id': row['inspection_id']}

    @app.get('/v90x/packing-runs/{packing_run_id}/qc')
    def get_qc(packing_run_id: UUID, request: Request):
        u = authenticate(request)
        if 'inventory.view' not in permissions_for_user(engine, u.user_id) and 'production.view' not in permissions_for_user(engine, u.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as c:
            row = c.execute(text("SELECT i.* FROM packing_qc_inspection i WHERE i.packing_run_id=:r"), {'r': str(packing_run_id)}).mappings().first()
            if not row: raise HTTPException(404, 'packing QC inspection not found')
            checks = c.execute(text("SELECT * FROM packing_qc_checks WHERE inspection_id=:i ORDER BY created_at"), {'i': row['inspection_id']}).mappings().all()
        try: assert_entity_location_allowed(engine, u.user_id, str(row['entity_id']), str(row['location_id']))
        except PermissionError as e: raise HTTPException(403, str(e))
        return {'inspection': dict(row), 'checks': [dict(x) for x in checks]}
