# V90.ef — Manufacturing Scheduling Execution from Approved Scenario

## Release
- Version: V90.ef
- Schema target: 207
- Builds cumulatively on V90.ee / migration 206.

## Scope
Adds the controlled execution stage after V90.ee approved factory-scenario handoff:

- creates a scheduling execution proposal from an approved scenario handoff
- maps work-centre scenario actions onto existing planned/approved manufacturing schedules
- proportionally reduces planned quantity and required hours when schedule-reduction hours are approved
- records approved overtime as auditable execution records
- approval workflow before execution
- controlled execution with optimistic before-value checks
- idempotent execution proposal creation per handoff
- execution-period close control
- role-based permissions
- Web UI

## Execution boundary
V90.ef does not silently execute a scenario at handoff time. It creates a PROPOSED execution, requires explicit approval, and only then changes matching manufacturing schedule quantities/hours. Overtime remains separately recorded as an approved/executed workforce scheduling adjustment.

## Migration
`207_v90ef_scheduling_execution.sql`

## Verification
- Focused V90.ef test: 2 passed
- Full pytest suite: 385 passed, 19 warnings, 0 failures
- Python compilation: passed
- CI repository gate: passed
- Migration continuity: 61..207
- Migration 207 SHA-256 verified against migration manifest
- Checksum verification: 814 files
- PostgreSQL migration smoke test: not run because no live DATABASE_URL/PostgreSQL instance is available
- GitHub Actions remote CI: not run/claimed
- Git commit: not claimed
- Production deployment: not claimed
