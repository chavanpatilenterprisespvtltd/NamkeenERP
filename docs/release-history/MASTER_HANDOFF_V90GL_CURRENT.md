# Namkeen ERP — Master Handoff Current — V90.gl

## Continuity rule
This is a cumulative ERP program. Never restart, redesign, simplify, or replace the historical architecture. New work must begin from the latest valid release/source ZIP. The uploaded V90.gk release is the authoritative baseline for this release build.

## Current release
- Release: **V90.gl — Working Capital, Cash & Credit Management**
- Baseline: **V90.gk — Product/Batch Costing & Profitability Management**
- Schema target: **263**
- Migration: `263_v90gl_working_capital.sql`
- Migration SHA-256: `5915696315d49d1ece66f5f9b95aec0be536ca36bb476f0c5e55b67eec3849b7`
- Package SHA-256: `3126b529d02af408273211ed28566fc380e4b89d44629cd249d1383d19cd8322`

## V90.gl delivered
- Working-capital management snapshots
- Cash available and payment commitments
- Receivables / overdue receivables
- Payables / overdue payables
- Inventory value / inventory days
- Customer credit limit / utilization
- Collection target / realization
- DSO / DPO / cash conversion cycle
- Net working capital
- RBAC and organization/entity security scope
- API: `/v90gl/working-capital`
- UI: `/ui/working-capital`

## Validation
- Focused V90.gl + immediate chain: **13 passed**
- Historical-release compatibility assertions: **32 passed**
- Cumulative regression excluding known OEE defect: **529 tests reached 100% with no test failures**, but the pytest process did not exit within the shell timeout; therefore this is not recorded as a clean runner PASS.
- Known unrelated OEE defect: expected availability **75.0%**, observed **0.0%**.
- Compileall: PASS
- Checksum verification: PASS, **1,108 artifacts**
- CI repository gate: PASS
- ZIP integrity: PASS
- PostgreSQL migration smoke: **NOT RUN — no live DATABASE_URL/PostgreSQL instance available**
- GitHub remote CI: NOT RUN
- Production deployment: NOT RUN

## Next milestone
**V90.gm — Advanced Procurement & Supplier Performance Management**, unless the latest source/release supplied later establishes a newer valid release or a different higher-priority roadmap item.

Candidate scope: supplier scorecards, OTIF, price variance/PPV, quality rejection, lead-time performance, supplier concentration/risk, alternate suppliers, RFQ/quotation decision support, savings and procurement exception cockpit.

## Do not lose
- Entity X = manufacturing; Entity Y = marketing/sales; multi-company/intercompany remains mandatory.
- Preserve all historical migrations and genealogy.
- Do not fabricate PostgreSQL, remote CI, deployment, tests, hashes, or production status.
- Move to the next meaningful business capability once the current milestone is sufficiently complete; do not get stuck in micro-finetuning.
