from __future__ import annotations
from typing import Any

# UI-oriented schemas. Required fields are deliberately limited to stable administrative keys;
# customer-specific statutory/tax/commercial fields remain extensible through additional_fields.
SCHEMAS: dict[str, dict[str, Any]] = {
    "PRODUCT": {"label":"Product", "fields":[
        ("code","Code","text",True), ("name","Name","text",True), ("description","Description","textarea",False), ("active","Active","checkbox",False)]},
    "VARIANT": {"label":"Variant", "fields":[
        ("code","Code","text",True), ("name","Name","text",True), ("product_id","Product ID","uuid",True), ("description","Description","textarea",False)]},
    "PACK_SIZE": {"label":"Pack Size", "fields":[
        ("code","Code","text",True), ("name","Name","text",True), ("quantity","Quantity","number",True), ("uom","UOM","text",True)]},
    "SKU": {"label":"SKU", "fields":[
        ("sku","SKU Code","text",True), ("name","Name","text",True), ("product_id","Product ID","uuid",True), ("variant_id","Variant ID","uuid",False), ("pack_size_id","Pack Size ID","uuid",True), ("barcode","Barcode","text",False)]},
    "UOM_CONVERSION": {"label":"UOM Conversion", "effective":True, "fields":[
        ("code","Conversion Code","text",True), ("sku","SKU","text",True), ("from_uom","From UOM","text",True), ("to_uom","To UOM","text",True), ("factor","Factor","number",True)]},
    "CUSTOMER": {"label":"Customer", "fields":[
        ("code","Customer Code","text",True), ("name","Customer Name","text",True), ("phone","Phone","text",False), ("address","Address","textarea",False), ("gstin","GSTIN","text",False), ("credit_limit","Credit Limit","number",False)]},
    "SUPPLIER": {"label":"Supplier", "fields":[
        ("code","Supplier Code","text",True), ("name","Supplier Name","text",True), ("phone","Phone","text",False), ("address","Address","textarea",False), ("gstin","GSTIN","text",False), ("payment_terms_days","Payment Terms Days","number",False)]},
    "WAREHOUSE": {"label":"Warehouse", "fields":[
        ("code","Warehouse Code","text",True), ("name","Warehouse Name","text",True), ("warehouse_type","Warehouse Type","text",True), ("address","Address","textarea",False)]},
    "BIN": {"label":"Bin", "fields":[
        ("code","Bin Code","text",True), ("name","Bin Name","text",True), ("warehouse_id","Warehouse ID","uuid",True), ("zone","Zone","text",False), ("aisle","Aisle","text",False), ("rack","Rack","text",False)]},
    "TAX_PROFILE": {"label":"Tax Profile", "effective":True, "fields":[
        ("code","Tax Profile Code","text",True), ("name","Name","text",True), ("gst_rate","GST Rate %","number",True), ("cgst_rate","CGST %","number",False), ("sgst_rate","SGST %","number",False), ("igst_rate","IGST %","number",False), ("cess_rate","Cess %","number",False), ("reverse_charge","Reverse Charge","checkbox",False)]},
    "HSN": {"label":"HSN", "effective":True, "fields":[
        ("code","HSN Code","text",True), ("description","Description","text",True), ("tax_profile_id","Tax Profile ID","uuid",False)]},
    "PRICE_LIST": {"label":"Price List", "effective":True, "fields":[
        ("code","Price List Code","text",True), ("name","Name","text",True), ("sku","SKU","text",True), ("price","Price","number",True), ("minimum_price","Minimum/Floor Price","number",False), ("maximum_discount_pct","Maximum Discount %","number",False)]},
    "TERRITORY": {"label":"Territory", "fields":[
        ("code","Territory Code","text",True), ("name","Territory Name","text",True), ("state","State","text",False), ("district","District","text",False)]},
    "ROLE": {"label":"Role", "fields":[
        ("code","Role Code","text",True), ("name","Role Name","text",True), ("description","Description","textarea",False)]},
    "ACCOUNTING_LEDGER_MAPPING": {"label":"Accounting Ledger Mapping", "effective":True, "fields":[
        ("code","Mapping Code","text",True), ("ledger_type","Ledger Type","text",True), ("external_ledger_name","External Ledger Name","text",True), ("external_ledger_ref","External Ledger Ref","text",False), ("voucher_type","Voucher Type","text",False)]},
}

def field_meta(master_type: str) -> dict[str, Any]:
    if master_type not in SCHEMAS:
        raise KeyError(master_type)
    s = SCHEMAS[master_type]
    return {"master_type": master_type, "label": s["label"], "effective": bool(s.get("effective")),
            "fields": [{"key":k,"label":lbl,"type":typ,"required":req} for k,lbl,typ,req in s["fields"]]}

def validate_payload(master_type: str, payload: dict[str, Any], action: str) -> list[str]:
    if master_type not in SCHEMAS:
        return ["Unsupported master type"]
    errors=[]
    allowed={k for k,_,_,_ in SCHEMAS[master_type]["fields"]}
    if action != "DEACTIVATE":
        for k,lbl,_,req in SCHEMAS[master_type]["fields"]:
            if req and (k not in payload or payload.get(k) in (None, "")):
                errors.append(f"{lbl} is required")
    if action == "DEACTIVATE" and not str(payload.get("reason") or "").strip():
        errors.append("Deactivation reason is required")
    # Conservative numeric checks for structured forms.
    for k in allowed:
        if k in payload and payload[k] is not None and k.endswith(("rate","factor","limit","price","discount_pct","days")):
            try:
                v=float(payload[k])
                if v < 0: errors.append(f"{k} cannot be negative")
            except (TypeError,ValueError): errors.append(f"{k} must be numeric")
    return errors
