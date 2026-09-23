# V90.b — Core Runtime & Database Connection Hardening

## Baseline
Built cumulatively from V90.a, preserving the V80–V90 implementation history.

## Completed
- Added a central SQLAlchemy database configuration layer.
- Added `DATABASE_URL` support with PostgreSQL/psycopg URL normalization.
- Added safe local SQLite fallback for developer/test execution.
- Added connection-pool controls (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`).
- Enabled `pool_pre_ping` by default for non-stale database connections.
- Added a runtime database ping (`SELECT 1`).
- Upgraded `/ready` to report `database: ok|<error type>` without changing `/health` semantics.
- Added dedicated regression tests for configuration, URL normalization, engine creation, and readiness reporting.

## Verification
Full regression suite: **52 passed**.

The V90 release identity remains authoritative in `config/release_manifest.json`; V90.b is a cumulative maintenance increment, not a replacement of V90.
