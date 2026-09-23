from __future__ import annotations

from typing import Any
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .auth import authenticate, UserRecord, set_session_validator, parse_access_token
from .identity import permissions_for_user, roles_for_user
from .access_scope import accessible_scope, grant_entity_access, grant_location_access, grant_warehouse_access

PERMISSIONS = (
    'security.rbac.view', 'security.rbac.manage',
    'security.scope.view', 'security.scope.manage',
)


def _require(e: Engine, r: Request, permission: str) -> UserRecord:
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _entity_org(e: Engine, entity_id: str) -> str | None:
    with e.connect() as c:
        row = c.execute(text('SELECT organization_id FROM erp_security_entity_organization WHERE entity_id=:e'), {'e': entity_id}).first()
    return str(row[0]) if row else None


def _location_entity(e: Engine, location_id: str) -> tuple[str, str] | None:
    with e.connect() as c:
        row = c.execute(text('SELECT entity_id FROM erp_locations WHERE location_id=:l'), {'l': location_id}).first()
    if not row:
        return None
    ent = str(row[0])
    org = _entity_org(e, ent)
    return (org, ent) if org else None


def _warehouse_scope(e: Engine, warehouse_id: str):
    with e.connect() as c:
        row = c.execute(text('SELECT entity_id,location_id FROM erp_warehouses WHERE warehouse_id=:w'), {'w': warehouse_id}).first()
    if not row:
        return None
    org = _entity_org(e, str(row[0]))
    return (org, str(row[0]), str(row[1])) if org else None


def _ensure_org_access(e: Engine, user_id: str, organization_id: str) -> bool:
    with e.connect() as c:
        if c.execute(text('SELECT 1 FROM erp_organization_user_access WHERE user_id=:u AND organization_id=:o AND active=1'), {'u':user_id,'o':organization_id}).first():
            return True
        # Super-admins retain explicit global administrative access for bootstrap/operations.
        perms = {r[0] for r in c.execute(text('SELECT rp.permission_id FROM erp_user_roles ur JOIN erp_role_permissions rp ON rp.role_id=ur.role_id WHERE ur.user_id=:u'), {'u':user_id}).all()}
        return 'security.rbac.manage' in perms or 'admin.users' in perms


def assert_security_scope(e: Engine, user_id: str, organization_id: str | None = None, entity_id: str | None = None, location_id: str | None = None, warehouse_id: str | None = None) -> None:
    if organization_id and not _ensure_org_access(e, user_id, organization_id):
        raise PermissionError('organization access denied')
    if entity_id:
        org = _entity_org(e, entity_id)
        if not org: raise PermissionError('entity not found')
        if organization_id and org != organization_id: raise PermissionError('entity is outside organization scope')
        with e.connect() as c:
            ok = c.execute(text('SELECT 1 FROM erp_entity_user_access WHERE user_id=:u AND entity_id=:e AND active=1'), {'u':user_id,'e':entity_id}).first()
        if not ok and not _ensure_org_access(e, user_id, org): raise PermissionError('entity access denied')
    if location_id:
        pair = _location_entity(e, location_id)
        if not pair: raise PermissionError('location not found')
        org, ent = pair
        if organization_id and org != organization_id: raise PermissionError('location is outside organization scope')
        if entity_id and ent != entity_id: raise PermissionError('location is outside entity scope')
        with e.connect() as c:
            ok = c.execute(text('SELECT 1 FROM erp_location_user_access WHERE user_id=:u AND location_id=:l AND active=1'), {'u':user_id,'l':location_id}).first()
        if not ok and not _ensure_org_access(e,user_id,org):
            raise PermissionError('location access denied')
    if warehouse_id:
        scope = _warehouse_scope(e, warehouse_id)
        if not scope: raise PermissionError('warehouse not found')
        org, ent, loc = scope
        if organization_id and org != organization_id: raise PermissionError('warehouse is outside organization scope')
        if entity_id and ent != entity_id: raise PermissionError('warehouse is outside entity scope')
        if location_id and loc != location_id: raise PermissionError('warehouse is outside location scope')
        with e.connect() as c:
            ok = c.execute(text('SELECT 1 FROM erp_warehouse_user_access WHERE user_id=:u AND warehouse_id=:w AND active=1'), {'u':user_id,'w':warehouse_id}).first()
        if not ok and not _ensure_org_access(e,user_id,org):
            raise PermissionError('warehouse access denied')


