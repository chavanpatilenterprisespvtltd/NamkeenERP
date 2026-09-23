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
            ok = conn.execute(text("SELECT 1 FROM erp_entity_user_access WHERE user_id=:u AND entity_id=:e AND active=1"), {'u': user_id, 'e': entity_id}).first() is not None
        if not ok:
            raise PermissionError('entity access denied')
    if location_id:
        with engine.connect() as conn:
            ok = conn.execute(text("SELECT 1 FROM erp_location_user_access WHERE user_id=:u AND location_id=:l AND active=1"), {'u': user_id, 'l': location_id}).first() is not None
        if not ok:
            raise PermissionError('location access denied')
