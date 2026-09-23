from __future__ import annotations
from typing import Any
from uuid import UUID
from sqlalchemy import select, or_, and_
from app.v77.persistent_master import MasterRecordORM, VALID_TYPES

LOOKUP_TYPES = {
    "products": "PRODUCT",
    "variants": "VARIANT",
    "pack-sizes": "PACK_SIZE",
    "skus": "SKU",
    "uom-conversions": "UOM_CONVERSION",
    "customers": "CUSTOMER",
    "suppliers": "SUPPLIER",
    "warehouses": "WAREHOUSE",
    "bins": "BIN",
    "tax-profiles": "TAX_PROFILE",
    "hsn": "HSN",
    "price-lists": "PRICE_LIST",
    "territories": "TERRITORY",
    "roles": "ROLE",
    "accounting-ledgers": "ACCOUNTING_LEDGER_MAPPING",
}

PARENT_FIELDS = {
    "variants": ("product_id", "product_id"),
    "skus": ("product_id", "product_id"),
    "skus_by_variant": ("variant_id", "variant_id"),
    "skus_by_pack": ("pack_size_id", "pack_size_id"),
    "bins": ("warehouse_id", "warehouse_id"),
    "hsn": ("tax_profile_id", "tax_profile_id"),
    "price-lists-by-sku": ("sku", "sku"),
}

def _text_blob(r: MasterRecordORM) -> str:
    d = r.data or {}
    return " ".join(str(d.get(k, "")) for k in ("code", "sku", "name", "description", "gstin", "barcode")).lower()

def _label(r: MasterRecordORM) -> str:
    d = r.data or {}
    return str(d.get("name") or d.get("code") or d.get("sku") or r.master_id)

def _key(r: MasterRecordORM) -> str:
    d = r.data or {}
    return str(d.get("code") or d.get("sku") or r.master_id)

def lookup(session_factory, *, organization_id: UUID, kind: str, q: str = "", parent_id: UUID | None = None,
           entity_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if kind not in LOOKUP_TYPES and kind not in PARENT_FIELDS:
        raise ValueError("Unsupported lookup type")
    if kind in LOOKUP_TYPES:
        master_type = LOOKUP_TYPES[kind]
        parent_field = None
    else:
        if kind == "skus_by_variant": master_type, parent_field = "SKU", "variant_id"
        elif kind == "skus_by_pack": master_type, parent_field = "SKU", "pack_size_id"
        else:
            mapping = {
                "variants": ("VARIANT", "product_id"),
                "skus": ("SKU", "product_id"),
                "bins": ("BIN", "warehouse_id"),
                "hsn": ("HSN", "tax_profile_id"),
                "price-lists-by-sku": ("PRICE_LIST", "sku"),
            }
            master_type, parent_field = mapping[kind]
    with session_factory() as s:
        stmt = select(MasterRecordORM).where(
            MasterRecordORM.organization_id == organization_id,
            MasterRecordORM.master_type == master_type,
            MasterRecordORM.active.is_(True),
        )
        if entity_id is not None:
            stmt = stmt.where(MasterRecordORM.entity_id == entity_id)
        rows = s.scalars(stmt.order_by(MasterRecordORM.updated_at.desc())).all()
    if parent_id is not None and parent_field:
        pid = str(parent_id)
        rows = [r for r in rows if str((r.data or {}).get(parent_field, "")) == pid]
    ql = q.strip().lower()
    if ql:
        rows = [r for r in rows if ql in _text_blob(r)]
    rows = rows[: max(1, min(limit, 200))]
    return [{"id": str(r.master_id), "key": _key(r), "label": _label(r), "master_type": r.master_type,
             "entity_id": str(r.entity_id) if r.entity_id else None, "data": dict(r.data or {})} for r in rows]


def lookup_relationships(session_factory, *, organization_id: UUID, sku_id: UUID | None = None,
                         warehouse_id: UUID | None = None, product_id: UUID | None = None,
                         variant_id: UUID | None = None, pack_size_id: UUID | None = None,
                         tax_profile_id: UUID | None = None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if product_id:
        out["variants"] = lookup(session_factory, organization_id=organization_id, kind="variants", parent_id=product_id)
        out["skus"] = lookup(session_factory, organization_id=organization_id, kind="skus", parent_id=product_id)
    if variant_id:
        out["skus_by_variant"] = lookup(session_factory, organization_id=organization_id, kind="skus_by_variant", parent_id=variant_id)
    if pack_size_id:
        out["skus_by_pack"] = lookup(session_factory, organization_id=organization_id, kind="skus_by_pack", parent_id=pack_size_id)
    if warehouse_id:
        out["bins"] = lookup(session_factory, organization_id=organization_id, kind="bins", parent_id=warehouse_id)
    if tax_profile_id:
        out["hsn"] = lookup(session_factory, organization_id=organization_id, kind="hsn", parent_id=tax_profile_id)
    if sku_id:
        out["price_lists"] = lookup(session_factory, organization_id=organization_id, kind="price-lists-by-sku", parent_id=sku_id)
    return out
