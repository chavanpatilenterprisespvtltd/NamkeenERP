#!/usr/bin/env bash
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

python3 "$ROOT/scripts/preflight_deploy.sh"

docker compose --env-file "$ROOT/config/runtime.env" -f "$ROOT/deploy/docker-compose.production.yml" config >/dev/null
docker compose --env-file "$ROOT/config/runtime.env" -f "$ROOT/deploy/docker-compose.production.yml" up -d --build

python3 "$ROOT/scripts/post_deploy_smoke.py"
echo "${APP_VERSION:-v90.bh} ${ENVIRONMENT} deployment started and smoke-checked"
