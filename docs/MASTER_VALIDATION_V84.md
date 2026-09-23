# v84 — Master Data Validation & Business Rules

v84 adds a server-side cross-field validation layer before a master change request reaches approval.

## Covered rules

- Product/variant relationships and stable identifiers
- Pack-size quantity/UOM consistency
- SKU Product/Variant/Pack references and barcode structure
- UOM conversion validity and same-UOM factor rules
- Customer/Supplier GSTIN structural validation
- Customer/Supplier commercial numeric fields
- Warehouse type validation
- Bin → Warehouse UUID validation
- Tax profile rate ranges and CGST/SGST/IGST consistency
- HSN structural validation and Tax Profile relationship
- Price List floor-price and discount-range checks
- Accounting ledger type/name validation

## Safety boundary

Validation only rejects or accepts proposed master changes. It never writes the authoritative master directly. Approved changes continue through the v77 persistent master workflow, optimistic locking, effective dating and audit snapshots.

Statutory validations remain structural/configurable checks, not a claim that an ERP-only check replaces official GST/IRP/FSSAI or other authority validation.
