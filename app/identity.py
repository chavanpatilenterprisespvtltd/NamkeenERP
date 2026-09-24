from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import hash_password, UserRecord

SCHEMA = {
    'sqlite': [
        "CREATE TABLE IF NOT EXISTS erp_users (user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, display_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS erp_roles (role_id TEXT PRIMARY KEY, role_name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS erp_permissions (permission_id TEXT PRIMARY KEY, permission_name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS erp_user_roles (user_id TEXT NOT NULL, role_id TEXT NOT NULL, PRIMARY KEY(user_id, role_id), FOREIGN KEY(user_id) REFERENCES erp_users(user_id), FOREIGN KEY(role_id) REFERENCES erp_roles(role_id))",
        "CREATE TABLE IF NOT EXISTS erp_role_permissions (role_id TEXT NOT NULL, permission_id TEXT NOT NULL, PRIMARY KEY(role_id, permission_id), FOREIGN KEY(role_id) REFERENCES erp_roles(role_id), FOREIGN KEY(permission_id) REFERENCES erp_permissions(permission_id))",
    ]
}

DEFAULT_ROLES = [('super_admin','Super Admin'),('manager','Manager'),('operator','Operator'),('salesperson','Salesperson'),('accounts','Accounts')]
DEFAULT_PERMISSIONS = [
    ('dashboard.view','View dashboard'),('masters.view','View masters'),('masters.edit','Edit masters'),
    ('production.view','View production'),('production.edit','Edit production'),('production.approve','Approve production'),('inventory.view','View inventory'),
    ('sales.view','View sales'),('sales.edit','Edit sales'),('sales.approve','Approve sales'),('procurement.view','View procurement'),('procurement.edit','Edit procurement'),('procurement.approve','Approve procurement'),('incentive_policy.view','View incentive policy'),('incentive_policy.edit','Edit incentive policy'),('inventory.edit','Edit inventory'),('qc.approve','Approve QC'),('qc.edit','Record QC'),('admin.users','Manage users'),('credit_policy.view','View credit policy'),('credit_policy.edit','Edit credit policy'),('payments.verify','Verify payments'),('dispatch.view','View dispatch'),('dispatch.edit','Edit dispatch'),('returns.view','View returns'),('returns.edit','Edit returns'),
]
DEFAULT_GRANTS = {
    'super_admin': [p[0] for p in DEFAULT_PERMISSIONS],
    'manager': ['dashboard.view','masters.view','masters.edit','production.view','production.edit','production.approve','inventory.view','inventory.edit','qc.edit','qc.approve','sales.view','sales.edit','sales.approve','incentive_policy.view','incentive_policy.edit','procurement.view','procurement.edit','procurement.approve','credit_policy.view','credit_policy.edit','payments.verify','dispatch.view','dispatch.edit','returns.view','returns.edit'],
    'operator': ['dashboard.view','production.view','production.edit','inventory.view','inventory.edit','qc.edit','procurement.view'],
    'salesperson': ['dashboard.view','sales.view','sales.edit','credit_policy.view','returns.view','returns.edit'],
}

