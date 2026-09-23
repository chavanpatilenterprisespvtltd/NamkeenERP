# Consolidation Validation Report — Candidate 1.0

Date: 2026-09-14

## Source

- Input: `Namkeen_ERP_V90_GW_ERP_COMPLETION_AUDIT_RELEASE.zip`
- Code baseline: V90.gw
- Schema target: 273
- Consolidated repository: `NAMKEEN_ERP_PRODUCTION_CANDIDATE_1_0`

## Results

| Check | Result | Evidence |
|---|---|---|
| Repository CI gate | PASS | `python scripts/ci_gate.py` |
| Migration continuity | PASS | migrations 061–273, 213 files |
| Artifact checksum verification | PASS | 1185 files |
| Python compilation | PASS | `python -m compileall -q app scripts tests` |
| Focused V90.gs–V90.gw tests | PASS | 10 passed |
| Consolidation compatibility tests | PASS | 24 passed |
| Full cumulative regression | PASS with 2 known baseline failures | 550 passed, 2 failed, 28 warnings |
| PostgreSQL live migration smoke | NOT RUN | no PostgreSQL runtime available in this environment |
| Production deployment | NOT RUN | not attempted |
| Real Android device/offline test | NOT RUN | requires device/environment |

## Known full-regression failures

1. `tests/test_v90db_machine_oee.py::test_machine_oee_calculation` — observed availability 0.0% versus expected 75.0% in the existing test. This is a pre-existing baseline issue and was not changed during consolidation.
2. `tests/test_v90gp_manufacturing_workforce_integration.py::test_dashboard_and_snapshot` — observed batch count 0 versus expected 1 for the fixed 2026-09-12 test date. This is a pre-existing/date-fixture issue and was not changed during consolidation.

These failures are explicitly retained as release-blocking UAT/technical validation items until reproduced or dispositioned in a real staging environment.

## Source hygiene

- No local database files retained.
- No `.env` secret files retained.
- No Python bytecode retained.
- No pytest cache retained.
- Historical release artifacts are organized under `docs/release-history/`.

## Conclusion

**Candidate 1.0 consolidation is complete as a source-packaging milestone.** The ERP is not yet production-certified. The next milestone is live staging environment validation followed by security, backup/DR, performance and role-based/E2E UAT.
