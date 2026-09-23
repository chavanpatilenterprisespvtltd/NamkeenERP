from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.v77.persistent_master import Base, PersistentMasterAdmin, ChangeRequest, VALID_TYPES, MasterChangeRequestORM, MasterAuditSnapshotORM
from app.v81.master_schemas import field_meta, validate_payload

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./v81_master.db")
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
service = PersistentMasterAdmin(SessionLocal)

app = FastAPI(title="Namkeen ERP v81 Structured Master Data", version="81.0")
static_dir = Path(__file__).parent / "static"
app.mount("/v81/static", StaticFiles(directory=static_dir), name="v81-static")

class StructuredChangeIn(BaseModel):
    organization_id: UUID
    master_type: str
    action: str
    requested_by: UUID
    payload: dict = Field(default_factory=dict)
    master_id: UUID | None = None
    entity_id: UUID | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    base_version_no: int | None = None
    client_event_id: str | None = None

@app.get("/v81", response_class=HTMLResponse)
def ui() -> str:
    return (static_dir / "index.html").read_text(encoding="utf-8")

@app.get("/v81/master-types")
def master_types():
    return {"items": [field_meta(x) for x in sorted(VALID_TYPES)]}

@app.get("/v81/master-schemas/{master_type}")
def schema(master_type: str):
    try: return field_meta(master_type)
    except KeyError: raise HTTPException(400, "Unsupported master type")

@app.get("/v81/master-data/{master_type}")
def list_master(master_type: str, organization_id: UUID, q: str = Query(""), active_only: bool = True,
                entity_id: UUID | None = None, offset: int = 0, limit: int = Query(50, ge=1, le=200)):
    if master_type not in VALID_TYPES: raise HTTPException(400, "Unsupported master type")
    try: rows,total = service.list(organization_id, master_type, q, active_only, entity_id, offset, limit)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    return {"items":[{**r.data,"master_id":str(r.master_id),"entity_id":str(r.entity_id) if r.entity_id else None,"version_no":r.version_no,"active":r.active,
                       "effective_from":r.effective_from.isoformat() if r.effective_from else None,"effective_to":r.effective_to.isoformat() if r.effective_to else None} for r in rows],"total":total,"offset":offset,"limit":limit}

@app.post("/v81/master-data/changes")
def create_change(body: StructuredChangeIn):
    errors=validate_payload(body.master_type, body.payload, body.action)
    if errors: raise HTTPException(422, {"errors": errors})
    if body.master_type not in VALID_TYPES: raise HTTPException(400,"Unsupported master type")
    try:
        rid=service.request(ChangeRequest(organization_id=body.organization_id,master_type=body.master_type,action=body.action,requested_by=body.requested_by,
            payload=body.payload,master_id=body.master_id,entity_id=body.entity_id,effective_from=body.effective_from,effective_to=body.effective_to,
            base_version_no=body.base_version_no,client_event_id=body.client_event_id))
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    return {"request_id":str(rid),"status":"PENDING_APPROVAL"}

@app.get("/v81/approval-queue")
def approval_queue(organization_id: UUID, limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as s:
        rows=s.scalars(select(MasterChangeRequestORM).where(MasterChangeRequestORM.organization_id==organization_id, MasterChangeRequestORM.status=="PENDING_APPROVAL").order_by(MasterChangeRequestORM.requested_at.desc()).limit(limit)).all()
    return {"items":[{"request_id":str(r.request_id),"master_type":r.master_type,"action":r.action,"master_id":str(r.master_id) if r.master_id else None,
                        "requested_by":str(r.requested_by),"entity_id":str(r.entity_id) if r.entity_id else None,"payload":r.payload,
                        "effective_from":r.effective_from.isoformat() if r.effective_from else None,"effective_to":r.effective_to.isoformat() if r.effective_to else None,
                        "requested_at":r.requested_at.isoformat()} for r in rows]}

@app.post("/v81/approval-queue/{request_id}/approve")
def approve(request_id: UUID, organization_id: UUID, approver_id: UUID, reason: str=""):
    try: mid=service.approve(organization_id,request_id,approver_id,reason)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    return {"status":"APPROVED","master_id":str(mid)}

@app.post("/v81/approval-queue/{request_id}/reject")
def reject(request_id: UUID, organization_id: UUID, approver_id: UUID, reason: str):
    try: service.reject(organization_id,request_id,approver_id,reason)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    return {"status":"REJECTED"}

@app.get("/v81/master-data/{master_type}/{master_id}/history")
def history(master_type: str, master_id: UUID, organization_id: UUID):
    if master_type not in VALID_TYPES: raise HTTPException(400,"Unsupported master type")
    with SessionLocal() as s:
        rows=s.scalars(select(MasterAuditSnapshotORM).where(MasterAuditSnapshotORM.organization_id==organization_id, MasterAuditSnapshotORM.master_id==master_id).order_by(MasterAuditSnapshotORM.version_no.desc())).all()
    return {"items":[{"version_no":r.version_no,"data":r.data,"active":r.active,"effective_from":r.effective_from.isoformat() if r.effective_from else None,
                        "effective_to":r.effective_to.isoformat() if r.effective_to else None,"changed_at":r.changed_at.isoformat()} for r in rows]}
