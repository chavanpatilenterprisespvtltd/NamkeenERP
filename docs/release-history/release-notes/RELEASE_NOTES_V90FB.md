# V90.fb — Enterprise Reliability Benchmarking

Schema target: **228**.

Adds normalized, advisory reliability benchmarking across comparable entities and work centers using the closed-loop reliability controls already established through V90.fa.

## Included
- Entity-level reliability peer ranking within an organization and period.
- Work-center benchmarking from observed change-effectiveness records.
- Transparent normalized benchmark score using control, effectiveness, target attainment and standard adoption.
- Internal best-practice ranking and benchmark-gap assessment.
- Benchmark exception queue with explicit resolution.
- Period close guard; `force=true` is required to close with open benchmark exceptions.
- Web UI at `/ui/maintenance-reliability-benchmark`.

## Control boundary
Benchmarking is advisory and observational. It does **not** automatically alter maintenance plans, work orders, schedules, standards, approvals or other operational records. Cross-company benchmarking is not inferred; peers are limited to the same organization and comparable scope type.

## Verification
- V90.fb focused tests: PASS
- V90.e* cumulative regression: PASS
- Python compilation: to be run in release verification
- CI repository gate: to be run in release verification
- Migration continuity/checksums/ZIP integrity: to be run in release verification
- PostgreSQL smoke: not run unless a live PostgreSQL `DATABASE_URL` is supplied
