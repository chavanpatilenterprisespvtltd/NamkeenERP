# V90.ea — Workforce + Machine/OEE Integrated Performance

## Scope
- PostgreSQL migration 202.
- Cross-module link from V90.dz labour-standard performance to V90.db machine runs and OEE.
- Work-centre/department/product integrated snapshots.
- Labour efficiency, output per labour hour, labour cost per unit, OEE and weighted combined score.
- Labour-vs-OEE gap and configurable STRONG/WATCH/REVIEW thresholds.
- Auditable period close and role-based API/UI access.

## Verification
- 23 focused cumulative workforce + machine/OEE tests passed.
- Python compilation passed.
- CI repository gate passed.
- Application import and V90.ea route registration passed.
- Migration 202 SQLite syntax parse passed.
- Checksum generation/verification passed for 788 files.
- PostgreSQL migration smoke test was not run because no live DATABASE_URL/PostgreSQL instance is available.
- Full pytest suite was not run to completion; no full-suite pass is claimed.

## Cumulative maintenance fixes
- Corrected an extra closing parenthesis in the V90.do runtime SQLite table definition exposed by regression testing.
- Corrected an extra closing parenthesis in the V90.dp runtime incentive table definition exposed by regression testing.
