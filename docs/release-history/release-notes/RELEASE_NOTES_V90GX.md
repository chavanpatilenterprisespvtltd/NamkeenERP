# V90.gx — Security/Deployment Fixes + Company X/Y, GST Invoicing, X→Y Settlement, Plant Registers, Entry Screens

Baseline: V90.gw-hotfix5 / schema 273 (commit 72010f9)
Schema: 279 (new migrations 274–279; files 061–273 untouched)
Session: CS2 (26 Sep 2026) — every changed file carries a `[Session CS2]` changelog in its header.

## Why this release exists

The 26 Sep 2026 gap review (`ERP_GAP_REVIEW_2026-09-26.md` in the working folder) found blockers that stop real use:
public demo logins, a public token secret in production, an in-memory database in Docker, an invalid compose file,
no invoice numbering/printing, no X→Y transfer price, invoice or settlement, and read-only screens that need typed UUIDs.
This release fixes those; it is not a numbering-only release.

## Hotfixes already on `main` before this release (from the repository reflog)

| Hotfix | Change |
|---|---|
| V90.gw-hotfix1 | CI pytest gap (`requirements-dev.txt`), 2 date-fixture test failures, source-only tree |
| V90.gw-hotfix2 | Regenerated checksums for `ERP_MASTER_HANDOFF.md` / `RELEASE_GENEALOGY.md` drift |
| V90.gw-hotfix3 | Added missing `accounts` role (FK violation under PostgreSQL) |
| V90.gw-hotfix4 | Added the 11 other missing roles (FK violations under PostgreSQL) |
| V90.gw-hotfix5 | `security_login_attempts.success=0` comparison fixed for PostgreSQL |

## A. Security & deployment (blockers A1–A7)

| Item | Fix | Files |
|---|---|---|
| Demo `admin`/`manager` logins with `change-me` in every environment | Only in development/test (`APP_ENV`), switch-off with `DEMO_LOGIN_ENABLED=false` | `app/runtime_security.py`, `app/auth.py`, `app/__main__.py` |
| Tokens signed with public default secret in production | Reads `AUTH_TOKEN_SECRET` / `JWT_SECRET` or `*_FILE`; staging/production refuse missing, default or < 32-char secrets at startup | `app/runtime_security.py`, `app/auth.py` |
| `DATABASE_URL_FILE` ignored → in-memory SQLite in Docker | Reads `DATABASE_URL_FILE`; SQLite refused in staging/production | `app/db.py` |
| `erpadmin` seeded with `change-me` | Not seeded in staging/production unless `ERP_ADMIN_PASSWORD(_FILE)` is safe; first admin comes from `bootstrap/bootstrap.py` | `app/identity.py` |
| Compose file invalid YAML | Healthcheck in exec form; API applies migrations on start (`RUN_MIGRATIONS=true`) | `deploy/docker-compose.production.yml` |
| API image missing `web/`, `migrations/`, `config/` | Images copy them and use the entrypoint | `docker/api.Dockerfile`, `docker/worker.Dockerfile`, `docker/entrypoint.sh` |
| `bootstrap/bootstrap.py` missing | New idempotent bootstrap: org, entities X/Y, sites, warehouses, first Super Admin (password to a chmod-600 file) | `bootstrap/bootstrap.py`, `scripts/run_first_customer_bootstrap.sh` |
| `deploy.sh` ran a bash script with python3; smoke test printed PASS without checking | Fixed; smoke test now calls `/health`, `/ready`, `/version`, `/auth/me` | `scripts/deploy.sh`, `scripts/preflight_deploy.sh`, `scripts/post_deploy_smoke.py` |
| Migration smoke could not import `app` in CI | Repo root added to `sys.path`; runtime schema created first | `scripts/migration_smoke.py` |
| Migration chain failed at 073 on a fresh PostgreSQL database (072/073 define `master_validation_run` differently) | Fix-forward **279**; 073–075 listed as `superseded` in the manifest (files and checksums unchanged) — the runner records them without executing | `migrations/279_…`, `app/migrations.py`, `config/migration_manifest.json` |
| Dispatch failed on PostgreSQL (FK `dispatch_lines → dispatches`) | Header inserted before lines | `app/v90ag_dispatch_execution.py` |
| Login returned HTTP 500 on PostgreSQL | `record_login_attempt()` sends a real boolean | `app/v90bf_security_hardening.py` |
| Scope checks failed on PostgreSQL (`boolean = integer`) | `active=TRUE/FALSE` in access-scope SQL | `app/access_scope.py`, `app/master_scope.py`, `app/v90fn_security_rbac_scope_hardening.py` |

New: `app/migrate_cli.py` (`python -m app.migrate_cli [--verify-only]`).

## B. New business functions

1. **Company X / Y profile** (`/ui/company-profile`, `app/v90gx_company_gst_invoicing.py`, migration 274):
   legal & trade name, role (Manufacturer = X, Sales & Marketing = Y), GSTIN (format, check digit, state and PAN
   consistency), PAN, CIN, FSSAI licence + validity, address/state, bank/IFSC/UPI, invoice prefix.
