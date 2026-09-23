from __future__ import annotations
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uuid import UUID

from app.v86.service import ProductionMasterAdminV86
from app.v86.service import ProductionMasterAdminV86
from app.v77.persistent_master import Base as V77Base

app = FastAPI(title="Namkeen ERP", version="v86")

DB_URL = "sqlite+pysqlite:///./namkeen_v86.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
V77Base.metadata.create_all(engine)


class ChangeRequestIn(BaseModel):
    organization_id: UUID
    master_type: str
    action: str
    requested_by: UUID
    payload: dict = Field(default_factory=dict)
    master_id: UUID | None = None
    entity_id: UUID | None = None
    effective_from: object | None = None
    effective_to: object | None = None
    base_version_no: int | None = None
    client_event_id: str | None = None


class DecisionIn(BaseModel):
    organization_id: UUID
    request_id: UUID
    actor_id: UUID
    reason: str = ""


@app.get("/health")
def health():
    return {"status": "ok", "version": "v86"}


@app.post("/v86/master-data/change-requests")
def submit(req: ChangeRequestIn):
    from app.v77.persistent_master import ChangeRequest
    service = ProductionMasterAdminV86(SessionLocal)
    cr = ChangeRequest(
        organization_id=req.organization_id, master_type=req.master_type, action=req.action,
        requested_by=req.requested_by, payload=req.payload, master_id=req.master_id,
        entity_id=req.entity_id, effective_from=req.effective_from, effective_to=req.effective_to,
        base_version_no=req.base_version_no, client_event_id=req.client_event_id,
    )
    try:
        request_id, result = service.submit(cr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"request_id": str(request_id), "validation_status": result.status,
            "errors": list(result.errors), "warnings": list(result.warnings),
            "validation_version": result.validation_version}


@app.post("/v86/master-data/approve")
def approve(req: DecisionIn):
    service = ProductionMasterAdminV86(SessionLocal)
    try:
        master_id, result = service.approve(req.organization_id, req.request_id, req.actor_id, req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"master_id": str(master_id), "validation_status": result.status,
            "warnings": list(result.warnings), "validation_version": result.validation_version}


@app.post("/v86/master-data/reject")
def reject(req: DecisionIn):
    service = ProductionMasterAdminV86(SessionLocal)
    try:
        service.reject(req.organization_id, req.request_id, req.actor_id, req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "REJECTED"}
