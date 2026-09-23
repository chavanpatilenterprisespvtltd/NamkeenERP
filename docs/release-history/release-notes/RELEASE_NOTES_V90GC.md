# V90.gc — Production Release Certification & Cutover Integration

Schema target: **254**  
Migration: `254_v90gc_production_release_certification.sql`

## Purpose
V90.gc makes the V90.gb production-readiness result an explicit hard prerequisite in the production release certification chain, integrating UAT, deployment/rollback, backup/DR, operational health, and business-owner signoff.

## Controls
- V90.gb performance production-readiness gate must be CLOSED.
- V90.ft UAT plan must be CERTIFIED for the period.
- V90.fv deployment controls must be PASS/WAIVED and a rollback drill must PASS.
- V90.fw must have successful backup, passed restore validation, and passed DR recovery drill.
- V90.fx must have no failing health checks, open critical alerts, or unresolved critical incidents.
- Explicit business-owner signoff is required with evidence.
- Certification lifecycle: REQUESTED → CERTIFIED → CLOSED; failed prerequisites block certification.

## API/UI
- API root: `/v90gc/production-release/certifications`
- Readiness: `/v90gc/production-release/certifications/{id}/readiness`
- UI: `/ui/production-release-certification`
- Permissions: `release.production_certification.view`, `release.production_certification.manage`

## Validation
- Focused V90.gc tests: 3 passed.
- Targeted regression set after manifest rollover: 16 passed.
- Full cumulative suite: **505 passed, 1 pre-existing failure, 28 warnings**.
- Pre-existing failure: `tests/test_v90db_machine_oee.py::test_machine_oee_calculation` — expected availability 75.0%, actual 0.0%.
- Python compilation: PASS.
- CI repository gate: PASS.
- Checksums: 1,060 files verified.
- PostgreSQL migration smoke test was not run because no live DATABASE_URL/PostgreSQL instance is available.
- GitHub remote CI: not performed.
- Production deployment: not performed.
- External production/APM performance execution: not performed.
