# V90.bh Deployment Guide

## Runtime configuration

Do not deploy directly from `.env.*.example`. Create `config/runtime.env` from the matching example and replace every secret-file path with a real mounted secret path.

## Preflight

Run:

```bash
python3 scripts/validate_deployment_config.py
scripts/preflight_deploy.sh
```

## Deploy

```bash
scripts/deploy.sh staging
```

or:

```bash
scripts/deploy.sh production
```

The script validates configuration, validates release checksums and critical tests, validates the Compose model, rebuilds containers, waits on PostgreSQL health, and runs the existing post-deployment smoke test.

## Docker security

Secrets are supplied through Docker secrets rather than plain Compose environment values. API and worker containers run as non-root users. PostgreSQL persists only through the named `postgres_data` volume.

## Rollback

Use the existing rollback/restore runbooks. Database restore remains an explicitly controlled operation; do not automatically destroy or replace the live database from the deployment script.
