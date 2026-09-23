# V90.ga — Performance Certification Integration & Production Performance Gate

## Scope
Adds an evidence-backed integration gate that aggregates the existing V90.fy scalability readiness, V90.fz optimization certification, and V90.fx operational health controls, plus explicit production performance, capacity-headroom, and regression reviews.

## Deliverables
- `app/v90ga_performance_production_gate.py`
- `migrations/252_v90ga_performance_production_gate.sql`
- `web/performance_production_gate.html`
- `tests/test_v90ga_performance_production_gate.py`

## Controls
- Performance production gate by organization, period, release and environment.
- Required checks: scalability readiness, optimization certification, operational health, performance evidence, capacity headroom, regression control.
- PASS/WAIVED checks require evidence.
- Certification is blocked until derived and explicit controls are green.
- Period close requires prior certification and a green readiness result.
- Organization scope is enforced using the existing V90.fn security layer.

## Verification
- Focused V90.ga/V90.fz/release-integrity tests: 7 passed.
- Full cumulative suite: 499 passed, 1 pre-existing failure, 28 warnings.
- Known pre-existing failure: `tests/test_v90db_machine_oee.py::test_machine_oee_calculation`; expected availability 75.0%, actual 0.0%.
- PostgreSQL migration smoke: not run successfully because no live `DATABASE_URL`/PostgreSQL instance is available in this environment.
- GitHub remote CI and production deployment are not claimed as executed.
- External load/APM or production performance execution is not claimed; the milestone records and gates supplied evidence.
