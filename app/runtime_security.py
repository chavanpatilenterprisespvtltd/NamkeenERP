# FILE PATH: app/runtime_security.py
# ─── Runtime Security Configuration v1.0 (Session CS2 — one place that decides dev vs staging/production secrets) ─
#
# [Session CS2] FEATURE — CENTRAL RUNTIME ENVIRONMENT, SECRET-FILE AND PRODUCTION-SAFETY RULES.
# Confirmed this session by reading app/auth.py, app/db.py, app/identity.py, app/__main__.py,
# config/.env.production.example and deploy/docker-compose.production.yml of V90.gw-hotfix5:
#   - the Docker/production templates supply JWT_SECRET_FILE and DATABASE_URL_FILE, but the code
#     only read AUTH_TOKEN_SECRET / DATABASE_URL, so production silently fell back to the public
#     token secret "dev-only-change-me" and an in-memory SQLite database;
#   - /auth/login accepted the demo users admin/manager with password "change-me" in every
#     environment, and erpadmin was seeded with "change-me" when ERP_ADMIN_PASSWORD was unset.
# No live staging/production host was available this session; the rules below were verified with
# the unit tests in tests/test_v90gx_runtime_security.py against the FastAPI TestClient.
#
# THE FIX: new helpers used by auth.py, db.py, identity.py and __main__.py:
#   - erp_environment(): APP_ENV (fallback ERP_ENV), default "development".
#   - is_strict_environment(): True for staging/production (and anything not a known dev/test name).
#   - read_secret(NAME): NAME, else the file named by NAME_FILE (Docker secrets).
#   - token_secret(): AUTH_TOKEN_SECRET / JWT_SECRET (or *_FILE). In strict environments a missing,
#     default or short (<32 chars) secret raises RuntimeConfigError.
#   - demo_login_enabled(): legacy admin/manager demo users only in development/test, and can be
#     switched off there too with DEMO_LOGIN_ENABLED=false.
#   - bootstrap_admin_password(): ERP_ADMIN_PASSWORD(_FILE); "change-me" is refused in strict envs.
#   - validate_runtime_configuration(): startup gate called from app/__main__.py.
# Development and the existing test suite keep their current behaviour (no env vars needed).
# NOT touched: password hashing, token format, session validation, RBAC, any business module.
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

DEV_ENVIRONMENTS = {"development", "dev", "local", "test", "testing", "ci"}
STRICT_ENVIRONMENTS = {"staging", "production", "prod", "uat"}
INSECURE_SECRETS = {"", "dev-only-change-me", "change-me", "changeme", "secret", "password"}
DEV_TOKEN_SECRET = "dev-only-change-me"
MIN_SECRET_LENGTH = 32


class RuntimeConfigError(RuntimeError):
    """Raised when a staging/production process is started with unsafe configuration."""


def _env(source: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return os.environ if source is None else source


def erp_environment(source: Mapping[str, str] | None = None) -> str:
    env = _env(source)
    return (env.get("APP_ENV") or env.get("ERP_ENV") or "development").strip().lower()


def is_strict_environment(source: Mapping[str, str] | None = None) -> bool:
    return erp_environment(source) not in DEV_ENVIRONMENTS


def read_secret(name: str, source: Mapping[str, str] | None = None) -> str | None:
    """Return NAME from the environment, else the content of the file named by NAME_FILE."""
    env = _env(source)
    value = env.get(name)
    if value:
        return value.strip()
    file_name = env.get(f"{name}_FILE")
    if file_name:
        path = Path(file_name)
        if not path.is_file():
            raise RuntimeConfigError(f"{name}_FILE points to a missing file: {file_name}")
        return path.read_text(encoding="utf-8").strip()
    return None


def token_secret(source: Mapping[str, str] | None = None) -> str:
    secret = read_secret("AUTH_TOKEN_SECRET", source) or read_secret("JWT_SECRET", source)
    if is_strict_environment(source):
        if not secret or secret.lower() in INSECURE_SECRETS:
            raise RuntimeConfigError("AUTH_TOKEN_SECRET / JWT_SECRET(_FILE) must be set to a private value in staging/production")
        if len(secret) < MIN_SECRET_LENGTH:
            raise RuntimeConfigError(f"token secret must be at least {MIN_SECRET_LENGTH} characters in staging/production")
        return secret
    return secret or DEV_TOKEN_SECRET


def demo_login_enabled(source: Mapping[str, str] | None = None) -> bool:
    env = _env(source)
    if is_strict_environment(env):
        return False
    return str(env.get("DEMO_LOGIN_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}


def bootstrap_admin_password(source: Mapping[str, str] | None = None) -> str | None:
    """Password for the seeded erpadmin user; None means 'do not seed' (strict env without a safe value)."""
    password = read_secret("ERP_ADMIN_PASSWORD", source)
    if is_strict_environment(source):
        if not password or password.lower() in INSECURE_SECRETS or len(password) < 10:
            return None
        return password
    return password or "change-me"


def database_url(source: Mapping[str, str] | None = None) -> str:
    url = read_secret("DATABASE_URL", source)
    if is_strict_environment(source):
        if not url:
            raise RuntimeConfigError("DATABASE_URL or DATABASE_URL_FILE is required in staging/production")
        if url.startswith("sqlite"):
            raise RuntimeConfigError("SQLite is not allowed in staging/production; use PostgreSQL")
        return url
    return url or "sqlite+pysqlite:///:memory:"


def validate_runtime_configuration(source: Mapping[str, str] | None = None) -> dict[str, object]:
    """Startup gate. Raises RuntimeConfigError in strict environments when a rule is broken."""
    env = _env(source)
    token_secret(env)
    database_url(env)
    return {
        "environment": erp_environment(env),
        "strict": is_strict_environment(env),
        "demo_login_enabled": demo_login_enabled(env),
        "admin_seed_enabled": bootstrap_admin_password(env) is not None,
    }
