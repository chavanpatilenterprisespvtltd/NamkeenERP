# V90.cd — Advanced Financial Integration & Statutory Reporting

Cumulative release from V90.cc.

## Delivered
- Fixed-asset depreciation -> accounting posting bridge with idempotency.
- Loan interest -> accounting posting bridge with idempotency.
- Profit & Loss report foundation.
- Balance Sheet report foundation and balance check.
- Cash Flow report foundation for cash/bank ledger movement.
- Financial reporting/integration RBAC.
- Financial Reports web workspace.
- Migration 155.

## Controls
- Organization/entity filters are configuration-driven.
- Existing accounting ledger mappings are reused; no company, ledger, GST, product or rate values are hard-coded.
- Integration postings are source-idempotent.
