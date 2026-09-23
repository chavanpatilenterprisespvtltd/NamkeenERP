# V90.dg — HR, Workforce & Labour Allocation Foundation

Cumulative release after V90.df; schema target 184.

## Scope
- Employee master with entity and organization scope
- Shift master and standard hours
- Attendance capture
- Production-batch labour allocation
- Hourly labour cost calculation
- Labour allocation approval
- Workforce dashboard
- RBAC for workforce, attendance and labour allocation

## Verification
- Focused tests: 2/2 passed
- Python compile: passed
- CI repository gate: passed
- Artifact checksum verification: passed
- Migration 184 checksum: `$(sha256sum $ROOT/migrations/184_v90dg_hr_workforce.sql | awk '{print $1}')`
- PostgreSQL migration smoke not claimed without DATABASE_URL.
