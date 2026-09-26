#!/usr/bin/env bash
# FILE PATH: scripts/deploy.sh
# ─── Deploy Script v1.1 (Session CS2 — preflight run with bash; real smoke check; v90.gx label) ─
# [Session CS2] FIX — `python3 scripts/preflight_deploy.sh` tried to run a bash script with Python and
# always failed. Confirmed this session by reading both files. THE FIX: run it with bash; smoke test
# now waits for /health and checks /ready and /version (scripts/post_deploy_smoke.py). Default label
# v90.gx instead of v90.bh. NOT touched: runtime.env requirement, compose invocation.
set -euo pipefail
ENVIRONMENT="${1:-staging}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/config/.env.${ENVIRONMENT}.example"

case "$ENVIRONMENT" in staging|production) ;; *) echo 'environment must be staging or production' >&2; exit 2;; esac

python3 "$ROOT/scripts/validate_deployment_config.py"

if [[ ! -f "$ROOT/config/runtime.env" ]]; then
  echo "Missing config/runtime.env. Copy the appropriate .env.${ENVIRONMENT}.example to config/runtime.env and replace placeholders with real values." >&2
  exit 4
fi

set -a
source "$ROOT/config/runtime.env"
set +a

bash "$ROOT/scripts/preflight_deploy.sh"  # [Session CS2] FIX — was run with python3 (it is a bash script)

docker compose --env-file "$ROOT/config/runtime.env" -f "$ROOT/deploy/docker-compose.production.yml" config >/dev/null
docker compose --env-file "$ROOT/config/runtime.env" -f "$ROOT/deploy/docker-compose.production.yml" up -d --build

python3 "$ROOT/scripts/post_deploy_smoke.py" --wait 120  # [Session CS2] real HTTP checks now
echo "${APP_VERSION:-v90.gx} ${ENVIRONMENT} deployment started and smoke-checked"
