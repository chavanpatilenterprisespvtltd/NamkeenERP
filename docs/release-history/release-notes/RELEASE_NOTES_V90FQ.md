# V90.fq — ERP Critical-Action Governance Certification

## Release
- Release: V90.fq
- Schema target: 243
- Migration: `243_v90fq_governance_certification.sql`

## Scope
V90.fq certifies governance coverage for the critical transactional action surface established by V90.fo/V90.fp. It provides a controlled certification registry, coverage calculation, evidence-backed exceptions, exception resolution, and period-close guardrails.

## Critical action catalog
- PROCUREMENT.WRITE
- RECEIVING_QC.WRITE
- INVENTORY.WRITE
- PRODUCTION.WRITE
- PROCESS_QC.WRITE
- BATCH_PACKING.WRITE
- FG_DISPATCH.WRITE
- SALES.WRITE
- RETURNS.WRITE
- RETURN_DISPOSITION.WRITE
- ACCOUNTING.WRITE
- INTERCOMPANY.WRITE

## APIs
- `POST /v90fq/governance/certifications`
- `POST /v90fq/governance/certifications/bootstrap`
- `GET /v90fq/governance/certifications`
- `GET /v90fq/governance/coverage`
- `POST /v90fq/governance/exceptions`
- `GET /v90fq/governance/exceptions`
- `POST /v90fq/governance/exceptions/{exception_id}/resolve`
- `POST /v90fq/governance/{period_key}/close`
- UI: `/ui/governance-certification`

## Controls
- Organization security scope is checked through the existing V90.fn security foundation.
- Certification resolution requires evidence reference and resolution note.
- Normal period close is blocked while open certification exceptions or uncertified critical actions remain.
- `force=true` is an explicit governance override and is not the normal close path.
- No maintenance, inventory, production, sales, accounting, or intercompany transaction is automatically mutated by certification.

## Verification
- V90.fq focused tests: 5 passed.
- Full cumulative suite: 468 passed, 1 unrelated pre-existing failure, 27 warnings.
- Python compilation: PASS.
- CI repository gate: PASS.
- Artifact checksums: 1,004 files verified.
- PostgreSQL migration smoke: not successfully executed because no live `DATABASE_URL`/PostgreSQL instance was available.
- GitHub remote CI: not run.
- Production deployment: not run.

## Known pre-existing regression
`tests/test_v90db_machine_oee.py::test_machine_oee_calculation` remains failing: expected availability 75.0%, actual 0.0%. This is unrelated to V90.fq and was not changed in this release.
