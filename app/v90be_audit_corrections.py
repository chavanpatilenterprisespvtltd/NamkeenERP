from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _scope(engine, request: Request, permission: str, entity_id: str | None = None, location_id: str | None = None):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    if entity_id:
        try:
            assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90be_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS erp_audit_log (
            audit_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NULL,
            location_id TEXT NULL,
            actor_user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            before_json TEXT NULL,
            after_json TEXT NULL,
            reason TEXT NULL,
            correlation_id TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS corrective_transaction_requests (
            correction_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            correction_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            before_json TEXT NULL,
            proposed_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            requested_by TEXT NOT NULL,
            requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            decided_by TEXT NULL,
            decided_at TEXT NULL,
            decision_reason TEXT NULL,
            applied_at TEXT NULL,
            applied_by TEXT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_audit_scope_time ON erp_audit_log(organization_id,entity_id,location_id,created_at)",
        "CREATE INDEX IF NOT EXISTS ix_audit_object ON erp_audit_log(object_type,object_id,created_at)",
        "CREATE INDEX IF NOT EXISTS ix_correction_queue ON corrective_transaction_requests(organization_id,entity_id,status,requested_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_correction_active_source ON corrective_transaction_requests(source_type,source_id) WHERE status IN ('PENDING','APPROVED')",
    ]
    with engine.begin() as c:
        for s in stmts:
            c.execute(text(s))
        perms = {
            'audit.view': 'View audit log and transaction history',
            'correction.view': 'View corrective transaction requests',
            'correction.submit': 'Submit corrective transaction requests',
            'correction.approve': 'Approve or reject corrective transaction requests',
        }
        for p, n in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p': p, 'n': n})
        grants = {
            'manager': list(perms),
            'super_admin': list(perms),
            'operator': ['audit.view', 'correction.view', 'correction.submit'],
            'production': ['audit.view', 'correction.view', 'correction.submit'],
            'quality': ['audit.view', 'correction.view', 'correction.submit'],
            'warehouse': ['audit.view', 'correction.view', 'correction.submit'],
            'dispatch': ['audit.view', 'correction.view', 'correction.submit'],
            'salesperson': ['audit.view', 'correction.view', 'correction.submit'],
            'mis': ['audit.view', 'correction.view'],
        }
        for role, ps in grants.items():
            for p in ps:
                c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role, 'p': p})


class AuditEventIn(BaseModel):
    organization_id: UUID
    entity_id: UUID | None = None
    location_id: UUID | None = None
    action: str = Field(min_length=2, max_length=80)
    object_type: str = Field(min_length=2, max_length=80)
    object_id: str = Field(min_length=1, max_length=120)
    before: dict | None = None
    after: dict | None = None
    reason: str | None = Field(default=None, max_length=1000)
    correlation_id: str | None = Field(default=None, max_length=120)


class CorrectionIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    source_type: str = Field(min_length=2, max_length=80)
    source_id: str = Field(min_length=1, max_length=120)
    correction_type: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=5, max_length=2000)
    proposed: dict


class CorrectionDecisionIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


def _record_audit(engine, body: AuditEventIn, actor_id: str):
    aid = str(uuid4())
    with engine.begin() as c:
        c.execute(text("""INSERT INTO erp_audit_log(
            audit_id,organization_id,entity_id,location_id,actor_user_id,action,object_type,object_id,
            before_json,after_json,reason,correlation_id)
            VALUES(:id,:o,:e,:l,:u,:a,:ot,:oi,:b,:af,:r,:c)"""), {
            'id': aid, 'o': str(body.organization_id), 'e': str(body.entity_id) if body.entity_id else None,
            'l': str(body.location_id) if body.location_id else None, 'u': actor_id, 'a': body.action.upper(),
            'ot': body.object_type.upper(), 'oi': body.object_id,
            'b': json.dumps(body.before, default=str) if body.before is not None else None,
            'af': json.dumps(body.after, default=str) if body.after is not None else None,
            'r': body.reason, 'c': body.correlation_id,
        })
    return aid


