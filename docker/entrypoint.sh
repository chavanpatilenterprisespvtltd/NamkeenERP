#!/usr/bin/env sh
set -eu

: "${APP_ENV:=staging}"
: "${APP_VERSION:=v90.bh}"

case "$APP_ENV" in
  staging|production) ;;
  *) echo "APP_ENV must be staging or production" >&2; exit 2 ;;
esac

exec "$@"
