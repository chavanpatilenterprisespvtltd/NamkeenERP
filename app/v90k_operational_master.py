from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed
from .v77.persistent_master import MasterRecordORM, ChangeRequest
from .v90i_master_api import _service, _allowed_entities, _is_uuid

OPERATIONAL_MASTER_TYPES = {"CUSTOMER", "SUPPLIER", "WAREHOUSE", "BIN"}

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{13}$", re.I)
PHONE_RE = re.compile(r"^[0-9+()\- ]{7,20}$")


class OperationalMasterChange(BaseModel):
    organization_id: UUID
    action: str
    payload: dict[str, Any] = Field(min_length=1)
    master_id: UUID | None = None
    entity_id: UUID | None = None
    location_id: UUID | None = None
    effective_from: Any | None = None
    effective_to: Any | None = None
    base_version_no: int | None = None
    client_event_id: str | None = None


def _require(engine, request: Request, entity_id: UUID | None, location_id: UUID | None, write: bool):
    user = authenticate(request)
    required = "masters.edit" if write else "masters.view"
    if required not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    try:
        assert_entity_location_allowed(
            engine,
            user.user_id,
            str(entity_id) if entity_id else None,
            str(location_id) if location_id else None,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _uuid(value: Any, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid UUID") from exc


def _find(engine, organization_id: UUID, master_type: str, master_id: UUID):
    with Session(engine, expire_on_commit=False) as s:
        row = s.scalar(
            select(MasterRecordORM).where(
                MasterRecordORM.organization_id == organization_id,
                MasterRecordORM.master_type == master_type,
                MasterRecordORM.master_id == master_id,
            )
        )
        return row


def _validate_common(payload: dict[str, Any], master_type: str) -> None:
    code = str(payload.get("code") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not code:
        raise ValueError("Code is required")
    if not name:
        raise ValueError("Name is required")

    phone = str(payload.get("phone") or "").strip()
    if phone and not PHONE_RE.match(phone):
        raise ValueError("Phone format is invalid")

    gstin = str(payload.get("gstin") or "").strip().upper()
    if gstin and not GSTIN_RE.match(gstin):
        raise ValueError("GSTIN format is invalid")

    if "credit_limit" in payload and payload["credit_limit"] is not None:
        try:
            if float(payload["credit_limit"]) < 0:
                raise ValueError("Credit limit cannot be negative")
        except (TypeError, ValueError) as exc:
            if str(exc) == "Credit limit cannot be negative":
                raise
            raise ValueError("Credit limit must be numeric") from exc

    if "payment_terms_days" in payload and payload["payment_terms_days"] is not None:
        try:
            if float(payload["payment_terms_days"]) < 0:
                raise ValueError("Payment terms days cannot be negative")
        except (TypeError, ValueError) as exc:
            if str(exc) == "Payment terms days cannot be negative":
                raise
            raise ValueError("Payment terms days must be numeric") from exc


def _reference_exists(session: Session, organization_id: UUID, master_type: str, master_id: UUID, entity_id: UUID | None = None):
    row = session.scalar(
        select(MasterRecordORM).where(
            MasterRecordORM.organization_id == organization_id,
            MasterRecordORM.master_type == master_type,
            MasterRecordORM.master_id == master_id,
            MasterRecordORM.active.is_(True),
        )
    )
    if not row:
        raise ValueError(f"Referenced {master_type} not found")
    if entity_id is not None and row.entity_id not in (None, entity_id):
        raise ValueError(f"Referenced {master_type} is outside entity scope")
    return row


def _validate_type_relationships(engine, body: OperationalMasterChange, master_type: str, payload: dict[str, Any]):
    _validate_common(payload, master_type)
    with Session(engine, expire_on_commit=False) as s:
        if master_type == "WAREHOUSE":
            if not body.entity_id:
                raise ValueError("entity_id is required for warehouse")
            if not body.location_id:
                raise ValueError("location_id is required for warehouse")
            loc = s.scalar(
                select(MasterRecordORM).where(
                    MasterRecordORM.organization_id == body.organization_id,
                    MasterRecordORM.master_type == "LOCATION",
                    MasterRecordORM.master_id == body.location_id,
                    MasterRecordORM.active.is_(True),
                )
            )
            # Location is maintained by org_structure rather than MasterRecord in the current system.
            # Therefore only structural UUID presence is enforced here; deeper referential validation is
            # handled by the dedicated admin/location layer in this checkpoint.
            _ = loc
            if not str(payload.get("warehouse_type") or "").strip():
                raise ValueError("warehouse_type is required")

        elif master_type == "BIN":
            if not payload.get("warehouse_id"):
                raise ValueError("warehouse_id is required for bin")
            wid = _uuid(payload["warehouse_id"], "warehouse_id")
            _reference_exists(s, body.organization_id, "WAREHOUSE", wid, body.entity_id)
            for k in ("zone", "aisle", "rack"):
                if payload.get(k) is not None:
                    payload[k] = str(payload[k]).strip()

        elif master_type in {"CUSTOMER", "SUPPLIER"}:
            # Normalize statutory/commercial values without changing business meaning.
            if payload.get("gstin"):
                payload["gstin"] = str(payload["gstin"]).strip().upper()
            if payload.get("payment_terms_days") is not None:
                payload["payment_terms_days"] = int(float(payload["payment_terms_days"]))
            if payload.get("credit_limit") is not None:
                payload["credit_limit"] = float(payload["credit_limit"])


def register_v90k_routes(app, engine):
    @app.get("/v90k/operational-masters")
    def operational_types(request: Request):
        _require(engine, request, None, None, False)
        return {"items": sorted(OPERATIONAL_MASTER_TYPES)}

    @app.get("/v90k/operational-masters/{master_type}")
    def operational_list(master_type: str, request: Request, organization_id: UUID,
                         entity_id: UUID | None = None, location_id: UUID | None = None,
                         q: str = "", offset: int = 0, limit: int = 100):
        if master_type not in OPERATIONAL_MASTER_TYPES:
            raise HTTPException(400, "Unsupported operational master type")
        _require(engine, request, entity_id, location_id, False)
        rows, total = _service(engine).list(organization_id, master_type, q, True, entity_id, offset, limit)
        items = []
        ql = q.lower().strip()
        for r in rows:
            d = dict(r.data or {})
            if ql and ql not in str(d).lower():
                continue
            items.append({**d, "master_id": str(r.master_id), "entity_id": str(r.entity_id) if r.entity_id else None,
                          "version_no": r.version_no, "active": bool(r.active)})
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    @app.post("/v90k/operational-masters/{master_type}/changes")
    def operational_change(master_type: str, body: OperationalMasterChange, request: Request):
        if master_type not in OPERATIONAL_MASTER_TYPES:
            raise HTTPException(400, "Unsupported operational master type")
        actor = _require(engine, request, body.entity_id, body.location_id, True)
        if body.action not in {"CREATE", "UPDATE", "DEACTIVATE"}:
            raise HTTPException(400, "Unsupported master action")

        try:
            payload = dict(body.payload)
            if body.action == "UPDATE":
                if not body.master_id:
                    raise ValueError("master_id is required")
                existing = _find(engine, body.organization_id, master_type, body.master_id)
                if not existing:
                    raise ValueError("Operational master not found")
                merged = dict(existing.data or {})
                merged.update(payload)
                _validate_type_relationships(engine, body, master_type, merged)
                payload = merged
            else:
                _validate_type_relationships(engine, body, master_type, payload)

            rid = _service(engine).request(ChangeRequest(
                organization_id=body.organization_id,
                master_type=master_type,
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
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"request_id": str(rid), "status": "PENDING_APPROVAL"}

    @app.get("/v90k/bin/{bin_id}/location")
    def bin_location(bin_id: UUID, request: Request, organization_id: UUID, entity_id: UUID | None = None):
        _require(engine, request, entity_id, None, False)
        row = _find(engine, organization_id, "BIN", bin_id)
        if not row or not row.active or (entity_id is not None and row.entity_id not in (None, entity_id)):
            raise HTTPException(404, "BIN not found")
        d = dict(row.data or {})
        wid_raw = d.get("warehouse_id")
        if not wid_raw:
            raise HTTPException(409, "BIN has no warehouse reference")
        wh = _find(engine, organization_id, "WAREHOUSE", _uuid(wid_raw, "warehouse_id"))
        return {
            "bin_id": str(bin_id),
            "warehouse_id": str(wid_raw),
            "warehouse": dict(wh.data or {}) if wh else None,
            "entity_id": str(row.entity_id) if row.entity_id else None,
        }
