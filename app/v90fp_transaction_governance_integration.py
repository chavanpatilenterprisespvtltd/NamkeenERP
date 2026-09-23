from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope

PERMISSION_VIEW = 'governance.integration.view'
PERMISSION_MANAGE = 'governance.integration.manage'

DEFAULT_POLICIES = [
    ('PROCUREMENT', 'PROCUREMENT.WRITE', '/v90l/procurement', 'POST'),
    ('RECEIVING_QC', 'RECEIVING_QC.WRITE', '/v90m/inventory', 'POST'),
    ('INVENTORY', 'INVENTORY.WRITE', '/v90n/inventory', 'POST'),
    ('PRODUCTION', 'PRODUCTION.WRITE', '/v90o/production-planning', 'POST'),
    ('PROCESS_QC', 'PROCESS_QC.WRITE', '/v90t', 'POST'),
    ('BATCH_PACKING', 'BATCH_PACKING.WRITE', '/v90u', 'POST'),
    ('FG_DISPATCH', 'FG_DISPATCH.WRITE', '/v90y', 'POST'),
    ('SALES', 'SALES.WRITE', '/v90z/sales', 'POST'),
    ('RETURNS', 'RETURNS.WRITE', '/v90ah', 'POST'),
    ('RETURN_DISPOSITION', 'RETURN_DISPOSITION.WRITE', '/v90ai', 'POST'),
    ('ACCOUNTING', 'ACCOUNTING.WRITE', '/v90ca/accounting', 'POST'),
    ('INTERCOMPANY', 'INTERCOMPANY.WRITE', '/v90fm/intercompany', 'POST'),
]


class IntegrationPolicyIn(BaseModel):
    organization_id: str | None = None
    module_name: str = Field(min_length=1, max_length=64)
    action_code: str = Field(min_length=1, max_length=128)
    route_prefix: str = Field(min_length=1, max_length=255)
    http_method: str = Field(default='POST', min_length=1, max_length=10)
    enforcement: str = Field(default='AUDIT_ONLY', pattern='^(AUDIT_ONLY|REQUIRE_APPROVAL)$')
    active: bool = True


class RevokePolicyIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _user(e: Engine, request: Request, permission: str):
    u = authenticate(request)
    ps = permissions_for_user(e, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def ensure_v90fp_schema(e: Engine):
    stmts = [
        '''CREATE TABLE IF NOT EXISTS erp_governance_integration_policy(
            integration_id TEXT PRIMARY KEY,
            organization_id TEXT NULL,
            module_name TEXT NOT NULL,
            action_code TEXT NOT NULL,
            route_prefix TEXT NOT NULL,
            http_method TEXT NOT NULL DEFAULT 'POST',
            enforcement TEXT NOT NULL DEFAULT 'AUDIT_ONLY',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deactivated_by TEXT NULL,
            deactivated_at TIMESTAMP NULL,
            deactivation_reason TEXT NULL,
            UNIQUE(organization_id,module_name,action_code,route_prefix,http_method)
        )''',
        '''CREATE TABLE IF NOT EXISTS erp_governance_integration_event(
            event_id TEXT PRIMARY KEY,
            integration_id TEXT NOT NULL,
            organization_id TEXT NULL,
            entity_id TEXT NULL,
            actor_user_id TEXT NOT NULL,
            path TEXT NOT NULL,
            http_method TEXT NOT NULL,
            action_code TEXT NOT NULL,
            outcome TEXT NOT NULL,
            governed_action_id TEXT NULL,
            status_code INTEGER NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        'CREATE INDEX IF NOT EXISTS ix_governance_integration_policy_match ON erp_governance_integration_policy(active,http_method,route_prefix,organization_id)',
        'CREATE INDEX IF NOT EXISTS ix_governance_integration_event_scope ON erp_governance_integration_event(organization_id,actor_user_id,created_at)',
        'CREATE INDEX IF NOT EXISTS ix_governance_integration_event_action ON erp_governance_integration_event(action_code,path,created_at)',
    ]
    with e.begin() as c:
        for s in stmts:
            c.execute(text(s))
        perms = {
            PERMISSION_VIEW: 'View ERP transaction governance integration',
            PERMISSION_MANAGE: 'Manage ERP transaction governance integration',
        }
        for p, n in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p': p, 'n': n})
        for p in (PERMISSION_VIEW, PERMISSION_MANAGE):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'p': p})
        # Defaults are observational. They create coverage without changing legacy transaction behavior.
        existing = c.execute(text('SELECT COUNT(*) FROM erp_governance_integration_policy')).scalar_one()
        if existing == 0:
            for module_name, action_code, route_prefix, method in DEFAULT_POLICIES:
                c.execute(text('''INSERT INTO erp_governance_integration_policy
                    (integration_id,module_name,action_code,route_prefix,http_method,enforcement,active,created_by)
                    VALUES(:id,:m,:a,:rp,:hm,'AUDIT_ONLY',TRUE,'system')
                '''), {'id': str(uuid4()), 'm': module_name, 'a': action_code, 'rp': route_prefix, 'hm': method})


def _load_policy(e: Engine, method: str, path: str):
    with e.connect() as c:
        rows = c.execute(text('''SELECT * FROM erp_governance_integration_policy
            WHERE active=TRUE AND upper(http_method)=upper(:m)
              AND :path LIKE route_prefix || '%'
            ORDER BY length(route_prefix) DESC, organization_id NULLS LAST, created_at DESC'''), {'m': method, 'path': path}).mappings().all()
    return dict(rows[0]) if rows else None


def _gov_action(e: Engine, action_id: str):
    with e.connect() as c:
        return c.execute(text('SELECT * FROM erp_governed_action WHERE action_id=:id'), {'id': action_id}).mappings().first()


def _mark_executed(e: Engine, action_id: str, actor_user_id: str, status_code: int):
    with e.begin() as c:
        c.execute(text('''UPDATE erp_governed_action
            SET status='EXECUTED', executed_by=:u, executed_at=CURRENT_TIMESTAMP
            WHERE action_id=:id AND status='APPROVED' ''') , {'id': action_id, 'u': actor_user_id})
        c.execute(text('''INSERT INTO erp_governance_integration_event(
            event_id,integration_id,organization_id,entity_id,actor_user_id,path,http_method,action_code,outcome,governed_action_id,status_code,details_json)
            VALUES(:id,:pid,:o,:e,:u,:path,:hm,:a,'EXECUTED',:ga,:sc,:d)'''), {
                'id': str(uuid4()), 'pid': getattr(_mark_executed, '_policy_id', None), 'o': getattr(_mark_executed, '_org', None),
                'e': getattr(_mark_executed, '_entity', None), 'u': actor_user_id, 'path': getattr(_mark_executed, '_path', ''),
                'hm': getattr(_mark_executed, '_method', 'POST'), 'a': getattr(_mark_executed, '_action', ''), 'ga': action_id,
                'sc': status_code, 'd': json.dumps({'integration':'v90fp'})
            })


class GovernanceMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, engine: Engine):
        super().__init__(app)
        self.engine = engine

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() not in {'POST', 'PUT', 'PATCH', 'DELETE'} or request.url.path.startswith('/ui/') or request.url.path.startswith('/docs') or request.url.path.startswith('/openapi'):
            return await call_next(request)
        try:
            policy = _load_policy(self.engine, request.method, request.url.path)
            if not policy:
                return await call_next(request)
            actor = authenticate(request)
            governed_action_id = request.headers.get('X-Governed-Action-Id')
            action = _gov_action(self.engine, governed_action_id) if governed_action_id else None
            if policy['enforcement'] == 'REQUIRE_APPROVAL':
                if not action:
                    raise HTTPException(409, 'approved governed action is required; supply X-Governed-Action-Id')
                if action['status'] != 'APPROVED':
                    raise HTTPException(409, f'governed action status is {action["status"]}')
                if str(action['action_code']) != str(policy['action_code']):
                    raise HTTPException(409, 'governed action code does not match integration policy')
                if str(action['module_name']) != str(policy['module_name']):
                    raise HTTPException(409, 'governed action module does not match integration policy')
                try:
                    assert_security_scope(self.engine, actor.user_id, organization_id=str(action['organization_id']), entity_id=str(action['entity_id']) if action['entity_id'] else None)
                except PermissionError as exc:
                    raise HTTPException(403, str(exc)) from exc
                if action['evidence_required'] and not action['evidence_complete']:
                    raise HTTPException(409, 'required evidence is incomplete')
            response = await call_next(request)
            with self.engine.begin() as c:
                c.execute(text('''INSERT INTO erp_governance_integration_event(
                    event_id,integration_id,organization_id,entity_id,actor_user_id,path,http_method,action_code,outcome,governed_action_id,status_code,details_json)
                    VALUES(:id,:pid,:o,:e,:u,:path,:hm,:a,:out,:ga,:sc,:d)'''), {
                    'id': str(uuid4()), 'pid': policy['integration_id'], 'o': action['organization_id'] if action else None,
                    'e': action['entity_id'] if action else None, 'u': actor.user_id, 'path': request.url.path,
                    'hm': request.method.upper(), 'a': policy['action_code'],
                    'out': 'SUCCESS' if response.status_code < 400 else 'HTTP_ERROR', 'ga': governed_action_id,
                    'sc': response.status_code, 'd': json.dumps({'enforcement': policy['enforcement']})
                })
                if policy['enforcement'] == 'REQUIRE_APPROVAL' and response.status_code < 400 and governed_action_id:
                    c.execute(text('''UPDATE erp_governed_action SET status='EXECUTED',executed_by=:u,executed_at=CURRENT_TIMESTAMP
                                      WHERE action_id=:id AND status='APPROVED' '''), {'id': governed_action_id, 'u': actor.user_id})
            return response
        except HTTPException as exc:
            try:
                actor = authenticate(request)
                with self.engine.begin() as c:
                    if policy:
                        c.execute(text('''INSERT INTO erp_governance_integration_event(
                            event_id,integration_id,actor_user_id,path,http_method,action_code,outcome,status_code,details_json)
                            VALUES(:id,:pid,:u,:path,:hm,:a,'BLOCKED',:sc,:d)'''), {
                            'id': str(uuid4()), 'pid': policy['integration_id'], 'u': actor.user_id, 'path': request.url.path,
                            'hm': request.method.upper(), 'a': policy['action_code'], 'sc': exc.status_code, 'd': json.dumps({'detail': exc.detail})
                        })
            except Exception:
                pass
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})
        except Exception:
            return await call_next(request)


def register_v90fp_routes(app: FastAPI, e: Engine) -> None:
    ensure_v90fp_schema(e)
    app.add_middleware(GovernanceMiddleware, engine=e)

    @app.post('/v90fp/governance/integrations')
    def create_policy(body: IntegrationPolicyIn, request: Request):
        u = _user(e, request, PERMISSION_MANAGE)
        if body.organization_id:
            try:
                assert_security_scope(e, u.user_id, organization_id=body.organization_id)
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
        pid = str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO erp_governance_integration_policy(
                integration_id,organization_id,module_name,action_code,route_prefix,http_method,enforcement,active,created_by)
                VALUES(:id,:o,:m,:a,:rp,:hm,:en,:ac,:u)'''), {
                'id': pid, 'o': body.organization_id, 'm': body.module_name.upper(), 'a': body.action_code.upper(),
                'rp': body.route_prefix, 'hm': body.http_method.upper(), 'en': body.enforcement, 'ac': body.active, 'u': u.user_id
            })
        return {'integration_id': pid, 'status': 'ACTIVE' if body.active else 'INACTIVE'}

    @app.get('/v90fp/governance/integrations')
    def list_policies(request: Request, organization_id: str | None = None):
        _user(e, request, PERMISSION_VIEW)
        q = 'SELECT * FROM erp_governance_integration_policy WHERE 1=1'; p = {}
        if organization_id:
            q += ' AND (organization_id=:o OR organization_id IS NULL)'; p['o'] = organization_id
        with e.connect() as c:
            rows = [dict(r) for r in c.execute(text(q + ' ORDER BY length(route_prefix) DESC, created_at DESC'), p).mappings().all()]
        return {'integrations': rows}

    @app.post('/v90fp/governance/integrations/{integration_id}/deactivate')
    def deactivate(integration_id: str, body: RevokePolicyIn, request: Request):
        u = _user(e, request, PERMISSION_MANAGE)
        with e.begin() as c:
            row = c.execute(text('SELECT * FROM erp_governance_integration_policy WHERE integration_id=:id'), {'id': integration_id}).mappings().first()
            if not row: raise HTTPException(404, 'integration policy not found')
            c.execute(text('''UPDATE erp_governance_integration_policy SET active=FALSE,deactivated_by=:u,deactivated_at=CURRENT_TIMESTAMP,deactivation_reason=:r WHERE integration_id=:id'''), {'id': integration_id, 'u': u.user_id, 'r': body.reason})
        return {'integration_id': integration_id, 'status': 'INACTIVE'}

    @app.get('/v90fp/governance/events')
    def events(request: Request, organization_id: str | None = None, module_name: str | None = None, outcome: str | None = None, limit: int = 500):
        _user(e, request, PERMISSION_VIEW); limit = max(1, min(limit, 1000))
        q = 'SELECT * FROM erp_governance_integration_event WHERE 1=1'; p = {}
        if organization_id: q += ' AND organization_id=:o'; p['o'] = organization_id
        if module_name: q += ' AND action_code LIKE :m'; p['m'] = module_name.upper() + '.%'
        if outcome: q += ' AND outcome=:out'; p['out'] = outcome.upper()
        q += ' ORDER BY created_at DESC LIMIT :lim'; p['lim'] = limit
        with e.connect() as c: rows = [dict(r) for r in c.execute(text(q), p).mappings().all()]
        return {'events': rows}

    @app.get('/v90fp/governance/coverage')
    def coverage(request: Request):
        _user(e, request, PERMISSION_VIEW)
        with e.connect() as c:
            rows = c.execute(text('''SELECT module_name,COUNT(*) AS policy_count,
                SUM(CASE WHEN enforcement='REQUIRE_APPROVAL' AND active THEN 1 ELSE 0 END) AS enforced_policy_count,
                SUM(CASE WHEN active THEN 1 ELSE 0 END) AS active_policy_count
                FROM erp_governance_integration_policy GROUP BY module_name ORDER BY module_name''')).mappings().all()
            ev = c.execute(text('''SELECT COUNT(*) AS total_events,
                SUM(CASE WHEN outcome='BLOCKED' THEN 1 ELSE 0 END) AS blocked_events,
                SUM(CASE WHEN outcome='SUCCESS' THEN 1 ELSE 0 END) AS successful_events
                FROM erp_governance_integration_event''')).mappings().first()
        return {'modules': [dict(r) for r in rows], 'events': dict(ev)}

    @app.get('/ui/governance-integration')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'governance_integration.html')