def register_v90be_routes(app: FastAPI, engine):
    ensure_v90be_schema(engine)

    @app.post('/v90be/audit')
    def record_audit(body: AuditEventIn, request: Request):
        user = _scope(engine, request, 'audit.view', str(body.entity_id) if body.entity_id else None, str(body.location_id) if body.location_id else None)
        # A write to the immutable log requires the stronger correction capability only when explicitly recording a correction action.
        if body.action.upper().startswith('CORRECTION'):
            if 'correction.submit' not in permissions_for_user(engine, user.user_id):
                raise HTTPException(403, 'correction audit permission required')
        return {'audit_id': _record_audit(engine, body, str(user.user_id)), 'status': 'RECORDED'}

    @app.get('/v90be/audit')
    def list_audit(
        organization_id: UUID,
        request: Request,
        entity_id: UUID | None = None,
        location_id: UUID | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        action: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ):
        _scope(engine, request, 'audit.view', str(entity_id) if entity_id else None, str(location_id) if location_id else None)
        sql = "SELECT * FROM erp_audit_log WHERE organization_id=:o"
        params = {'o': str(organization_id), 'lim': limit}
        if entity_id: sql += " AND entity_id=:e"; params['e'] = str(entity_id)
        if location_id: sql += " AND location_id=:l"; params['l'] = str(location_id)
        if object_type: sql += " AND object_type=:ot"; params['ot'] = object_type.upper()
        if object_id: sql += " AND object_id=:oi"; params['oi'] = object_id
        if action: sql += " AND action=:a"; params['a'] = action.upper()
        sql += " ORDER BY created_at DESC LIMIT :lim"
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text(sql), params).mappings().all()]
        return {'items': rows, 'count': len(rows)}

    @app.post('/v90be/corrections')
    def submit_correction(body: CorrectionIn, request: Request):
        user = _scope(engine, request, 'correction.submit', str(body.entity_id), str(body.location_id) if body.location_id else None)
        cid = str(uuid4())
        with engine.begin() as c:
            try:
                c.execute(text("""INSERT INTO corrective_transaction_requests(
                    correction_id,organization_id,entity_id,location_id,source_type,source_id,correction_type,
                    reason,before_json,proposed_json,requested_by)
                    VALUES(:id,:o,:e,:l,:st,:si,:ct,:r,:b,:p,:u)"""), {
                    'id': cid, 'o': str(body.organization_id), 'e': str(body.entity_id), 'l': str(body.location_id) if body.location_id else None,
                    'st': body.source_type.upper(), 'si': body.source_id, 'ct': body.correction_type.upper(), 'r': body.reason,
                    'b': json.dumps(body.proposed.get('_before'), default=str) if isinstance(body.proposed, dict) and '_before' in body.proposed else None,
                    'p': json.dumps(body.proposed, default=str), 'u': str(user.user_id),
                })
            except Exception as exc:
                if 'ux_correction_active_source' in str(exc) or 'UNIQUE' in str(exc).upper():
                    raise HTTPException(409, 'an active correction already exists for this source transaction') from exc
                raise
        return {'correction_id': cid, 'status': 'PENDING'}

    @app.get('/v90be/corrections')
    def list_corrections(organization_id: UUID, request: Request, status: str | None = None, entity_id: UUID | None = None):
        _scope(engine, request, 'correction.view', str(entity_id) if entity_id else None)
        sql = "SELECT * FROM corrective_transaction_requests WHERE organization_id=:o"; params = {'o': str(organization_id)}
        if status: sql += ' AND status=:s'; params['s'] = status.upper()
        if entity_id: sql += ' AND entity_id=:e'; params['e'] = str(entity_id)
        sql += ' ORDER BY requested_at DESC'
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text(sql), params).mappings().all()]
        return {'corrections': rows}

    def decide(correction_id: UUID, request: Request, approved: bool, body: CorrectionDecisionIn):
        user = _scope(engine, request, 'correction.approve')
        with engine.begin() as c:
            row_sql = 'SELECT * FROM corrective_transaction_requests WHERE correction_id=:i'
            if engine.dialect.name == 'postgresql':
                row_sql += ' FOR UPDATE'
            row = c.execute(text(row_sql), {'i': str(correction_id)}).mappings().first()
            if not row:
                raise HTTPException(404, 'correction not found')
            if row['status'] != 'PENDING':
                raise HTTPException(409, 'correction is no longer pending')
            if str(row['requested_by']) == str(user.user_id):
                raise HTTPException(409, 'requester cannot approve or reject own correction')
            if not approved and not body.reason:
                raise HTTPException(422, 'rejection reason is required')
            status = 'APPROVED' if approved else 'REJECTED'
            c.execute(text("""UPDATE corrective_transaction_requests SET status=:s,decided_by=:u,decided_at=CURRENT_TIMESTAMP,decision_reason=:r,applied_at=CASE WHEN :a=1 THEN CURRENT_TIMESTAMP ELSE NULL END,applied_by=CASE WHEN :a=1 THEN :u ELSE NULL END WHERE correction_id=:i"""), {'s': status, 'u': str(user.user_id), 'r': body.reason, 'a': 1 if approved else 0, 'i': str(correction_id)})
            c.execute(text("""INSERT INTO erp_audit_log(audit_id,organization_id,entity_id,location_id,actor_user_id,action,object_type,object_id,before_json,after_json,reason,correlation_id)
                VALUES(:id,:o,:e,:l,:u,:a,'CORRECTIVE_TRANSACTION',:oi,:b,:af,:r,:oi)"""), {
                    'id': str(uuid4()), 'o': row['organization_id'], 'e': row['entity_id'], 'l': row['location_id'], 'u': str(user.user_id),
                    'a': status, 'oi': str(correction_id), 'b': row['before_json'], 'af': row['proposed_json'], 'r': body.reason,
                })
        return {'correction_id': str(correction_id), 'status': status}

    @app.post('/v90be/corrections/{correction_id}/approve')
    def approve_correction(correction_id: UUID, body: CorrectionDecisionIn, request: Request):
        return decide(correction_id, request, True, body)

    @app.post('/v90be/corrections/{correction_id}/reject')
    def reject_correction(correction_id: UUID, body: CorrectionDecisionIn, request: Request):
        return decide(correction_id, request, False, body)
