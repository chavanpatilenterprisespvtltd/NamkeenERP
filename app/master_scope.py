# FILE PATH: app/master_scope.py
# ─── Master Scope v1.1 (Session CS2 — access flags compared/set as TRUE/FALSE so scope checks work on PostgreSQL) ─
#
# [Session CS2] FIX — ENTITY/LOCATION/ORGANIZATION SCOPE CHECKS FAILED ON POSTGRESQL.
# Confirmed live this session by running the full pytest suite against a fresh PostgreSQL 16 database:
# "operator does not exist: boolean = integer" (…AND active=1) and "column active is of type boolean
# but expression is of type integer" (…DO UPDATE SET active=1) from this file.
# ROOT CAUSE: on PostgreSQL the access tables are created with active BOOLEAN; the SQL used 1/0 literals,
# which only SQLite accepts.
# THE FIX: every active=1 / active=0 literal in this file (2 places) is now active=TRUE / active=FALSE.
# SQLite (3.23+) treats TRUE/FALSE as 1/0, so the SQLite behaviour and tests are unchanged.
# NOT touched: which tables/columns are queried, the scope rules themselves, DDL.
#
# ─── v1.0 HEADER (preserved) ─────────────────────────────────────────────
# Original V90.h master scope; no in-file changelog existed before Session CS2.
from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.engine import Engine

MASTER_TABLE = 'master_record'

def _table_exists(conn, table: str, dialect: str) -> bool:
    if dialect == 'sqlite':
        return conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t"), {'t': table}).first() is not None
    return conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name=:t"), {'t': table}).first() is not None

def ensure_master_scope_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        if not _table_exists(conn, MASTER_TABLE, engine.dialect.name):
            return
        if engine.dialect.name == 'sqlite':
            existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({MASTER_TABLE})"))}
            if 'location_id' not in existing:
                conn.execute(text(f"ALTER TABLE {MASTER_TABLE} ADD COLUMN location_id TEXT"))
        else:
            existing = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"), {'t': MASTER_TABLE})}
            if 'location_id' not in existing:
                conn.execute(text(f"ALTER TABLE {MASTER_TABLE} ADD COLUMN location_id VARCHAR(64)"))

def assert_entity_location_allowed(engine: Engine, user_id: str, entity_id: str | None = None, location_id: str | None = None) -> None:
    if entity_id:
        with engine.connect() as conn:
            ok = conn.execute(text("SELECT 1 FROM erp_entity_user_access WHERE user_id=:u AND entity_id=:e AND active=TRUE"), {'u': user_id, 'e': entity_id}).first() is not None
        if not ok:
            raise PermissionError('entity access denied')
    if location_id:
        with engine.connect() as conn:
            ok = conn.execute(text("SELECT 1 FROM erp_location_user_access WHERE user_id=:u AND location_id=:l AND active=TRUE"), {'u': user_id, 'l': location_id}).first() is not None
        if not ok:
            raise PermissionError('location access denied')
