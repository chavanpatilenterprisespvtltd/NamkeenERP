# Namkeen ERP — Master Handoff V90.gu

Current release: **V90.gu**
Schema: **271**
Baseline: **V90.gt / schema 270**

## Completed
Mobile adapters for the remaining V90.gs transaction types: receipt confirmation, production confirmation, stock count evidence, and quality confirmation.

## Key endpoint
`POST /v90gu/mobile/transactions/{integration_id}/execute`

## Controls
- Existing ERP transaction tables remain systems of record.
- Receipt confirmation validates against an existing GRN and never bypasses incoming QC.
- Production confirmation records output and completes an eligible running batch, with existing QC and 125% output guardrail.
- Stock-count variance is recorded as evidence only; it does not directly post a stock adjustment.
- Quality confirmation requires quality.manage permission and release checks failed results/open NCs.
- Execution is idempotent and audited.
- Entity/location RBAC is enforced.

## Validation
Focused: 5 passed across V90.gu/V90.gt/V90.gs.
Cumulative excluding known OEE: 544 passed, 1 pre-existing V90.gp failure. See BUILD_VERIFICATION_V90GU.txt.
Compileall, checksum verification and CI repository gate passed.
PostgreSQL smoke test was not run because no live DATABASE_URL/PostgreSQL instance is available.

## Continuity
Preserve all historical migrations and releases. Do not restart or redesign. Entity X remains manufacturing and Entity Y remains marketing/sales with multi-company/intercompany architecture. Known historical OEE defect remains separate and must not be hidden.

## Next milestone
**V90.gv — Mobile Transaction Exception / Reconciliation / Approval Control**, covering failed/partial/conflict/retry states and controlled exception resolution before final ERP hardening and UAT.
