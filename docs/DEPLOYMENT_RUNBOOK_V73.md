# v73 Deployment Runbook

## Pre-deployment
- Verify target host resources and DNS/TLS.
- Verify secret references exist without printing secret values.
- Verify last database backup and restore status.
- Verify object-storage and notification provider configuration.
- Verify Tally/IRP/EWB credentials are supplied only through the target secret mechanism.
- Verify exact artifact SHA-256 manifest.

## Migration
- Take a fresh database backup.
- Apply migrations in order through 062.
- Stop on checksum mismatch.
- Record migration evidence.

## Deployment
- Start PostgreSQL.
- Start API and worker.
- Verify `/health` and `/ready`.
- Run smoke tests.
- Run UAT.

## Production promotion
Promote the exact immutable artifact digest validated in staging. Do not rebuild from source between staging and production.

## Android
Build/sign the release APK or AAB using customer-controlled keystore secrets. Record artifact SHA-256 before distribution.

## Rollback
Use the v72/v73 restore-based rollback procedure. Do not execute destructive schema-down commands in production.
