# FILE PATH: app/db.py
# ─── Database Configuration v1.1 (Session CS2 — DATABASE_URL_FILE support; no SQLite fallback in production) ─
#
# [Session CS2] FIX — DOCKER PRODUCTION WOULD RUN ON AN IN-MEMORY SQLITE DATABASE AND LOSE ALL DATA ON RESTART.
# Confirmed this session by reading the code: load_database_config() used
# source.get("DATABASE_URL", "sqlite+pysqlite:///:memory:"); the production compose/env templates
# provide only DATABASE_URL_FILE=/run/secrets/database_url, which was never read.
#
# ROOT CAUSE: secret-file convention added in V90.bh deployment templates, not in the V90.b db layer.
#
# THE FIX: load_database_config() now resolves the URL through runtime_security.database_url(),
# which reads DATABASE_URL or the file named by DATABASE_URL_FILE and raises RuntimeConfigError in
# staging/production when the URL is missing or points to SQLite. When an explicit `env` mapping is
# passed (as the existing tests do) that mapping is used instead of os.environ.
# NOT touched: postgres:// → postgresql+psycopg:// rewrite, pool settings, create_db_engine(), database_ping().
# Verified by tests/test_v90gx_runtime_security.py and the existing db tests.
#
# ─── v1.0 HEADER (preserved) ─────────────────────────────────────────────
# Original V90.b core runtime database layer; no in-file changelog existed before Session CS2.
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import Engine

from .runtime_security import database_url


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    pool_size: int = 5
    max_overflow: int = 5
    pool_pre_ping: bool = True


def load_database_config(env: Optional[dict[str, str]] = None) -> DatabaseConfig:
    source = env or os.environ
    url = database_url(source)  # [Session CS2] FIX — see file header (DATABASE_URL_FILE; no SQLite in production).
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return DatabaseConfig(
        url=url,
        pool_size=int(source.get("DB_POOL_SIZE", "5")),
        max_overflow=int(source.get("DB_MAX_OVERFLOW", "5")),
        pool_pre_ping=source.get("DB_POOL_PRE_PING", "true").lower() not in {"0", "false", "no"},
    )


def create_db_engine(config: DatabaseConfig | None = None) -> Engine:
    cfg = config or load_database_config()
    kwargs = {"pool_pre_ping": cfg.pool_pre_ping}
    if cfg.url.startswith("sqlite"):
        kwargs.update({"connect_args": {"check_same_thread": False}})
        if cfg.url in {"sqlite+pysqlite:///:memory:", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update({"pool_size": cfg.pool_size, "max_overflow": cfg.max_overflow})
    return create_engine(cfg.url, **kwargs)


def database_ping(engine: Engine) -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # pragma: no cover - error path is tested via fake engine
        return False, type(exc).__name__
