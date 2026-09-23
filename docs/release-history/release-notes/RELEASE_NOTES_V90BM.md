# V90.bm — Product Master + Recipe/BOM + Procurement UI

Implemented the transactional UI layer over the existing Product Master, Recipe/BOM and Procurement APIs.

- Product Master UI and grouped Product/Variant/Pack Size/SKU/UOM views
- Recipe/BOM listing with status, version, yield and expected-loss visibility
- Procurement dashboard with requisition/quote/PO/GRN counts and recent POs
- User-specific transactional screen filter/column preferences
- Mobile-supported transaction screen registry
- RBAC: transaction_ui.view / transaction_ui.manage
- Migration 138

Validation: 244 cumulative tests passed; CI repository gate passed; migration 61-138 contiguous; Python compilation passed.
