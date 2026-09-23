from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.v77.persistent_master import Base, PersistentMasterAdmin, ChangeRequest, VALID_TYPES
from app.v79.bulk_master import preview_bytes, apply_preview

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./v80_master.db")
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
service = PersistentMasterAdmin(SessionLocal)

app = FastAPI(title="Namkeen ERP v80 Master Data UI", version="80.0")
static_dir = Path(__file__).parent / "static"
app.mount("/v80/static", StaticFiles(directory=static_dir), name="v80-static")

class ChangeIn(BaseModel):
    organization_id: UUID
    master_type: str
    action: str
    requested_by: UUID
    payload: dict = Field(min_length=1)
    master_id: UUID | None = None
    entity_id: UUID | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    base_version_no: int | None = None
    client_event_id: str | None = None

class DecisionIn(BaseModel):
    organization_id: UUID
    approver_id: UUID
    reason: str = ""

@app.get("/v80", response_class=HTMLResponse)
def ui() -> str:
    return (static_dir / "index.html").read_text(encoding="utf-8")

@app.get("/v80/master-types")
def master_types():
    return {"items": sorted(VALID_TYPES)}

@app.get("/v80/master-data/{master_type}")
def list_master(master_type: str, organization_id: UUID, q: str = Query(""), active_only: bool = True,
                entity_id: UUID | None = None, offset: int = 0, limit: int = Query(50, ge=1, le=200)):
    if master_type not in VALID_TYPES:
        raise HTTPException(400, "Unsupported master type")
    try:
        rows, total = service.list(organization_id, master_type, q, active_only, entity_id, offset, limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"items": [
        {**r.data, "master_id": str(r.master_id), "entity_id": str(r.entity_id) if r.entity_id else None,
         "version_no": r.version_no, "active": r.active,
         "effective_from": r.effective_from.isoformat() if r.effective_from else None,
         "effective_to": r.effective_to.isoformat() if r.effective_to else None}
        for r in rows
    ], "total": total, "offset": offset, "limit": limit}

@app.post("/v80/master-data/changes")
def create_change(body: ChangeIn):
    try:
        rid = service.request(ChangeRequest(**body.model_dump()))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"request_id": str(rid), "status": "PENDING_APPROVAL"}

@app.get("/v80/approval-queue")
def approval_queue(organization_id: UUID, limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as s:
        from app.v77.persistent_master import MasterChangeRequestORM
        from sqlalchemy import select
        rows = s.scalars(select(MasterChangeRequestORM).where(
            MasterChangeRequestORM.organization_id == organization_id,
            MasterChangeRequestORM.status == "PENDING_APPROVAL"
        ).order_by(MasterChangeRequestORM.requested_at.desc()).limit(limit)).all()
    return {"items": [{
        "request_id": str(r.request_id), "master_type": r.master_type, "action": r.action,
        "master_id": str(r.master_id) if r.master_id else None, "requested_by": str(r.requested_by),
        "entity_id": str(r.entity_id) if r.entity_id else None,
        "payload": r.payload, "requested_at": r.requested_at.isoformat()
    } for r in rows]}

@app.post("/v80/approval-queue/{request_id}/approve")
def approve(request_id: UUID, body: DecisionIn):
    try:
        master_id = service.approve(body.organization_id, request_id, body.approver_id, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "APPROVED", "master_id": str(master_id)}

@app.post("/v80/approval-queue/{request_id}/reject")
def reject(request_id: UUID, body: DecisionIn):
    try:
        service.reject(body.organization_id, request_id, body.approver_id, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "REJECTED"}

@app.get("/v80/master-data/{master_type}/{master_id}/history")
def history(master_type: str, master_id: UUID, organization_id: UUID):
    if master_type not in VALID_TYPES:
        raise HTTPException(400, "Unsupported master type")
    with SessionLocal() as s:
        from app.v77.persistent_master import MasterAuditSnapshotORM
        from sqlalchemy import select
        rows = s.scalars(select(MasterAuditSnapshotORM).where(
            MasterAuditSnapshotORM.organization_id == organization_id,
            MasterAuditSnapshotORM.master_id == master_id
        ).order_by(MasterAuditSnapshotORM.version_no.desc())).all()
    return {"items": [{
        "version_no": r.version_no, "data": r.data, "active": r.active,
        "effective_from": r.effective_from.isoformat() if r.effective_from else None,
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "changed_at": r.changed_at.isoformat()
    } for r in rows]}

@app.post("/v80/bulk/preview")
def bulk_preview(organization_id: UUID, file_name: str, payload_b64: str):
    import base64
    try:
        preview = preview_bytes(base64.b64decode(payload_b64), file_name, organization_id)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"batch_id": str(preview.batch_id), "valid": preview.valid, "errors": [e.__dict__ for e in preview.errors],
            "row_count": len(preview.rows), "content_sha256": preview.content_sha256}
