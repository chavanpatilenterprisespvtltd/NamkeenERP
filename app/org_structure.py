from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_org_schema(engine: Engine) -> None:
    if engine.dialect.name == 'sqlite':
        stmts = [
            "CREATE TABLE IF NOT EXISTS erp_entities (entity_id TEXT PRIMARY KEY, entity_code TEXT NOT NULL UNIQUE, entity_name TEXT NOT NULL, entity_type TEXT NOT NULL DEFAULT 'legal_entity', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS erp_locations (location_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, location_code TEXT NOT NULL, location_name TEXT NOT NULL, location_type TEXT NOT NULL DEFAULT 'site', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(entity_id) REFERENCES erp_entities(entity_id), UNIQUE(entity_id, location_code))",
            "CREATE TABLE IF NOT EXISTS erp_departments (department_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, department_code TEXT NOT NULL, department_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(entity_id) REFERENCES erp_entities(entity_id), UNIQUE(entity_id, department_code))",
            "CREATE TABLE IF NOT EXISTS erp_responsibilities (responsibility_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, department_id TEXT, responsibility_code TEXT NOT NULL, responsibility_name TEXT NOT NULL, module_name TEXT NOT NULL, primary_user_id TEXT, backup_user_id TEXT, approval_user_id TEXT, active INTEGER NOT NULL DEFAULT 1, effective_from TEXT, effective_to TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(entity_id) REFERENCES erp_entities(entity_id), FOREIGN KEY(department_id) REFERENCES erp_departments(department_id), UNIQUE(entity_id, responsibility_code))",
            "CREATE TABLE IF NOT EXISTS erp_user_org_assignments (user_id TEXT NOT NULL, entity_id TEXT NOT NULL, department_id TEXT, responsibility_id TEXT, is_primary INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id, entity_id, responsibility_id), FOREIGN KEY(user_id) REFERENCES erp_users(user_id), FOREIGN KEY(entity_id) REFERENCES erp_entities(entity_id), FOREIGN KEY(department_id) REFERENCES erp_departments(department_id), FOREIGN KEY(responsibility_id) REFERENCES erp_responsibilities(responsibility_id))",
        ]
    else:
        stmts = [
            "CREATE TABLE IF NOT EXISTS erp_entities (entity_id VARCHAR(64) PRIMARY KEY, entity_code VARCHAR(64) NOT NULL UNIQUE, entity_name VARCHAR(160) NOT NULL, entity_type VARCHAR(40) NOT NULL DEFAULT 'legal_entity', active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS erp_locations (location_id VARCHAR(64) PRIMARY KEY, entity_id VARCHAR(64) NOT NULL REFERENCES erp_entities(entity_id), location_code VARCHAR(64) NOT NULL, location_name VARCHAR(160) NOT NULL, location_type VARCHAR(40) NOT NULL DEFAULT 'site', active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(entity_id, location_code))",
            "CREATE TABLE IF NOT EXISTS erp_departments (department_id VARCHAR(64) PRIMARY KEY, entity_id VARCHAR(64) NOT NULL REFERENCES erp_entities(entity_id), department_code VARCHAR(64) NOT NULL, department_name VARCHAR(160) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(entity_id, department_code))",
            "CREATE TABLE IF NOT EXISTS erp_responsibilities (responsibility_id VARCHAR(64) PRIMARY KEY, entity_id VARCHAR(64) NOT NULL REFERENCES erp_entities(entity_id), department_id VARCHAR(64) REFERENCES erp_departments(department_id), responsibility_code VARCHAR(80) NOT NULL, responsibility_name VARCHAR(160) NOT NULL, module_name VARCHAR(100) NOT NULL, primary_user_id VARCHAR(64), backup_user_id VARCHAR(64), approval_user_id VARCHAR(64), active BOOLEAN NOT NULL DEFAULT TRUE, effective_from DATE, effective_to DATE, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(entity_id, responsibility_code))",
            "CREATE TABLE IF NOT EXISTS erp_user_org_assignments (user_id VARCHAR(64) NOT NULL REFERENCES erp_users(user_id), entity_id VARCHAR(64) NOT NULL REFERENCES erp_entities(entity_id), department_id VARCHAR(64) REFERENCES erp_departments(department_id), responsibility_id VARCHAR(64) REFERENCES erp_responsibilities(responsibility_id), is_primary BOOLEAN NOT NULL DEFAULT FALSE, active BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY(user_id, entity_id, responsibility_id))",
        ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def create_entity(engine: Engine, entity_id: str, code: str, name: str, entity_type: str = 'legal_entity') -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type) VALUES (:i,:c,:n,:t)"), {'i':entity_id,'c':code,'n':name,'t':entity_type})


def create_location(engine: Engine, location_id: str, entity_id: str, code: str, name: str, location_type: str = 'site') -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type) VALUES (:i,:e,:c,:n,:t)"), {'i':location_id,'e':entity_id,'c':code,'n':name,'t':location_type})


def create_department(engine: Engine, department_id: str, entity_id: str, code: str, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_departments(department_id,entity_id,department_code,department_name) VALUES (:i,:e,:c,:n)"), {'i':department_id,'e':entity_id,'c':code,'n':name})


def create_responsibility(engine: Engine, responsibility_id: str, entity_id: str, code: str, name: str, module_name: str, department_id: str | None = None, primary_user_id: str | None = None, backup_user_id: str | None = None, approval_user_id: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_responsibilities(responsibility_id,entity_id,department_id,responsibility_code,responsibility_name,module_name,primary_user_id,backup_user_id,approval_user_id) VALUES (:i,:e,:d,:c,:n,:m,:p,:b,:a)"), {'i':responsibility_id,'e':entity_id,'d':department_id,'c':code,'n':name,'m':module_name,'p':primary_user_id,'b':backup_user_id,'a':approval_user_id})


def assign_user(engine: Engine, user_id: str, entity_id: str, department_id: str | None, responsibility_id: str | None, primary: bool = False) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_user_org_assignments(user_id,entity_id,department_id,responsibility_id,is_primary) VALUES (:u,:e,:d,:r,:p)"), {'u':user_id,'e':entity_id,'d':department_id,'r':responsibility_id,'p':primary})
