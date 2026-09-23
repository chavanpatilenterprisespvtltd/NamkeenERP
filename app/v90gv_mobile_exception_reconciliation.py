from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now():
    return datetime.now(timezone.utc).isoformat()


def _user(engine, request, entity_id, location_id, permission='mobile.exception.view'):
    u = authenticate(request)
    if permission not in permissions_for_user(engine, u.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, u.user_id, str(entity_id), str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return u


def ensure_v90gv_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS mobile_transaction_exceptions (
            exception_id TEXT PRIMARY KEY,
            integration_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NULL,
            transaction_type TEXT NOT NULL,
            reference_type TEXT NULL,
            reference_id TEXT NULL,
            exception_code TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'MEDIUM',
            status TEXT NOT NULL DEFAULT 'OPEN',
            retryable INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL,
            resolution_note TEXT NULL,
            raised_at TEXT NOT NULL,
            resolved_at TEXT NULL,
            raised_by TEXT NOT NULL,
            resolved_by TEXT NULL
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_mobile_exception_key ON mobile_transaction_exceptions(integration_id, exception_code)",
        "CREATE INDEX IF NOT EXISTS ix_mobile_exception_scope ON mobile_transaction_exceptions(entity_id,location_id,status,severity,raised_at)",
        "CREATE INDEX IF NOT EXISTS ix_mobile_exception_ref ON mobile_transaction_exceptions(reference_type,reference_id,status)",
    ]
    with engine.begin() as c:
        for s in stmts:
            c.execute(text(s))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('mobile.exception.view','View mobile transaction exceptions') ON CONFLICT(permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('mobile.exception.manage','Resolve and retry mobile transaction exceptions') ON CONFLICT(permission_id) DO NOTHING"))
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'mobile.exception.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': r})
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'mobile.exception.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': r})


class ResolveIn(BaseModel):
    resolution_note: str = Field(min_length=3, max_length=1000)


class RetryIn(BaseModel):
    resolution_note: str = Field(min_length=3, max_length=1000)


def _integration(engine, integration_id):
    with engine.connect() as c:
        return c.execute(text('SELECT * FROM mobile_transaction_integrations WHERE integration_id=:i'), {'i': str(integration_id)}).mappings().first()


def _create_exception(c, row, code, severity, retryable, message, user_id):
    existing = c.execute(text('SELECT * FROM mobile_transaction_exceptions WHERE integration_id=:i AND exception_code=:c'), {'i': row['integration_id'], 'c': code}).mappings().first()
    if existing:
        return dict(existing)
    eid = str(uuid4())
    c.execute(text("""INSERT INTO mobile_transaction_exceptions
        (exception_id,integration_id,organization_id,entity_id,location_id,transaction_type,reference_type,reference_id,exception_code,severity,status,retryable,message,raised_at,raised_by)
        VALUES(:id,:i,:o,:e,:l,:t,:rt,:ri,:c,:s,'OPEN',:r,:m,:d,:u)"""), {
        'id': eid, 'i': row['integration_id'], 'o': row['organization_id'], 'e': row['entity_id'], 'l': row['location_id'],
        't': row['transaction_type'], 'rt': row['reference_type'], 'ri': row['reference_id'], 'c': code,
        's': severity, 'r': 1 if retryable else 0, 'm': message, 'd': _now(), 'u': user_id
    })
    c.execute(text("INSERT INTO mobile_transaction_audit(audit_id,integration_id,action,from_status,to_status,message,actor_user_id,created_at) VALUES(:a,:i,'EXCEPTION',:f,:t,:m,:u,:d)"), {
        'a': str(uuid4()), 'i': row['integration_id'], 'f': row['status'], 't': row['status'], 'm': f'{code}: {message}', 'u': user_id, 'd': _now()
    })
    return c.execute(text('SELECT * FROM mobile_transaction_exceptions WHERE exception_id=:id'), {'id': eid}).mappings().first()


