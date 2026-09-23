from __future__ import annotations
from datetime import datetime
from typing import Any
from uuid import UUID
import re

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{13}$")
HEX_HSN_RE = re.compile(r"^[0-9]{4,8}$")
BARCODE_RE = re.compile(r"^[0-9A-Za-z\-_.:/]+$")
VALID_UOMS = {"kg", "g", "piece", "pack", "carton"}
VALID_WAREHOUSE_TYPES = {"RM", "PKG", "WIP", "FG", "QC", "DISP", "GENERAL", "DISPATCH"}
VALID_LEDGER_TYPES = {"CUSTOMER", "SUPPLIER", "SALES", "PURCHASE", "CGST", "SGST", "IGST", "CESS", "CASH", "BANK", "EXPENSE", "ASSET", "LIABILITY", "OTHER"}


def _num(payload: dict[str, Any], key: str, errors: list[str], *, min_value: float | None = None, max_value: float | None = None):
    if key not in payload or payload[key] in (None, ""):
        return None
    try:
        value = float(payload[key])
    except (TypeError, ValueError):
        errors.append(f"{key}: must be numeric")
        return None
    if min_value is not None and value < min_value:
        errors.append(f"{key}: must be >= {min_value}")
    if max_value is not None and value > max_value:
        errors.append(f"{key}: must be <= {max_value}")
    return value


def validate_cross_field(master_type: str, payload: dict[str, Any], *, existing: dict[str, Any] | None = None) -> list[str]:
    """Business-rule validation before a master change request is approved."""
    errors: list[str] = []
    p = dict(existing or {})
    p.update(payload)

    if master_type == "PRODUCT":
        if p.get("code") and p["code"].strip() != p["code"]:
            errors.append("code: leading/trailing spaces are not allowed")
        if p.get("name") and len(p["name"].strip()) < 2:
            errors.append("name: must contain at least 2 characters")

    elif master_type == "VARIANT":
        if not p.get("product_id"):
            errors.append("product_id: required")
        else:
            try: UUID(str(p["product_id"]))
            except ValueError: errors.append("product_id: must be a valid UUID")

    elif master_type == "PACK_SIZE":
        qty = _num(p, "quantity", errors, min_value=0.000001)
        uom = str(p.get("uom") or "").strip().lower()
        if uom not in VALID_UOMS:
            errors.append(f"uom: must be one of {sorted(VALID_UOMS)}")
        if uom in {"kg", "g"} and qty is not None and qty <= 0:
            errors.append("quantity: weight pack must be positive")

    elif master_type == "SKU":
        for key in ("product_id", "pack_size_id"):
            if not p.get(key):
                errors.append(f"{key}: required")
            else:
                try: UUID(str(p[key]))
                except ValueError: errors.append(f"{key}: must be a valid UUID")
        if p.get("variant_id"):
            try: UUID(str(p["variant_id"]))
            except ValueError: errors.append("variant_id: must be a valid UUID")
        if p.get("barcode"):
            barcode = str(p["barcode"]).strip()
            if not BARCODE_RE.match(barcode):
                errors.append("barcode: contains unsupported characters")
            if len(barcode) > 64:
                errors.append("barcode: maximum length is 64")

    elif master_type == "UOM_CONVERSION":
        for key in ("from_uom", "to_uom"):
            if str(p.get(key) or "").strip().lower() not in VALID_UOMS:
                errors.append(f"{key}: must be one of {sorted(VALID_UOMS)}")
        factor = _num(p, "factor", errors, min_value=0.000001)
        if p.get("from_uom") == p.get("to_uom") and factor is not None and factor != 1:
            errors.append("factor: same-UOM conversion must have factor 1")
        if not p.get("sku"):
            errors.append("sku: required")

    elif master_type in {"CUSTOMER", "SUPPLIER"}:
        if p.get("gstin"):
            gstin = str(p["gstin"]).strip().upper()
            if not GSTIN_RE.match(gstin):
                errors.append("gstin: invalid structural format")
        credit = _num(p, "credit_limit", errors, min_value=0)
        days = _num(p, "payment_terms_days", errors, min_value=0)
        if master_type == "CUSTOMER" and credit is not None and days is None:
            pass

    elif master_type == "WAREHOUSE":
        wt = str(p.get("warehouse_type") or "").strip().upper()
        if wt not in VALID_WAREHOUSE_TYPES:
            errors.append(f"warehouse_type: must be one of {sorted(VALID_WAREHOUSE_TYPES)}")

    elif master_type == "BIN":
        if not p.get("warehouse_id"):
            errors.append("warehouse_id: required")
        else:
            try: UUID(str(p["warehouse_id"]))
            except ValueError: errors.append("warehouse_id: must be a valid UUID")

    elif master_type == "TAX_PROFILE":
        gst = _num(p, "gst_rate", errors, min_value=0, max_value=100)
        cgst = _num(p, "cgst_rate", errors, min_value=0, max_value=100)
        sgst = _num(p, "sgst_rate", errors, min_value=0, max_value=100)
        igst = _num(p, "igst_rate", errors, min_value=0, max_value=100)
        cess = _num(p, "cess_rate", errors, min_value=0, max_value=100)
        if gst is not None and cgst is not None and sgst is not None and abs((cgst + sgst) - gst) > 0.01:
            errors.append("cgst_rate + sgst_rate must equal gst_rate for an intra-state profile")
        if gst is not None and igst is not None and abs(igst - gst) > 0.01:
            errors.append("igst_rate should equal gst_rate for the standard inter-state mapping")
        _ = cess

    elif master_type == "HSN":
        code = str(p.get("code") or "").strip()
        if not HEX_HSN_RE.match(code):
            errors.append("code: HSN must contain 4 to 8 digits")
        if p.get("tax_profile_id"):
            try: UUID(str(p["tax_profile_id"]))
            except ValueError: errors.append("tax_profile_id: must be a valid UUID")

    elif master_type == "PRICE_LIST":
        price = _num(p, "price", errors, min_value=0)
        floor = _num(p, "minimum_price", errors, min_value=0)
        disc = _num(p, "maximum_discount_pct", errors, min_value=0, max_value=100)
        if floor is not None and price is not None and floor > price:
            errors.append("minimum_price cannot exceed price")
        if p.get("sku") and not str(p["sku"]).strip():
            errors.append("sku: cannot be blank")
        _ = disc

    elif master_type == "TERRITORY":
        if p.get("state") and len(str(p["state"]).strip()) < 2:
            errors.append("state: must contain at least 2 characters")

    elif master_type == "ACCOUNTING_LEDGER_MAPPING":
        lt = str(p.get("ledger_type") or "").strip().upper()
        if lt not in VALID_LEDGER_TYPES:
            errors.append(f"ledger_type: must be one of {sorted(VALID_LEDGER_TYPES)}")
        if not str(p.get("external_ledger_name") or "").strip():
            errors.append("external_ledger_name: required")

    return errors