def _audit_scope(e: Engine, actor: str, target: str, scope_type: str, scope_id: str, action: str, reason: str | None):
    with e.begin() as c:
        c.execute(text('INSERT INTO erp_security_scope_audit(audit_id,user_id,actor_user_id,scope_type,scope_id,action,reason) VALUES(:id,:u,:a,:t,:s,:ac,:r)'), {'id':str(uuid4()),'u':target,'a':actor,'t':scope_type,'s':scope_id,'ac':action,'r':reason})


def _tighten_session_validation(e: Engine):
    def _validator(token: str) -> bool:
        import hashlib
        try:
            parsed = parse_access_token(token)
        except Exception:
            return False
        digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
        with e.connect() as c:
            user = c.execute(text('SELECT active FROM erp_users WHERE user_id=:u'), {'u':parsed.user_id}).first()
            row = c.execute(text('SELECT ss.user_id,ss.revoked_at,ss.expires_at FROM security_sessions ss WHERE ss.token_digest=:d'), {'d':digest}).mappings().first()
        if not user or not user[0]:
            # The legacy demo users are intentionally stateless and are retained for backward-compatible test/bootstrap flows.
            from .auth import default_demo_users
            demo = default_demo_users().get(parsed.username)
            if not demo or demo[0].user_id != parsed.user_id or demo[0].role != parsed.role:
                return False
        if not row:
            return True
        if str(row['user_id']) != str(parsed.user_id) or row['revoked_at']:
            return False
        try:
            from datetime import datetime, timezone
            expiry = datetime.fromisoformat(str(row['expires_at']).replace('Z', '+00:00'))
            return expiry > datetime.now(timezone.utc)
        except ValueError:
            return False
    set_session_validator(_validator)


