# V90.fc — Reliability CAPA Integration

Schema target: 229

## Scope
- Converts recurring reliability failures and enterprise benchmark exceptions into controlled CAPA records.
- Links reliability triggers to the existing `quality_capa` CAPA workflow.
- Adds root-cause, corrective/preventive action, owner and due-date support.
- Adds CAPA effectiveness evidence through the existing `capa_effectiveness` verification boundary.
- Adds overdue CAPA queue and controlled period closure.
- No automatic maintenance-plan or other operational mutation is performed.

## API/UI
- POST `/v90fc/maintenance/reliability-capa/generate`
- POST `/v90fc/maintenance/reliability-capa/{capa_id}/effectiveness`
- GET `/v90fc/maintenance/reliability-capa/dashboard`
- GET `/v90fc/maintenance/reliability-capa/overdue`
- POST `/v90fc/maintenance/reliability-capa/{period_key}/close`
- GET `/ui/maintenance-reliability-capa`

## Verification
- Focused V90.fb + V90.fc tests: PASS (4)
- Python compilation: PASS
- CI repository gate: PASS
- Checksum generation/verification: PASS (931 files)
- PostgreSQL migration smoke: not run successfully because no live `DATABASE_URL`/PostgreSQL instance is available.
- Full pytest suite: not claimed as complete.
- Remote GitHub CI/push and production deployment: not performed.

# V90.fd — Reliability Audit & Compliance

Adds reliability audit snapshots, evidence completeness checks, approval compliance checks, workflow-integrity unauthorized-change detection, audit exception queue/resolution, and controlled audit closure. Detection is advisory/control-oriented and is not a database write interceptor.
