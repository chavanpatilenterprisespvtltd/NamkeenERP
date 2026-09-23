# v75 — Master Data Administration

v75 introduces approval-controlled administration for core ERP masters. Master changes are requests first; approved changes are then applied by the appropriate authoritative service.

## Masters covered
- Product / Variant / Pack Size / SKU
- UOM and SKU conversion
- Customer / Supplier
- Warehouse / Bin / Scope assignment
- Tax profile / HSN
- Price list / territory
- Roles
- Accounting ledger mappings

## Controls
- Organization/entity scope
- CREATE / UPDATE / DEACTIVATE workflow
- Self-approval prevention
- Effective-dated records
- Historical snapshots
- Scope assignments
- Offline `client_event_id` idempotency
- Audit trail through `master_change_request` and `master_audit_snapshot`

## Important boundaries
Master administration does not directly post stock, tax, accounting, production or sales transactions. Those remain in their authoritative transaction services.

Customer-specific legal/tax data, GST rates, HSN applicability, price policies and accounting ledger mappings must be entered and approved by authorized customer users; v75 does not invent those values.
