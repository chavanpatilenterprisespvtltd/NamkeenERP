from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .identity import permissions_for_user
from .auth import authenticate
from .master_scope import assert_entity_location_allowed
from .v77.persistent_master import PersistentMasterAdmin, ChangeRequest, VALID_TYPES, MasterChangeRequestORM, MasterRecordORM


class MasterChangeIn(BaseModel):
    organization_id: UUID
    master_type: str
    action: str
    payload: dict[str, Any] = Field(min_length=1)
    master_id: UUID | None = None
    entity_id: UUID | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    base_version_no: int | None = None
    client_event_id: str | None = None


class MasterDecisionIn(BaseModel):
    organization_id: UUID
    reason: str = ""


def _ensure_tables(engine: Engine) -> None:
    """Create the SQLite-compatible master tables needed by the runtime/API tests.

    PostgreSQL installations are created by migration 066+, while SQLite is only a
    development/test runtime. The statements are deliberately idempotent.
    """
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS master_record (
                    master_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    master_type TEXT NOT NULL,
                    entity_id TEXT NULL,
                    data TEXT NOT NULL,
                    normalized_key TEXT NULL,
                    version_no INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    effective_from TEXT NULL,
                    effective_to TEXT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS master_change_request (
                    request_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    master_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    master_id TEXT NULL,
                    entity_id TEXT NULL,
                    payload TEXT NOT NULL,
                    effective_from TEXT NULL,
                    effective_to TEXT NULL,
                    base_version_no INTEGER NULL,
                    client_event_id TEXT UNIQUE NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
                    rejection_reason TEXT NULL,
                    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    decided_at TEXT NULL
                )
            """))
            # Compatibility for SQLite files carried forward from earlier checkpoints.
            existing = {r[1] for r in conn.execute(text("PRAGMA table_info(master_change_request)"))}
            for name, ddl in [("validation_status", "TEXT"), ("validation_id", "TEXT"),
                              ("validation_version", "TEXT"), ("validated_at", "TEXT")]:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE master_change_request ADD COLUMN {name} {ddl}"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS master_audit_snapshot (
                    snapshot_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    master_id TEXT NOT NULL,
                    master_type TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    effective_from TEXT NULL,
                    effective_to TEXT NULL,
                    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    changed_by TEXT NOT NULL
                )
            """))


def _assert_admin_scope(engine: Engine, request: Request, organization_id: UUID, entity_id: UUID | None = None, write: bool = False):
    user = authenticate(request)
    needed = "masters.edit" if write else "masters.view"
    if needed not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail="permission denied")
    # Entity/location authorization is enforced when an entity is supplied.
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id) if entity_id else None, None)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return user


def _service(engine: Engine) -> PersistentMasterAdmin:
    from sqlalchemy.orm import Session
    # PersistentMasterAdmin only needs a callable session factory.
    return PersistentMasterAdmin(lambda: Session(engine, expire_on_commit=False))


