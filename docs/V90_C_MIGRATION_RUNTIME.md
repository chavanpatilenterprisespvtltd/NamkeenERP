# Namkeen ERP v90.c — Migration Runtime Hardening

## Goal
Make database schema upgrades deterministic, checksum-verified, ordered, and auditable without altering historical v89/v90 baselines.

## Added
- Migration manifest loader with contiguous-version validation.
- SHA-256 verification for every migration file before execution.
- PostgreSQL `schema_migrations` history table.
- Idempotent migration execution: previously applied migrations are skipped only when their checksum still matches.
- Target-version support for controlled upgrades.
- Explicit rejection of migration execution against SQLite development databases.

## Safety
Historical release archives remain immutable. v90.c is cumulative from v90.b.
