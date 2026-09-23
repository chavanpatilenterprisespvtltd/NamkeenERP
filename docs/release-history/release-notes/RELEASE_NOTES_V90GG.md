# V90.gg — Operational Handover, Hypercare & Closure Certification

Schema 258. Continues V90.gf.

## Scope
- Operational handover and hypercare control layer.
- Requires V90.gf final go-live closure to be CLOSED.
- Tracks explicit health, critical-issue, hypercare evidence, support ownership, and KPI acceptance controls.
- Records dated hypercare checkpoints with health, incidents, critical issue count, KPI status, and evidence.
- Supports evidence-controlled acceptance and closure.
- RBAC: `release.hypercare.view`, `release.hypercare.manage`.
- UI: `/ui/operational-handover-hypercare`.

## Verification
- Focused V90.gg and cumulative go-live chain tests: PASS.
- Full cumulative suite: 517 passed, 1 pre-existing failure, 28 warnings.
- Pre-existing failure: `tests/test_v90db_machine_oee.py::test_machine_oee_calculation` (expected availability 75.0%, actual 0.0%).
- Python compilation: PASS.
- CI repository gate: PASS.
- Checksums: 1,080 files verified.
- PostgreSQL migration smoke: not executed because no live `DATABASE_URL` is available.
- GitHub remote CI and actual production deployment: not performed.
