# Automated Testing Strategy

## Required layers

1. Repository/CI gate
2. Python compilation
3. Migration continuity/checksum verification
4. Focused module tests
5. Cumulative regression tests
6. PostgreSQL migration smoke test
7. Android build
8. Deployment smoke test

## Evidence policy

A test is **PASS** only when it actually ran and passed. A timeout, unavailable database, skipped integration, or static inspection must be recorded as such.

## Known historical exceptions

See `docs/ERP_MASTER_HANDOFF.md`. The OEE and V90.gp fixed-date issues must not be silently hidden.
