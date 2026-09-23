from __future__ import annotations
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .rules import validate_cross_field
from uuid import UUID, uuid4
from datetime import datetime, timezone

app = FastAPI(title="Namkeen ERP v84 Master Validation", version="84.0")

class ValidateIn(BaseModel):
    organization_id: UUID
    master_type: str
    action: str = "CREATE"
    payload: dict = Field(default_factory=dict)
    existing: dict = Field(default_factory=dict)

class ValidateOut(BaseModel):
    validation_id: UUID
    valid: bool
    errors: list[str]
    checked_at: datetime

@app.post("/v84/master-data/validate", response_model=ValidateOut)
def validate(body: ValidateIn):
    errors = validate_cross_field(body.master_type, body.payload, existing=body.existing)
    return ValidateOut(validation_id=uuid4(), valid=not errors, errors=errors,
                       checked_at=datetime.now(timezone.utc))

@app.get("/v84/health")
def health():
    return {"status": "ok", "version": "84.0"}
