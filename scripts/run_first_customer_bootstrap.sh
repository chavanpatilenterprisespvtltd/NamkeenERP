#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${POSTGRES_DSN:?Set POSTGRES_DSN to the target customer database DSN}"
python3 "$ROOT/bootstrap/bootstrap.py" --root "$ROOT" --postgres-dsn "$POSTGRES_DSN" --bootstrap "$ROOT/config/customer_bootstrap.example.json"
python3 "$ROOT/scripts/generate_checksums.py"
python3 "$ROOT/scripts/post_deploy_smoke.py"
