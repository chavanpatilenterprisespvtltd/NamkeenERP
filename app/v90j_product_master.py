from __future__ import annotations

from typing import Any
from uuid import UUID
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed
from .v77.persistent_master import MasterRecordORM, PersistentMasterAdmin, ChangeRequest, VALID_TYPES
from .v81.master_schemas import field_meta, validate_payload
from .v90i_master_api import _service, _allowed_entities, _is_uuid

PRODUCT_MASTER_TYPES = {"PRODUCT", "VARIANT", "PACK_SIZE", "SKU", "UOM_CONVERSION"}

class StructuredMasterChange(BaseModel):
    organization_id: UUID
    action: str
    payload: dict[str, Any] = Field(min_length=1)
    master_id: UUID | None = None
    entity_id: UUID | None = None
    effective_from: Any | None = None
    effective_to: Any | None = None
    base_version_no: int | None = None
    client_event_id: str | None = None


def _require(engine, request: Request, organization_id: UUID, entity_id: UUID | None, write: bool):
    user = authenticate(request)
    required = "masters.edit" if write else "masters.view"
    if required not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id) if entity_id else None, None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _as_uuid(value: Any, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid UUID") from exc


def _lookup_active(session: Session, organization_id: UUID, master_type: str, master_id: UUID, entity_id: UUID | None):
    row = session.scalar(select(MasterRecordORM).where(
        MasterRecordORM.master_id == master_id,
        MasterRecordORM.organization_id == organization_id,
        MasterRecordORM.master_type == master_type,
        MasterRecordORM.active.is_(True),
    ))
    if not row:
        raise ValueError(f"Referenced {master_type} not found")
    if entity_id is not None and row.entity_id not in (None, entity_id):
        raise ValueError(f"Referenced {master_type} is outside entity scope")
    return row


def _validate_relationships(engine, organization_id: UUID, entity_id: UUID | None, master_type: str, payload: dict[str, Any]):
    if master_type not in PRODUCT_MASTER_TYPES:
        raise ValueError("Unsupported product master type")
    errors = validate_payload(master_type, payload, "CREATE")
    if errors:
        raise ValueError("; ".join(errors))
    with Session(engine, expire_on_commit=False) as s:
        if master_type == "VARIANT":
            _lookup_active(s, organization_id, "PRODUCT", _as_uuid(payload["product_id"], "product_id"), entity_id)
        elif master_type == "SKU":
            _lookup_active(s, organization_id, "PRODUCT", _as_uuid(payload["product_id"], "product_id"), entity_id)
            _lookup_active(s, organization_id, "PACK_SIZE", _as_uuid(payload["pack_size_id"], "pack_size_id"), entity_id)
            if payload.get("variant_id"):
                _lookup_active(s, organization_id, "VARIANT", _as_uuid(payload["variant_id"], "variant_id"), entity_id)
            barcode = str(payload.get("barcode") or "").strip()
            if barcode:
                rows = s.scalars(select(MasterRecordORM).where(
                    MasterRecordORM.organization_id == organization_id,
                    MasterRecordORM.master_type == "SKU",
                    MasterRecordORM.active.is_(True),
                )).all()
                for row in rows:
                    if entity_id is not None and row.entity_id not in (None, entity_id):
                        continue
                    if str((row.data or {}).get("barcode") or "").strip() == barcode:
                        raise ValueError("Duplicate active SKU barcode")
        elif master_type == "PACK_SIZE":
            quantity = float(payload.get("quantity", 0))
            if quantity <= 0:
                raise ValueError("Pack size quantity must be greater than zero")
            if not str(payload.get("uom") or "").strip():
                raise ValueError("Pack size UOM is required")
        elif master_type == "UOM_CONVERSION":
            factor = float(payload.get("factor", 0))
            if factor <= 0:
                raise ValueError("UOM conversion factor must be greater than zero")
            if str(payload.get("from_uom")).strip().lower() == str(payload.get("to_uom")).strip().lower():
                raise ValueError("From UOM and To UOM must differ")


def _relationship_update_validation(engine, organization_id: UUID, entity_id: UUID | None, master_type: str, master_id: UUID, payload: dict[str, Any]):
    # Validate the merged record against the product hierarchy without mutating it.
    with Session(engine, expire_on_commit=False) as s:
        row = s.scalar(select(MasterRecordORM).where(
            MasterRecordORM.master_id == master_id,
            MasterRecordORM.organization_id == organization_id,
            MasterRecordORM.master_type == master_type,
        ))
        if not row:
            raise ValueError(f"{master_type} not found")
        merged = dict(row.data or {})
        merged.update(payload)
    _validate_relationships(engine, organization_id, entity_id, master_type, merged)


def register_v90j_routes(app, engine):
    @app.get("/v90j/product-masters")
    def product_master_types(request: Request):
        _require(engine, request, UUID(int=0), None, False)
        return {"items": [field_meta(x) for x in sorted(PRODUCT_MASTER_TYPES)]}

    @app.get("/v90j/product-masters/{master_type}")
    def product_master_list(master_type: str, request: Request, organization_id: UUID,
                            entity_id: UUID | None = None, q: str = "", active_only: bool = True,
                            offset: int = 0, limit: int = 100):
        if master_type not in PRODUCT_MASTER_TYPES:
            raise HTTPException(400, "Unsupported product master type")
        _require(engine, request, organization_id, entity_id, False)
        rows, total = _service(engine).list(organization_id, master_type, q, active_only, entity_id, offset, limit)
        return {"items": [{**(r.data or {}), "master_id": str(r.master_id), "entity_id": str(r.entity_id) if r.entity_id else None,
                            "version_no": r.version_no, "active": bool(r.active)} for r in rows], "total": total,
                "offset": offset, "limit": limit}

    @app.post("/v90j/product-masters/{master_type}/changes")
    def product_master_change(master_type: str, body: StructuredMasterChange, request: Request):
        if master_type not in PRODUCT_MASTER_TYPES:
            raise HTTPException(400, "Unsupported product master type")
        actor = _require(engine, request, body.organization_id, body.entity_id, True)
        if body.action not in {"CREATE", "UPDATE", "DEACTIVATE"}:
            raise HTTPException(400, "Unsupported master action")
        try:
            if body.action == "CREATE":
                _validate_relationships(engine, body.organization_id, body.entity_id, master_type, body.payload)
            elif body.action == "UPDATE":
                if not body.master_id:
                    raise ValueError("master_id is required")
                _relationship_update_validation(engine, body.organization_id, body.entity_id, master_type, body.master_id, body.payload)
            elif body.action == "DEACTIVATE" and not str(body.payload.get("reason") or "").strip():
                raise ValueError("Deactivation reason is required")
            rid = _service(engine).request(ChangeRequest(
                organization_id=body.organization_id, master_type=master_type, action=body.action,
                requested_by=UUID(str(actor.user_id)) if _is_uuid(actor.user_id) else UUID(int=0),
                payload=dict(body.payload), master_id=body.master_id, entity_id=body.entity_id,
                effective_from=body.effective_from, effective_to=body.effective_to,
                base_version_no=body.base_version_no, client_event_id=body.client_event_id,
            ))
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"request_id": str(rid), "status": "PENDING_APPROVAL"}

    @app.get("/v90j/product-hierarchy/{product_id}")
    def product_hierarchy(product_id: UUID, request: Request, organization_id: UUID, entity_id: UUID | None = None):
        _require(engine, request, organization_id, entity_id, False)
        from .v82.lookups import lookup
        return {
            "product": lookup(_service(engine).session_factory, organization_id=organization_id, kind="products", q=str(product_id), entity_id=entity_id)[:1],
            "variants": lookup(_service(engine).session_factory, organization_id=organization_id, kind="variants", parent_id=product_id, entity_id=entity_id),
            "skus": lookup(_service(engine).session_factory, organization_id=organization_id, kind="skus", parent_id=product_id, entity_id=entity_id),
        }

    @app.get("/v90j/sku/{sku_id}/configuration")
    def sku_configuration(sku_id: UUID, request: Request, organization_id: UUID, entity_id: UUID | None = None):
        _require(engine, request, organization_id, entity_id, False)
        with Session(engine, expire_on_commit=False) as s:
            row = s.scalar(select(MasterRecordORM).where(MasterRecordORM.master_id == sku_id, MasterRecordORM.organization_id == organization_id, MasterRecordORM.master_type == "SKU", MasterRecordORM.active.is_(True)))
            if not row or (entity_id is not None and row.entity_id not in (None, entity_id)):
                raise HTTPException(404, "SKU not found")
            d = dict(row.data or {})
            refs = {}
            for key, typ in (("product_id", "PRODUCT"), ("variant_id", "VARIANT"), ("pack_size_id", "PACK_SIZE")):
                if d.get(key):
                    ref = s.scalar(select(MasterRecordORM).where(MasterRecordORM.master_id == _as_uuid(d[key], key), MasterRecordORM.organization_id == organization_id, MasterRecordORM.master_type == typ, MasterRecordORM.active.is_(True)))
                    refs[key] = dict(ref.data or {}) if ref else None
            return {"sku_id": str(row.master_id), "sku": d, "references": refs, "version_no": row.version_no}