def ensure_identity_schema(engine: Engine) -> None:
    dialect = engine.dialect.name
    if dialect == 'sqlite':
        with engine.begin() as conn:
            for stmt in SCHEMA['sqlite']:
                conn.execute(text(stmt))
    else:
        statements = [
            "CREATE TABLE IF NOT EXISTS erp_users (user_id VARCHAR(64) PRIMARY KEY, username VARCHAR(120) NOT NULL UNIQUE, password_hash TEXT NOT NULL, display_name VARCHAR(160) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS erp_roles (role_id VARCHAR(64) PRIMARY KEY, role_name VARCHAR(120) NOT NULL UNIQUE, active BOOLEAN NOT NULL DEFAULT TRUE)",
            "CREATE TABLE IF NOT EXISTS erp_permissions (permission_id VARCHAR(100) PRIMARY KEY, permission_name VARCHAR(160) NOT NULL UNIQUE, active BOOLEAN NOT NULL DEFAULT TRUE)",
            "CREATE TABLE IF NOT EXISTS erp_user_roles (user_id VARCHAR(64) NOT NULL REFERENCES erp_users(user_id), role_id VARCHAR(64) NOT NULL REFERENCES erp_roles(role_id), PRIMARY KEY(user_id, role_id))",
            "CREATE TABLE IF NOT EXISTS erp_role_permissions (role_id VARCHAR(64) NOT NULL REFERENCES erp_roles(role_id), permission_id VARCHAR(100) NOT NULL REFERENCES erp_permissions(permission_id), PRIMARY KEY(role_id, permission_id))",
        ]
        with engine.begin() as conn:
            for stmt in statements:
                conn.exec_driver_sql(stmt)
    seed_identity(engine)
    _seed_persistent_admins(engine)


def _seed_persistent_admins(engine: Engine) -> None:
    # Seed only when absent; passwords remain configurable through environment variables.
    existing = find_user(engine, 'erpadmin')
    if existing:
        return
    import os
    try:
        create_user(engine, 'erpadmin', 'erpadmin', os.getenv('ERP_ADMIN_PASSWORD', 'change-me'), 'ERP Administrator', 'super_admin')
    except Exception:
        pass

def seed_identity(engine: Engine) -> None:
    with engine.begin() as conn:
        for rid, name in DEFAULT_ROLES:
            conn.execute(text("INSERT INTO erp_roles(role_id, role_name) VALUES (:id,:name) ON CONFLICT(role_id) DO NOTHING"), {'id':rid,'name':name})
        for pid, name in DEFAULT_PERMISSIONS:
            conn.execute(text("INSERT INTO erp_permissions(permission_id, permission_name) VALUES (:id,:name) ON CONFLICT(permission_id) DO NOTHING"), {'id':pid,'name':name})
        for rid, perms in DEFAULT_GRANTS.items():
            for pid in perms:
                conn.execute(text("INSERT INTO erp_role_permissions(role_id, permission_id) VALUES (:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':rid,'p':pid})

def create_user(engine: Engine, user_id: str, username: str, password: str, display_name: str, role_id: str='operator') -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO erp_users(user_id,username,password_hash,display_name) VALUES (:id,:u,:h,:d)"), {'id':user_id,'u':username,'h':hash_password(password),'d':display_name})
        conn.execute(text("INSERT INTO erp_user_roles(user_id,role_id) VALUES (:u,:r)"), {'u':user_id,'r':role_id})

def find_user(engine: Engine, username: str):
    with engine.connect() as conn:
        row=conn.execute(text("SELECT user_id,username,password_hash,display_name,active FROM erp_users WHERE username=:u"), {'u':username}).mappings().first()
        return dict(row) if row else None

def roles_for_user(engine: Engine, user_id: str) -> list[str]:
    with engine.connect() as conn:
        return [r['role_id'] for r in conn.execute(text("SELECT role_id FROM erp_user_roles WHERE user_id=:u ORDER BY role_id"), {'u':user_id}).mappings()]

def permissions_for_user(engine: Engine, user_id: str) -> set[str]:
    with engine.connect() as conn:
        rows=conn.execute(text("SELECT DISTINCT rp.permission_id FROM erp_user_roles ur JOIN erp_role_permissions rp ON rp.role_id=ur.role_id WHERE ur.user_id=:u"), {'u':user_id}).mappings()
        return {r['permission_id'] for r in rows}

def user_record(engine: Engine, username: str, password: str):
    from .auth import verify_password
    u=find_user(engine,username)
    if not u or not u['active'] or not verify_password(password,u['password_hash']): return None
    roles=roles_for_user(engine,u['user_id'])
    role=roles[0] if roles else 'operator'
    return UserRecord(u['user_id'],u['username'],role,True)
