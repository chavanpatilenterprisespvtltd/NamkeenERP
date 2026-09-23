# Production Deployment Plan

## Current deployment assets

- Docker API image: `docker/api.Dockerfile`
- Worker image: `docker/worker.Dockerfile`
- Production Compose: `deploy/docker-compose.production.yml`
- Preflight/deployment scripts under `scripts/`
- GitHub Actions under `.github/workflows/`

## Required environment

- PostgreSQL 16-compatible production database
- secrets for database credentials and application authentication
- object storage if enabled
- Tally/GST/e-way integrations only when their real credentials/endpoints are configured
- monitoring/logging
- backup storage and restore procedure

## Before production

1. Run migration smoke on a disposable staging database.
2. Validate schema/checksums.
3. Run backup and restore drill.
4. Run security/RBAC tests.
5. Run performance/load tests.
6. Deploy staging.
7. Run role-based and E2E UAT.
8. Perform cutover and rollback rehearsal.
9. Obtain business sign-off.

## Production rule

No production claim is valid until the real environment has been exercised and evidence recorded.
