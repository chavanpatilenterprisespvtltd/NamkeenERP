#!/usr/bin/env bash
# FILE PATH: scripts/preflight_deploy.sh
# ─── Deploy Preflight v1.1 (Session CS2 — also verifies migration manifest; version-neutral message) ─
# [Session CS2] FIX — message hard-coded "V90.bh"; migration manifest/checksums were not verified.
# THE FIX: add `app.migrate_cli --verify-only`; neutral message. NOT touched: existing checks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_ENV="${APP_ENV:-staging}"

python3 "$ROOT/scripts/validate_deployment_config.py"
python3 "$ROOT/scripts/verify_checksums.py"
python3 -m pytest -q "$ROOT/tests/test_v90_release_integrity.py" "$ROOT/tests/test_v90bg_backup_restore.py"
for f in config/.env.example config/customer_bootstrap.example.json; do
  test -s "$ROOT/$f" || { echo "missing $f" >&2; exit 1; }
done
python3 -c "import sys; sys.path.insert(0, '$ROOT'); from app.migrate_cli import main; main(['--verify-only'])"
printf 'Namkeen ERP deployment preflight completed for %s\n' "$APP_ENV"
