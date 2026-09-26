#!/usr/bin/env sh
# FILE PATH: docker/entrypoint.sh
# ─── Container Entrypoint v1.1 (Session CS2 — actually used by both images; runs migrations on request) ─
#
# [Session CS2] FIX — ENTRYPOINT WAS NEVER USED AND STILL DEFAULTED TO v90.bh.
# Confirmed this session by reading docker/api.Dockerfile and docker/worker.Dockerfile: neither had
# an ENTRYPOINT, so the APP_ENV check below never ran; APP_VERSION defaulted to v90.bh.
# THE FIX: both Dockerfiles now use this script as ENTRYPOINT. APP_VERSION default removed (the
# release comes from config/release_manifest.json inside the image). When RUN_MIGRATIONS=true the
# ordered, checksum-verified migrations are applied before the process starts (api service only).
# NOT touched: the allowed APP_ENV values (staging|production) for containers.
set -eu

: "${APP_ENV:=staging}"

case "$APP_ENV" in
  staging|production) ;;
  *) echo "APP_ENV must be staging or production" >&2; exit 2 ;;
esac

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "Applying database migrations before start..."
  python -m app.migrate_cli
fi

exec "$@"
