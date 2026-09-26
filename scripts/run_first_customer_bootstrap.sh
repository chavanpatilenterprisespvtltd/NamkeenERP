#!/usr/bin/env bash
# FILE PATH: scripts/run_first_customer_bootstrap.sh
# ─── First-Customer Bootstrap Runner v1.1 (Session CS2 — calls the restored bootstrap/bootstrap.py with its real arguments) ─
# [Session CS2] FIX — the script called bootstrap/bootstrap.py, which was not in the repository, with
# --postgres-dsn/--bootstrap arguments the new bootstrap does not use. THE FIX: POSTGRES_DSN (kept for
# compatibility) is exported as DATABASE_URL; the generated admin password goes to ADMIN_PASSWORD_OUT
# (default ./first-admin-password.txt, chmod 600); the smoke test runs only when API_BASE_URL is set.
# generate_checksums.py is no longer called here (it would overwrite the release checksum file).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${POSTGRES_DSN:?Set POSTGRES_DSN to the target customer database DSN}"
export DATABASE_URL="${DATABASE_URL:-$POSTGRES_DSN}"
python3 "$ROOT/bootstrap/bootstrap.py" --config "${BOOTSTRAP_CONFIG:-$ROOT/config/customer_bootstrap.example.json}" --password-out "${ADMIN_PASSWORD_OUT:-$PWD/first-admin-password.txt}"
if [[ -n "${API_BASE_URL:-}" ]]; then python3 "$ROOT/scripts/post_deploy_smoke.py" --base-url "$API_BASE_URL"; fi
