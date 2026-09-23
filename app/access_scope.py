from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_access_scope_schema(engine: Engine) -> None:
    if engine.dialect.name == 'sqlite':
        stmts = [
            "CREATE TABLE IF NOT EXISTS erp_entity_user_access (user_id TEXT NOT NULL, entity_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id, entity_id), FOREIGN KEY(user_id) REFERENCES erp_users(user_id), FOREIGN KEY(entity_id) REFERENCES erp_entities(entity_id))",
            "CREATE TABLE IF NOT EXISTS erp_location_user_access (user_id TEXT NOT NULL, location_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id, location_id), FOREIGN KEY(user_id) REFERENCES erp_users(user_id), FOREIGN KEY(location_id) REFERENCES erp_locations(location_id))",
            "CREATE TABLE IF NOT EXISTS erp_warehouses (warehouse_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, location_id TEXT NOT NULL, warehouse_code TEXT NOT NULL, warehouse_name TEXT NOT NULL, warehouse_type TEXT NOT NULL DEFAULT 'general', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(entity_id) REFERENCES erp_entities(entity_id), FOREIGN KEY(location_id) REFERENCES erp_locations(location_id), UNIQUE(entity_id, warehouse_code))",
            "CREATE TABLE IF NOT EXISTS erp_warehouse_user_access (user_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id, warehouse_id), FOREIGN KEY(user_id) REFERENCES erp_users(user_id), FOREIGN KEY(warehouse_id) REFERENCES erp_warehouses(warehouse_id))",
        ]
    else:
        stmts = [
            "CREATE TABLE IF NOT EXISTS erp_entity_user_access (user_id VARCHAR(64) NOT NULL REFERENCES erp_users(user_id), entity_id VARCHAR(64) NOT NULL REFERENCES erp_entities(entity_id), active BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY(user_id, entity_id))",
            "CREATE TABLE IF NOT EXISTS erp_location_user_access (user_id VARCHAR(64) NOT NULL REFERENCES erp_users(user_id), location_id VARCHAR(64) NOT NULL REFERENCES erp_locations(location_id), active BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY(user_id, location_id))",
            "CREATE TABLE IF NOT EXISTS erp_warehouses (warehouse_id VARCHAR(64) PRIMARY KEY, entity_id VARCHAR(64) NOT NULL REFERENCES erp_entities(entity_id), location_id VARCHAR(64) NOT NULL REFERENCES erp_locations(location_id), warehouse_code VARCHAR(64) NOT NULL, warehouse_name VARCHAR(160) NOT NULL, warehouse_type VARCHAR(40) NOT NULL DEFAULT 'general', active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(entity_id, warehouse_code))",
            "CREATE TABLE IF NOT EXISTS erp_warehouse_user_access (user_id VARCHAR(64) NOT NULL REFERENCES erp_users(user_id), warehouse_id VARCHAR(64) NOT NULL REFERENCES erp_warehouses(warehouse_id), active BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY(user_id, warehouse_id))",
        ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def create_warehouse(engine: Engine, warehouse_id: str, entity_id: str, location_id: str, code: str, name: str, warehouse_type: str = 'general') -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_warehouses(warehouse_id,entity_id,location_id,warehouse_code,warehouse_name,warehouse_type) VALUES (:i,:e,:l,:c,:n,:t)"), {'i':warehouse_id,'e':entity_id,'l':location_id,'c':code,'n':name,'t':warehouse_type})


def grant_entity_access(engine: Engine, user_id: str, entity_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES (:u,:e) ON CONFLICT(user_id,entity_id) DO UPDATE SET active=1"), {'u':user_id,'e':entity_id})


def grant_location_access(engine: Engine, user_id: str, location_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES (:u,:l) ON CONFLICT(user_id,location_id) DO UPDATE SET active=1"), {'u':user_id,'l':location_id})


def grant_warehouse_access(engine: Engine, user_id: str, warehouse_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_warehouse_user_access(user_id,warehouse_id) VALUES (:u,:w) ON CONFLICT(user_id,warehouse_id) DO UPDATE SET active=1"), {'u':user_id,'w':warehouse_id})


def accessible_scope(engine: Engine, user_id: str) -> dict[str, list[str]]:
    with engine.connect() as conn:
        entities = [r['entity_id'] for r in conn.execute(text("SELECT entity_id FROM erp_entity_user_access WHERE user_id=:u AND active=1 ORDER BY entity_id"), {'u':user_id}).mappings()]
        locations = [r['location_id'] for r in conn.execute(text("SELECT location_id FROM erp_location_user_access WHERE user_id=:u AND active=1 ORDER BY location_id"), {'u':user_id}).mappings()]
        warehouses = [r['warehouse_id'] for r in conn.execute(text("SELECT warehouse_id FROM erp_warehouse_user_access WHERE user_id=:u AND active=1 ORDER BY warehouse_id"), {'u':user_id}).mappings()]
    return {'entities': entities, 'locations': locations, 'warehouses': warehouses}


def is_entity_allowed(engine: Engine, user_id: str, entity_id: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1 FROM erp_entity_user_access WHERE user_id=:u AND entity_id=:e AND active=1"), {'u':user_id,'e':entity_id}).first() is not None


def is_location_allowed(engine: Engine, user_id: str, location_id: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1 FROM erp_location_user_access WHERE user_id=:u AND location_id=:l AND active=1"), {'u':user_id,'l':location_id}).first() is not None


def is_warehouse_allowed(engine: Engine, user_id: str, warehouse_id: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1 FROM erp_warehouse_user_access WHERE user_id=:u AND warehouse_id=:w AND active=1"), {'u':user_id,'w':warehouse_id}).first() is not None
