# V90.ap — Supplier Payables, Outstanding & Supplier Ageing

Implemented supplier-side accounts payable controls on the V90.ao baseline.

## Scope
- Supplier purchase invoice capture with entity-scoped duplicate protection
- Supplier payment capture with entity-scoped reference protection
- Supplier payment allocation to posted supplier invoices
- Over-allocation prevention at payment and invoice level
- Supplier-wise outstanding and ageing buckets
- Overdue supplier invoice endpoint
- Supplier payment follow-up recording
- Entity/location permission and scope enforcement
- PostgreSQL migration 115

## Verification
- Cumulative tests: 170 passed, 0 failed
- Migration sequence: 61 through 115 contiguous
- Migration checksum manifest: updated and verified
- Python compilation: passed
- ZIP integrity: verified

