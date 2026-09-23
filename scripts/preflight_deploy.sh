#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_ENV="${APP_ENV:-staging}"

python3 "$ROOT/scripts/validate_deployment_config.py"
python3 "$ROOT/scripts/verify_checksums.py"
python3 -m pytest -q "$ROOT/tests/test_v90_release_integrity.py" "$ROOT/tests/test_v90bg_backup_restore.py"
for f in config/.env.example config/customer_bootstrap.example.json; do
  test -s "$ROOT/$f" || { echo "missing $f" >&2; exit 1; }
done
printf 'V90.bh deployment preflight completed for %s\n' "$APP_ENV"
