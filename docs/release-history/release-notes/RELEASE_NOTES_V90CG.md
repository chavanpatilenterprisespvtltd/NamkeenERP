# V90.cg — GST Statutory Filing Data Engine + Reconciliation

Cumulative release from V90.cf, schema target 158.

## Added
- Filing-period snapshots with organization/entity/period scope
- Outward/inward taxable and GST classification totals
- Net tax calculation from statutory tax transactions
- Filing adjustment register with reason and status
- Filing period lock control
- Export-ready GST filing pack
- Filing UI and RBAC permissions

## Validation
- Focused V90.cg tests: 2/2 passed
- Python compilation: passed
- CI repository gate: passed
- Artifact checksum verification: 552 files passed
- Migration continuity: 61..158
- PostgreSQL migration smoke not claimed because DATABASE_URL is unavailable in this environment
- Known recursive legacy release-integrity test remains excluded because it can hang
