from __future__ import annotations
from datetime import datetime
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .persistent_master import Base, PersistentMasterAdmin, ChangeRequest

engine = create_engine("sqlite:///./v77_master.db", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
service = PersistentMasterAdmin(SessionLocal)
app = FastAPI(title="Namkeen ERP v77 Persistent Master API", version="77.0")

class ChangeIn(BaseModel):
    organization_id: UUID; master_type: str; action: str; requested_by: UUID; payload: dict = Field(min_length=1)
    master_id: UUID|None=None; entity_id: UUID|None=None; effective_from: datetime|None=None; effective_to: datetime|None=None
    base_version_no: int|None=None; client_event_id: str|None=None
class DecisionIn(BaseModel):
    organization_id: UUID; approver_id: UUID; reason: str=""

@app.get("/v77/master-data/{master_type}")
def list_master(master_type:str, organization_id:UUID, q:str=Query(""), active_only:bool=True, entity_id:UUID|None=None, offset:int=0, limit:int=50):
    try: rows,total=service.list(organization_id,master_type,q,active_only,entity_id,offset,limit)
    except ValueError as e: raise HTTPException(400,str(e))
    if q: rows=[r for r in rows if q.lower() in str(r.data).lower()]
    return {"items":[{**r.data,"master_id":str(r.master_id),"version_no":r.version_no,"active":r.active,"effective_from":r.effective_from,"effective_to":r.effective_to} for r in rows],"total":total,"offset":offset,"limit":limit}

@app.post("/v77/master-data/changes")
def create_change(body:ChangeIn):
    try: rid=service.request(ChangeRequest(**body.model_dump()))
    except ValueError as e: raise HTTPException(400,str(e))
    return {"request_id":str(rid),"status":"PENDING_APPROVAL"}

@app.post("/v77/master-data/changes/{request_id}/approve")
def approve(request_id:UUID, body:DecisionIn):
    try: mid=service.approve(body.organization_id,request_id,body.approver_id,body.reason)
    except ValueError as e: raise HTTPException(400,str(e))
    return {"status":"APPROVED","master_id":str(mid)}

@app.post("/v77/master-data/changes/{request_id}/reject")
def reject(request_id:UUID, body:DecisionIn):
    try: service.reject(body.organization_id,request_id,body.approver_id,body.reason)
    except ValueError as e: raise HTTPException(400,str(e))
    return {"status":"REJECTED"}
