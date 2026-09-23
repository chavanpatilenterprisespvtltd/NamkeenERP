# V90.ck — GST Final Statutory Close + Compliance Dashboard

## Scope
Cumulative release from V90.cj (schema 161) to schema 162.

## Added
- Final statutory close evaluation gate
- Return/compliance filing validation
- GST settlement reconciliation/sign-off gate
- Filing acknowledgement validation
- Unresolved exception gate
- Final statutory period lock
- Controlled reopen with mandatory reason
- Close audit trail
- Entity/organization-aware compliance dashboard
- Statutory close export pack
- RBAC: gst_close.view, gst_close.manage, gst_close.signoff
- Migration 162

## Verification
- V90.ck focused tests: 2/2 passed
- Python compileall: passed
- CI repository gate: passed
- Artifact checksum verification: 573/573 passed
- Migration continuity: 61 through 162 verified by CI gate
- PostgreSQL migration smoke not run because DATABASE_URL is unavailable
- Known recursive legacy release-integrity test remains excluded because it can hang
