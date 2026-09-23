# V90.by — GST / HSN / Tax Master + Statutory Reporting Foundation

## Implemented
- Configurable organization-scoped HSN/SAC master with effective dates and active status.
- Configurable GST rate master with intra-state CGST/SGST and inter-state IGST split.
- Cess support.
- Tax calculation service with rounded monetary outputs.
- Auditable tax transaction-line capture linked to source documents.
- Organization/entity/period tax summary for taxable value, IGST, CGST, SGST, cess and total GST.
- Tax control web workspace at `/ui/tax`.
- RBAC permissions: `tax.view`, `tax.manage`.
- Migration target: 150.

## Architecture
No company, product, HSN, GST rate, entity, warehouse, territory, user or approval level is hard-coded. Tax masters are configuration-driven and organization scoped, preserving the multi-company ERP model.

## Verification
- V90.by focused tests: 5/5 passed.
- Python compilation: passed.
- Repository/migration CI gate: passed.
- Artifact checksum verification: passed (511 files).
- Full cumulative pytest was started but exceeded the local 120-second execution window; it was not claimed as passed. The known recursive release-integrity test remains excluded because it can hang.
- PostgreSQL migration smoke was not run locally because no configured `DATABASE_URL` was available.