def register_v90i_routes(app, engine: Engine) -> None:
    _ensure_tables(engine)

    @app.get("/v90i/master-types")
    def master_types_v90i(request: Request):
        _assert_admin_scope(engine, request, UUID(int=0), write=False)
        return {"items": sorted(VALID_TYPES)}

    @app.get("/v90i/master-data/{master_type}")
    def list_master_v90i(
        master_type: str,
        request: Request,
        organization_id: UUID,
        q: str = Query(""),
        active_only: bool = True,
        entity_id: UUID | None = None,
        offset: int = 0,
        limit: int = Query(50, ge=1, le=200),
    ):
        _assert_admin_scope(engine, request, organization_id, entity_id, write=False)
        if master_type not in VALID_TYPES:
            raise HTTPException(400, "Unsupported master type")
        try:
            rows, total = _service(engine).list(organization_id, master_type, q, active_only, entity_id, offset, limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in str(r.data).lower()]
        return {
            "items": [
                {**r.data, "master_id": str(r.master_id), "entity_id": str(r.entity_id) if r.entity_id else None,
                 "version_no": r.version_no, "active": bool(r.active),
                 "effective_from": r.effective_from.isoformat() if r.effective_from else None,
                 "effective_to": r.effective_to.isoformat() if r.effective_to else None}
                for r in rows
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @app.post("/v90i/master-data/changes")
    def request_master_change_v90i(body: MasterChangeIn, request: Request):
        actor = _assert_admin_scope(engine, request, body.organization_id, body.entity_id, write=True)
        payload = dict(body.payload)
        if body.action == "DEACTIVATE" and "reason" not in payload:
            payload["reason"] = body.reason if hasattr(body, "reason") else ""
        try:
            rid = _service(engine).request(ChangeRequest(
                organization_id=body.organization_id,
                master_type=body.master_type,
                action=body.action,
                requested_by=UUID(str(actor.user_id)) if _is_uuid(actor.user_id) else UUID(int=0),
                payload=payload,
                master_id=body.master_id,
                entity_id=body.entity_id,
                effective_from=body.effective_from,
                effective_to=body.effective_to,
                base_version_no=body.base_version_no,
                client_event_id=body.client_event_id,
            ))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"request_id": str(rid), "status": "PENDING_APPROVAL"}

    @app.get("/v90i/approval-queue")
    def approval_queue_v90i(request: Request, organization_id: UUID, limit: int = Query(100, ge=1, le=500)):
        _assert_admin_scope(engine, request, organization_id, write=False)
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        with Session(engine, expire_on_commit=False) as session:
            rows = session.execute(
                select(MasterChangeRequestORM)
                .where(MasterChangeRequestORM.organization_id == organization_id, MasterChangeRequestORM.status == "PENDING_APPROVAL")
                .order_by(MasterChangeRequestORM.requested_at.desc())
                .limit(limit)
            ).scalars().all()
        return {"items": [{
            "request_id": str(r.request_id), "master_type": r.master_type, "action": r.action,
            "master_id": str(r.master_id) if r.master_id else None, "requested_by": str(r.requested_by),
            "entity_id": str(r.entity_id) if r.entity_id else None, "payload": r.payload,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None, "status": r.status
        } for r in rows]}

    @app.post("/v90i/approval-queue/{request_id}/approve")
    def approve_master_change_v90i(request_id: UUID, body: MasterDecisionIn, request: Request):
        approver = _assert_admin_scope(engine, request, body.organization_id, write=True)
        try:
            mid = _service(engine).approve(
                body.organization_id,
                request_id,
                UUID(str(approver.user_id)) if _is_uuid(approver.user_id) else UUID(int=0),
                body.reason,
                _allowed_entities(engine, approver.user_id),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"status": "APPROVED", "master_id": str(mid)}

    @app.post("/v90i/approval-queue/{request_id}/reject")
    def reject_master_change_v90i(request_id: UUID, body: MasterDecisionIn, request: Request):
        approver = _assert_admin_scope(engine, request, body.organization_id, write=True)
        try:
            _service(engine).reject(
                body.organization_id,
                request_id,
                UUID(str(approver.user_id)) if _is_uuid(approver.user_id) else UUID(int=0),
                body.reason,
                _allowed_entities(engine, approver.user_id),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"status": "REJECTED"}

    @app.get("/v90i/master-data/{master_type}/{master_id}/history")
    def master_history_v90i(master_type: str, master_id: UUID, request: Request, organization_id: UUID):
        _assert_admin_scope(engine, request, organization_id, write=False)
        if master_type not in VALID_TYPES:
            raise HTTPException(400, "Unsupported master type")
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from .v77.persistent_master import MasterAuditSnapshotORM
        with Session(engine, expire_on_commit=False) as session:
            rows = session.execute(
                select(MasterAuditSnapshotORM)
                .where(MasterAuditSnapshotORM.organization_id == organization_id, MasterAuditSnapshotORM.master_id == master_id)
                .order_by(MasterAuditSnapshotORM.version_no.desc())
            ).scalars().all()
        return {"items": [{
            "version_no": r.version_no, "data": r.data, "active": bool(r.active),
            "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            "changed_at": r.changed_at.isoformat() if r.changed_at else None
        } for r in rows]}


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def _allowed_entities(engine: Engine, user_id: str) -> list[UUID]:
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT entity_id FROM erp_entity_user_access WHERE user_id=:u AND active=1"), {"u": user_id}).scalars().all()
        return [UUID(str(x)) for x in rows if _is_uuid(str(x))]
    except Exception:
        return []