2. **GST tax invoice**: FY series `PREFIX/YY-YY/NNNN` (16-character GST limit enforced), auto-allocated at dispatch when
   no number is typed; CGST+SGST vs IGST from seller/buyer state; printable invoice
   (`/v90gx/sales-invoices/{id}/print`) with GSTIN, FSSAI, HSN, amount in words, bank; e-way and IRN recording.
3. **E-way rule**: consignment value above the threshold blocks dispatch without a 12-digit e-way bill number.
   Seeded: default ₹50,000; Maharashtra intra-state ₹1,00,000 / inter-state ₹50,000 — editable, verify before go-live.
4. **Advance terms** (e.g. super-stockist 50 % advance, balance in 7 days): dispatch blocked until advance recorded.
5. **Dispatch bug fixed**: multi-line orders failed (`UNIQUE constraint failed: sales_invoice_lines.invoice_line_id`).
6. **Intercompany X→Y** (`/ui/intercompany-xy`, `app/v90gx_intercompany_settlement.py`, migration 275):
   transfer-price policy agreed by X and Y (cost-plus / fixed / Y's price minus %) — **no default price**;
   pricing with GST; X dispatch creates X's tax invoice and stock goes in transit; Y receipt (short receipt needs a
   reason); settlement Y→X with outstanding balance; the old one-step `/v90fm/…/post` is refused for policy-priced transfers.
   Intercompany moves now also update `inventory_stock_balance` (`app/stock_balance.py`).
7. **Business date** on production batches (with shift) and machine runs; OEE periods use it
   (`app/business_date.py`, migration 276). Back-dating limit `BUSINESS_DATE_MAX_BACKDATE_DAYS` (default 7).
8. **Plant registers** (`/ui/plant-registers`, `app/v90gx_plant_operations.py`, migration 277): frying-oil log with
   TPM > 25 % = DISCARD_REQUIRED, fuel/wood, electricity/water meters, carton consumption variance, customer complaints
   (food-safety categories auto HIGH, HIGH needs CAPA to close), purchase return to supplier with stock-out and debit note.
9. **Notifications** (`app/v90gx_notifications.py`, migration 278): outbox; SMS/WhatsApp through an HTTPS webhook
   gateway, e-mail through SMTP; `stub` never reports SENT. Daily alerts: FSSAI expiry, open HIGH complaints, oil discard.
   `app/worker.py` now processes the outbox (was an empty sleep loop).
10. **Screens**: `/ui/daily-work` hub; every existing screen that asked for Organization/Entity/Location/Warehouse IDs
    now shows dropdowns (`web/assets/scope-picker.js`, injected by `app/v90gx_ui_support.py`; no page file edited).

## C. Verification actually performed (Session CS2)

- `pytest` on SQLite (CI configuration, Python 3.12): **577 passed, 0 failed** (552 before + 25 new V90.gx tests).
- `scripts/ci_gate.py` passed; `scripts/validate_deployment_config.py` passed; compose file parses as YAML.
- PostgreSQL 16 (local, empty database): `python -m app.migrate_cli` applied **061–279**; a second run applied nothing;
  `scripts/migration_smoke.py` reached schema 279.
- PostgreSQL 16 with `APP_ENV=production` and file secrets: app starts; it refuses to start without a token secret or
  database URL; `bootstrap/bootstrap.py` created X/Y, sites, warehouses and the first admin; demo users and
  `change-me` are rejected; the admin can sign in.
- All 25 new V90.gx tests also pass on PostgreSQL 16.
- Full suite on a migrated PostgreSQL 16 database: **381 passed / 196 failed** (before this release 301 / 258). Most
  remaining failures come from older test fixtures that insert `1` into BOOLEAN columns (268 such errors); the rest are
  PostgreSQL SQL issues in older modules (`substr()` on dates, untyped `:param IS NULL`, `text < timestamp`, `OR` syntax).
  These are the next work item; SQLite results are unaffected.
- Headless Chromium: company profile save, transfer-price policy, X→Y create → price → dispatch (invoice
  XMFI/26-27/0001) → short receipt → part payment, oil log, dropdowns on the existing Sales screen — no failed requests.
- Not done: real SMS/WhatsApp/SMTP gateway, GST IRP / e-way portal APIs, Android client, GitHub Actions run.

## Manual step (files the remote tools may not write)

`config/.env.production.example` and `config/.env.staging.example` were not changed by this session (the remote file
tools refuse `.env.*` files). Copy the V90.gx block at the end of `config/.env.example` into both and set
`APP_VERSION=v90.gx`; then run `python scripts/generate_checksums.py` and commit `artifact_checksums.json`.
All the new settings have safe defaults in code, so nothing breaks if this is done later.

## Still open

Incentive slabs (business input needed), Android client, entry screens for older flows (GRN/QC/batch/packing still use
their existing screens + APIs), PostgreSQL portability of older modules and their test fixtures.