def ensure_v90fn_schema(e: Engine):
    with e.begin() as c:
        if e.dialect.name == 'sqlite':
            c.execute(text('CREATE TABLE IF NOT EXISTS erp_organization_user_access (user_id TEXT NOT NULL, organization_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, granted_by TEXT, granted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, revoked_by TEXT, revoked_at TEXT, PRIMARY KEY(user_id,organization_id))'))
            c.execute(text('CREATE TABLE IF NOT EXISTS erp_security_entity_organization (entity_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, mapped_by TEXT, mapped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id))'))
            c.execute(text('CREATE TABLE IF NOT EXISTS erp_security_scope_audit (audit_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,actor_user_id TEXT NOT NULL,scope_type TEXT NOT NULL,scope_id TEXT NOT NULL,action TEXT NOT NULL,reason TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'))
        else:
            c.execute(text('CREATE TABLE IF NOT EXISTS erp_organization_user_access (user_id VARCHAR(64) NOT NULL REFERENCES erp_users(user_id), organization_id VARCHAR(64) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, granted_by VARCHAR(64), granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, revoked_by VARCHAR(64), revoked_at TIMESTAMPTZ, PRIMARY KEY(user_id,organization_id))'))
            c.execute(text('CREATE TABLE IF NOT EXISTS erp_security_entity_organization (entity_id VARCHAR(64) PRIMARY KEY, organization_id VARCHAR(64) NOT NULL, mapped_by VARCHAR(64), mapped_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id))'))
            c.execute(text('CREATE TABLE IF NOT EXISTS erp_security_scope_audit (audit_id VARCHAR(64) PRIMARY KEY,user_id VARCHAR(64) NOT NULL,actor_user_id VARCHAR(64) NOT NULL,scope_type VARCHAR(32) NOT NULL,scope_id VARCHAR(64) NOT NULL,action VARCHAR(32) NOT NULL,reason TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_erp_org_user_access ON erp_organization_user_access(organization_id,user_id,active)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_security_entity_org ON erp_security_entity_organization(organization_id,entity_id)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_security_scope_audit ON erp_security_scope_audit(user_id,scope_type,created_at)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_erp_users_active ON erp_users(active,username)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_erp_user_roles_role ON erp_user_roles(role_id,user_id)'))
        # Keep compatibility with deployments whose locations do not carry organization_id directly.
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('security.rbac.view','View RBAC and security scope') ON CONFLICT(permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('security.rbac.manage','Manage RBAC and security scope') ON CONFLICT(permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('security.scope.view','View organization/entity/location/warehouse access') ON CONFLICT(permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('security.scope.manage','Grant or revoke organization/entity/location/warehouse access') ON CONFLICT(permission_id) DO NOTHING"))
    _tighten_session_validation(e)


def register_v90fn_routes(app: FastAPI, e: Engine):
    ensure_v90fn_schema(e)

    @app.get('/v90fn/security/context')
    def context(request: Request):
        u = authenticate(request)
        scope = accessible_scope(e, u.user_id)
        with e.connect() as c:
            orgs = [str(r[0]) for r in c.execute(text('SELECT organization_id FROM erp_organization_user_access WHERE user_id=:u AND active=1 ORDER BY organization_id'), {'u':u.user_id}).all()]
        return {'user_id':u.user_id,'roles':roles_for_user(e,u.user_id),'permissions':sorted(permissions_for_user(e,u.user_id)),'organizations':orgs,**scope}

    @app.post('/v90fn/security/entity/{entity_id}/organization/{organization_id}')
    def map_entity_org(entity_id:str, organization_id:str, request:Request, reason:str|None=None):
        actor=_require(e,request,'security.scope.manage')
        with e.begin() as c:
            if not c.execute(text('SELECT 1 FROM erp_entities WHERE entity_id=:e'),{'e':entity_id}).first(): raise HTTPException(404,'entity not found')
            c.execute(text('INSERT INTO erp_security_entity_organization(entity_id,organization_id,mapped_by,mapped_at) VALUES(:e,:o,:u,CURRENT_TIMESTAMP) ON CONFLICT(entity_id) DO UPDATE SET organization_id=:o,mapped_by=:u,mapped_at=CURRENT_TIMESTAMP'),{'e':entity_id,'o':organization_id,'u':actor.user_id})
        _audit_scope(e,actor.user_id,actor.user_id,'entity_organization',entity_id,'MAP',reason or organization_id)
        return {'status':'mapped','entity_id':entity_id,'organization_id':organization_id}

    @app.delete('/v90fn/security/entity/{entity_id}/organization')
    def unmap_entity_org(entity_id:str, request:Request, reason:str|None=None):
        actor=_require(e,request,'security.scope.manage')
        with e.begin() as c:
            r=c.execute(text('DELETE FROM erp_security_entity_organization WHERE entity_id=:e'),{'e':entity_id})
            if r.rowcount!=1: raise HTTPException(404,'entity organization mapping not found')
        _audit_scope(e,actor.user_id,actor.user_id,'entity_organization',entity_id,'UNMAP',reason)
        return {'status':'unmapped','entity_id':entity_id}

    @app.get('/v90fn/security/entities')
    def entity_security_map(request:Request):
        _require(e,request,'security.scope.view')
        with e.connect() as c:
            rows=[dict(x) for x in c.execute(text('SELECT * FROM erp_security_entity_organization ORDER BY organization_id,entity_id')).mappings().all()]
        return {'entities':rows}

    @app.get('/v90fn/security/users/{user_id}/scope')
    def user_scope(user_id: str, request: Request):
        _require(e, request, 'security.scope.view')
        with e.connect() as c:
            orgs=[dict(x) for x in c.execute(text('SELECT organization_id,active,granted_by,granted_at,revoked_by,revoked_at FROM erp_organization_user_access WHERE user_id=:u ORDER BY organization_id'),{'u':user_id}).mappings().all()]
        return {'user_id':user_id,'organizations':orgs,'scope':accessible_scope(e,user_id)}

    @app.post('/v90fn/security/users/{user_id}/organization/{organization_id}')
    def grant_org(user_id:str, organization_id:str, request:Request, reason:str|None=None):
        actor=_require(e,request,'security.scope.manage')
        with e.begin() as c:
            if not c.execute(text('SELECT 1 FROM erp_users WHERE user_id=:u'),{'u':user_id}).first(): raise HTTPException(404,'user not found')
            c.execute(text('INSERT INTO erp_organization_user_access(user_id,organization_id,active,granted_by,granted_at,revoked_by,revoked_at) VALUES(:u,:o,1,:a,CURRENT_TIMESTAMP,NULL,NULL) ON CONFLICT(user_id,organization_id) DO UPDATE SET active=1,granted_by=:a,granted_at=CURRENT_TIMESTAMP,revoked_by=NULL,revoked_at=NULL'),{'u':user_id,'o':organization_id,'a':actor.user_id})
        _audit_scope(e,actor.user_id,user_id,'organization',organization_id,'GRANT',reason)
        return {'status':'granted','scope':'organization','organization_id':organization_id}

    @app.delete('/v90fn/security/users/{user_id}/organization/{organization_id}')
    def revoke_org(user_id:str, organization_id:str, request:Request, reason:str|None=None):
        actor=_require(e,request,'security.scope.manage')
        with e.begin() as c:
            r=c.execute(text('UPDATE erp_organization_user_access SET active=0,revoked_by=:a,revoked_at=CURRENT_TIMESTAMP WHERE user_id=:u AND organization_id=:o AND active=1'),{'u':user_id,'o':organization_id,'a':actor.user_id})
            if r.rowcount!=1: raise HTTPException(404,'organization access not found')
        _audit_scope(e,actor.user_id,user_id,'organization',organization_id,'REVOKE',reason)
        return {'status':'revoked','scope':'organization','organization_id':organization_id}

    @app.post('/v90fn/security/users/{user_id}/scope/{scope_type}/{scope_id}')
    def grant_scope(user_id:str,scope_type:str,scope_id:str,request:Request,reason:str|None=None):
        actor=_require(e,request,'security.scope.manage')
        funcs={'entity':grant_entity_access,'location':grant_location_access,'warehouse':grant_warehouse_access}
        fn=funcs.get(scope_type)
        if not fn: raise HTTPException(400,'unsupported scope type')
        try:
            # Validate that the target scope resolves to the actor's own organization(s) unless actor is RBAC super-admin.
            if scope_type=='entity': assert_security_scope(e,actor.user_id,entity_id=scope_id)
            elif scope_type=='location': assert_security_scope(e,actor.user_id,location_id=scope_id)
            else: assert_security_scope(e,actor.user_id,warehouse_id=scope_id)
        except PermissionError as exc:
            raise HTTPException(403,str(exc)) from exc
        fn(e,user_id,scope_id)
        _audit_scope(e,actor.user_id,user_id,scope_type,scope_id,'GRANT',reason)
        return {'status':'granted','scope':scope_type,'scope_id':scope_id}

    @app.delete('/v90fn/security/users/{user_id}/scope/{scope_type}/{scope_id}')
    def revoke_scope(user_id:str,scope_type:str,scope_id:str,request:Request,reason:str|None=None):
        actor=_require(e,request,'security.scope.manage')
        table={'entity':'erp_entity_user_access','location':'erp_location_user_access','warehouse':'erp_warehouse_user_access'}.get(scope_type)
        col={'entity':'entity_id','location':'location_id','warehouse':'warehouse_id'}.get(scope_type)
        if not table: raise HTTPException(400,'unsupported scope type')
        with e.begin() as c:
            r=c.execute(text(f'UPDATE {table} SET active=0 WHERE user_id=:u AND {col}=:s AND active=1'),{'u':user_id,'s':scope_id})
            if r.rowcount!=1: raise HTTPException(404,'scope access not found')
        _audit_scope(e,actor.user_id,user_id,scope_type,scope_id,'REVOKE',reason)
        return {'status':'revoked','scope':scope_type,'scope_id':scope_id}

    @app.get('/v90fn/security/scope-audit')
    def scope_audit(request:Request,user_id:str|None=None,scope_type:str|None=None):
        _require(e,request,'security.scope.view')
        sql='SELECT * FROM erp_security_scope_audit WHERE 1=1'; par={}
        if user_id: sql+=' AND user_id=:u';par['u']=user_id
        if scope_type: sql+=' AND scope_type=:t';par['t']=scope_type
        sql+=' ORDER BY created_at DESC LIMIT 500'
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(sql),par).mappings().all()]
        return {'events':rows}

    @app.get('/ui/security-rbac')
    def ui():
        return FileResponse(Path(__file__).resolve().parents[1]/'web'/'security_rbac.html')
