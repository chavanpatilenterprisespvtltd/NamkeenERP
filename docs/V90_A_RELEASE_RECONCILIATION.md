# V90.a — Release Reconciliation & Foundation Hardening

## Purpose

V90.a is the first cumulative step after the v90 baseline. It does not discard or replace v90 functionality. It establishes a clean, machine-readable release identity and removes a versioning mismatch in the API entrypoint.

## Completed

1. Central release metadata loader: `app/release.py`.
2. API version is now sourced from `config/release_manifest.json`.
3. Added `/version` endpoint exposing ERP release, schema target and migration policy.
4. Updated README to identify v90 as the production baseline and v90.x as cumulative maintenance.
5. Added regression tests proving the release identity is internally consistent.
6. Existing 45-test baseline remains green; V90.a adds 3 reconciliation tests.

## Not claimed

This step does **not** claim that every production prerequisite listed in the v90 go-live gate has been independently deployed or integrated in this container. The go-live gate still requires evidence for PostgreSQL, Android release, external integrations, backup/restore and UAT.

## Next step

**V90.b — Core runtime/database connection hardening:** validate configuration loading, database connectivity checks, migration state checks, startup/readiness behavior, and safe failure reporting before moving deeper into business-service integration.
