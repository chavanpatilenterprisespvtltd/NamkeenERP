from __future__ import annotations
from datetime import datetime
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from .master_api import MasterAdminRegistry, ChangeRequest

app = FastAPI(title="Namkeen ERP v76 Master Data API", version="76.0")
registry = MasterAdminRegistry()

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

class ApproveIn(BaseModel):
    approver_id: UUID
    reason: str = ""

@app.get("/v76/master-data/{master_type}")
def list_master(master_type: str, organization_id: UUID, q: str = Query(""), active_only: bool = True, entity_id: UUID | None = None):
    try:
        rows = registry.search(organization_id, master_type, q, active_only, entity_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"items":[{**r.data, "master_id": str(r.master_id), "version_no": r.version_no, "active": r.active} for r in rows]}

@app.post("/v76/master-data/changes")
def request_change(body: ChangeIn):
    try:
        req = registry.request(ChangeRequest(body.organization_id, body.master_type, body.action, body.requested_by, body.payload, body.master_id, body.entity_id, body.effective_from, body.effective_to))
        return {"request_id": str(req.request_id), "status": req.status}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/v76/master-data/changes/{request_id}/approve")
def approve(request_id: UUID, body: ApproveIn):
    try:
        rec = registry.approve(request_id, body.approver_id, body.reason)
        return {"status":"APPROVED", "master_id":str(rec.master_id), "version_no":rec.version_no}
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))

@app.get("/v76/master-data/{master_type}/{master_id}/history")
def history(master_type: str, master_id: UUID):
    return {"master_type": master_type, "master_id": str(master_id), "items": registry.history(master_id)}