def register_v90gv_routes(app: FastAPI, engine):
    ensure_v90gv_schema(engine)

    @app.get('/ui/mobile-exception-reconciliation')
    def ui():
        return FileResponse('web/mobile-exception-reconciliation.html')

    @app.post('/v90gv/mobile/reconcile/{integration_id}')
    def reconcile(integration_id: UUID, request: Request):
        row = _integration(engine, integration_id)
        if not row:
            raise HTTPException(404, 'integration not found')
        user = _user(engine, request, row['entity_id'], row['location_id'], 'mobile.exception.manage')
        with engine.begin() as c:
            exec_row = c.execute(text('SELECT * FROM mobile_execution_records WHERE integration_id=:i'), {'i': str(integration_id)}).mappings().first()
            code = None; severity = 'MEDIUM'; retryable = False; message = ''
            status = str(row['status']).upper()
            if status == 'REJECTED':
                code, severity, retryable, message = 'INTEGRATION_REJECTED', 'HIGH', False, row['validation_message'] or 'Mobile integration was rejected during validation'
            elif status == 'READY' and exec_row:
                code, severity, retryable, message = 'EXECUTION_STATE_MISMATCH', 'HIGH', False, 'Execution record exists while integration remains READY'
            elif status == 'POSTED' and not exec_row:
                code, severity, retryable, message = 'POSTING_EXECUTION_GAP', 'HIGH', True, 'Integration is POSTED but no execution record exists'
            elif status == 'READY':
                code, severity, retryable, message = 'READY_REQUIRES_EXECUTION', 'LOW', True, 'Integration remains READY and requires controlled execution or cancellation'
            elif status == 'POSTED' and exec_row and exec_row['status'] != 'EXECUTED':
                code, severity, retryable, message = 'EXECUTION_STATUS_MISMATCH', 'HIGH', False, f"Execution record status is {exec_row['status']}"
            else:
                code = 'NO_EXCEPTION'; message = 'No reconciliation exception detected'
            if code != 'NO_EXCEPTION':
                ex = _create_exception(c, row, code, severity, retryable, message, user.user_id)
                return {'integration_id': str(integration_id), 'status': 'EXCEPTION_OPEN', 'exception': dict(ex)}
        return {'integration_id': str(integration_id), 'status': 'RECONCILED', 'exception': None}

    @app.post('/v90gv/mobile/exceptions/{exception_id}/resolve')
    def resolve(exception_id: UUID, body: ResolveIn, request: Request):
        with engine.connect() as c:
            ex = c.execute(text('SELECT * FROM mobile_transaction_exceptions WHERE exception_id=:i'), {'i': str(exception_id)}).mappings().first()
        if not ex:
            raise HTTPException(404, 'exception not found')
        user = _user(engine, request, ex['entity_id'], ex['location_id'], 'mobile.exception.manage')
        if ex['status'] == 'RESOLVED':
            return {'exception_id': str(exception_id), 'status': 'RESOLVED', 'idempotent': True}
        with engine.begin() as c:
            c.execute(text("UPDATE mobile_transaction_exceptions SET status='RESOLVED',resolution_note=:n,resolved_at=:d,resolved_by=:u WHERE exception_id=:i AND status='OPEN'"), {'n': body.resolution_note, 'd': _now(), 'u': user.user_id, 'i': str(exception_id)})
            c.execute(text("INSERT INTO mobile_transaction_audit(audit_id,integration_id,action,from_status,to_status,message,actor_user_id,created_at) VALUES(:a,:i,'EXCEPTION_RESOLVE','OPEN','RESOLVED',:m,:u,:d)"), {'a': str(uuid4()), 'i': ex['integration_id'], 'm': body.resolution_note, 'u': user.user_id, 'd': _now()})
        return {'exception_id': str(exception_id), 'status': 'RESOLVED', 'resolution_note': body.resolution_note}

    @app.post('/v90gv/mobile/exceptions/{exception_id}/retry')
    def retry(exception_id: UUID, body: RetryIn, request: Request):
        with engine.connect() as c:
            ex = c.execute(text('SELECT * FROM mobile_transaction_exceptions WHERE exception_id=:i'), {'i': str(exception_id)}).mappings().first()
            row = c.execute(text('SELECT * FROM mobile_transaction_integrations WHERE integration_id=:i'), {'i': ex['integration_id'] if ex else ''}).mappings().first()
        if not ex or not row:
            raise HTTPException(404, 'exception or integration not found')
        user = _user(engine, request, ex['entity_id'], ex['location_id'], 'mobile.exception.manage')
        if ex['status'] != 'OPEN':
            raise HTTPException(409, 'exception is not open')
        if not ex['retryable']:
            raise HTTPException(409, 'exception is not retryable')
        if row['status'] != 'READY':
            raise HTTPException(409, f"integration is {row['status']}; only READY integrations may be retried")
        with engine.begin() as c:
            c.execute(text("UPDATE mobile_transaction_exceptions SET status='RESOLVED',resolution_note=:n,resolved_at=:d,resolved_by=:u WHERE exception_id=:i"), {'n': 'Retry authorized: ' + body.resolution_note, 'd': _now(), 'u': user.user_id, 'i': str(exception_id)})
            c.execute(text("INSERT INTO mobile_transaction_audit(audit_id,integration_id,action,from_status,to_status,message,actor_user_id,created_at) VALUES(:a,:i,'EXCEPTION_RETRY','READY','READY',:m,:u,:d)"), {'a': str(uuid4()), 'i': row['integration_id'], 'm': 'Retry authorized: ' + body.resolution_note, 'u': user.user_id, 'd': _now()})
        return {'exception_id': str(exception_id), 'integration_id': row['integration_id'], 'status': 'READY', 'retry_authorized': True}

    @app.get('/v90gv/mobile/exceptions')
    def exceptions(organization_id: UUID, entity_id: UUID, location_id: UUID | None = None, status: str | None = None, request: Request = None):
        _user(engine, request, entity_id, location_id, 'mobile.exception.view')
        q = 'SELECT * FROM mobile_transaction_exceptions WHERE organization_id=:o AND entity_id=:e'; p = {'o': str(organization_id), 'e': str(entity_id)}
        if location_id:
            q += ' AND (location_id=:l OR location_id IS NULL)'; p['l'] = str(location_id)
        if status:
            q += ' AND status=:s'; p['s'] = status.upper()
        q += ' ORDER BY raised_at DESC'
        with engine.connect() as c:
            rows = c.execute(text(q), p).mappings().all()
        return {'exceptions': [dict(r) for r in rows]}
