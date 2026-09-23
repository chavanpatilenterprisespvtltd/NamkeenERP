from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .auth import authenticate, UserRecord
from .identity import permissions_for_user


PERMISSIONS = {
    'security.view': 'View security sessions and devices',
    'security.manage': 'Manage security devices and sessions',
}

LOGIN_WINDOW_SECONDS = int(os.getenv('AUTH_LOGIN_WINDOW_SECONDS', '300'))
LOGIN_MAX_FAILURES = int(os.getenv('AUTH_LOGIN_MAX_FAILURES', '8'))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def ensure_security_schema(engine: Engine) -> None:
    if engine.dialect.name == 'sqlite':
        statements = [
            "CREATE TABLE IF NOT EXISTS security_devices (device_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, device_code TEXT NOT NULL, device_name TEXT NOT NULL, platform TEXT NOT NULL DEFAULT 'ANDROID', fingerprint_hash TEXT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, last_seen_at TEXT NULL, UNIQUE(user_id, device_code))",
            "CREATE TABLE IF NOT EXISTS security_sessions (session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_digest TEXT NOT NULL UNIQUE, device_id TEXT NULL, ip_address TEXT NULL, user_agent TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL, last_seen_at TEXT NULL, revoked_at TEXT NULL, revoked_reason TEXT NULL)",
            "CREATE TABLE IF NOT EXISTS security_login_attempts (attempt_id TEXT PRIMARY KEY, username TEXT NOT NULL, ip_address TEXT NOT NULL, attempted_at TEXT NOT NULL, success INTEGER NOT NULL DEFAULT 0)",
            "CREATE INDEX IF NOT EXISTS ix_security_sessions_user_active ON security_sessions(user_id, revoked_at, expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_security_attempts_lookup ON security_login_attempts(username, ip_address, attempted_at)",
        ]
    else:
        statements = [
            "CREATE TABLE IF NOT EXISTS security_devices (device_id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64) NOT NULL, device_code VARCHAR(120) NOT NULL, device_name VARCHAR(160) NOT NULL, platform VARCHAR(40) NOT NULL DEFAULT 'ANDROID', fingerprint_hash VARCHAR(128) NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, last_seen_at TIMESTAMPTZ NULL, UNIQUE(user_id, device_code))",
            "CREATE TABLE IF NOT EXISTS security_sessions (session_id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64) NOT NULL, token_digest CHAR(64) NOT NULL UNIQUE, device_id VARCHAR(64) NULL, ip_address VARCHAR(64) NULL, user_agent TEXT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMPTZ NOT NULL, last_seen_at TIMESTAMPTZ NULL, revoked_at TIMESTAMPTZ NULL, revoked_reason VARCHAR(160) NULL)",
            "CREATE TABLE IF NOT EXISTS security_login_attempts (attempt_id VARCHAR(64) PRIMARY KEY, username VARCHAR(120) NOT NULL, ip_address VARCHAR(64) NOT NULL, attempted_at TIMESTAMPTZ NOT NULL, success BOOLEAN NOT NULL DEFAULT FALSE)",
            "CREATE INDEX IF NOT EXISTS ix_security_sessions_user_active ON security_sessions(user_id, revoked_at, expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_security_attempts_lookup ON security_login_attempts(username, ip_address, attempted_at)",
        ]
    with engine.begin() as c:
        for stmt in statements:
            c.execute(text(stmt))
        for pid, name in PERMISSIONS.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id, permission_name) VALUES (:id,:name) ON CONFLICT(permission_id) DO NOTHING"), {'id': pid, 'name': name})
        for role in ('super_admin', 'manager'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id, permission_id) VALUES (:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role, 'p': 'security.view'})
            c.execute(text("INSERT INTO erp_role_permissions(role_id, permission_id) VALUES (:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role, 'p': 'security.manage'})


def _allowed(engine: Engine, user: UserRecord, permission: str) -> bool:
    return permission in permissions_for_user(engine, user.user_id)


def record_login_attempt(engine: Engine, username: str, ip_address: str, success: bool) -> None:
    with engine.begin() as c:
        c.execute(text("INSERT INTO security_login_attempts(attempt_id,username,ip_address,attempted_at,success) VALUES(:id,:u,:ip,:t,:s)"), {'id': str(uuid4()), 'u': username.strip().lower(), 'ip': ip_address, 't': _now(), 's': 1 if success else 0})
        # Keep the table bounded while retaining a useful rolling window.
        cutoff = datetime.now(timezone.utc).timestamp() - 86400
        c.execute(text("DELETE FROM security_login_attempts WHERE attempted_at < :cut"), {'cut': datetime.fromtimestamp(cutoff, timezone.utc).isoformat()})


def login_is_throttled(engine: Engine, username: str, ip_address: str) -> bool:
    cutoff = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - LOGIN_WINDOW_SECONDS, timezone.utc).isoformat()
    with engine.connect() as c:
        row = c.execute(text("SELECT COUNT(*) AS n FROM security_login_attempts WHERE username=:u AND ip_address=:ip AND success=0 AND attempted_at >= :cut"), {'u': username.strip().lower(), 'ip': ip_address, 'cut': cutoff}).first()
        return int(row[0] or 0) >= LOGIN_MAX_FAILURES


def create_session(engine: Engine, user: UserRecord, token: str, request: Request, device_id: str | None = None) -> str:
    sid = token.split('|')[4]
    expiry = token.split('|')[3]
    digest = _token_digest(token)
    with engine.begin() as c:
        if device_id:
            dev = c.execute(text("SELECT device_id FROM security_devices WHERE device_id=:d AND user_id=:u AND active=1"), {'d': device_id, 'u': user.user_id}).first()
            if not dev:
                raise HTTPException(404, 'device not found or inactive')
            c.execute(text("UPDATE security_devices SET last_seen_at=CURRENT_TIMESTAMP WHERE device_id=:d"), {'d': device_id})
        c.execute(text("INSERT INTO security_sessions(session_id,user_id,token_digest,device_id,ip_address,user_agent,created_at,expires_at,last_seen_at) VALUES(:sid,:u,:td,:d,:ip,:ua,:ca,:ex,:ls)"), {
            'sid': sid, 'u': user.user_id, 'td': digest, 'd': device_id, 'ip': request.client.host if request.client else None,
            'ua': request.headers.get('user-agent'), 'ca': _now(), 'ex': datetime.fromtimestamp(int(expiry), timezone.utc).isoformat(), 'ls': _now(),
        })
    return sid


def validate_token_session(engine: Engine, token: str) -> bool:
    """Validate persisted sessions. Legacy tokens are allowed for compatibility until explicitly registered/revoked."""
    digest = _token_digest(token)
    with engine.connect() as c:
        row = c.execute(text("SELECT session_id,expires_at,revoked_at FROM security_sessions WHERE token_digest=:d"), {'d': digest}).mappings().first()
    if not row:
        return True
    if row['revoked_at']:
        return False
    try:
        expiry = datetime.fromisoformat(str(row['expires_at']).replace('Z', '+00:00'))
        if expiry <= datetime.now(timezone.utc):
            return False
    except ValueError:
        return False
    return True


def current_session(engine: Engine, token: str):
    digest = _token_digest(token)
    with engine.connect() as c:
        return c.execute(text("SELECT * FROM security_sessions WHERE token_digest=:d"), {'d': digest}).mappings().first()


def register_device(engine: Engine, user: UserRecord, body: dict[str, Any]) -> dict[str, Any]:
    did = body.get('device_id') or str(uuid4())
    with engine.begin() as c:
        existing = c.execute(text("SELECT device_id FROM security_devices WHERE user_id=:u AND device_code=:dc"), {'u': user.user_id, 'dc': body['device_code'].strip()}).first()
        if existing and str(existing[0]) != did:
            raise HTTPException(409, 'device code already registered')
        c.execute(text("INSERT INTO security_devices(device_id,user_id,device_code,device_name,platform,fingerprint_hash,active,last_seen_at) VALUES(:id,:u,:dc,:dn,:p,:fh,1,:t) ON CONFLICT(device_id) DO UPDATE SET device_name=excluded.device_name, platform=excluded.platform, fingerprint_hash=excluded.fingerprint_hash, active=1, last_seen_at=excluded.last_seen_at"), {
            'id': did, 'u': user.user_id, 'dc': body['device_code'].strip(), 'dn': body['device_name'].strip(), 'p': body.get('platform', 'ANDROID').upper(), 'fh': body.get('fingerprint_hash'), 't': _now()
        })
    return {'device_id': did, 'status': 'ACTIVE'}


def register_v90bf_routes(app: FastAPI, engine: Engine) -> None:
    ensure_security_schema(engine)
    app.state.security_engine = engine

    @app.post('/v90bf/devices/register')
    def devices_register(payload: dict, request: Request):
        user = authenticate(request)
        if not _allowed(engine, user, 'security.manage'):
            raise HTTPException(403, 'permission denied')
        required = ('device_code', 'device_name')
        if any(not str(payload.get(k, '')).strip() for k in required):
            raise HTTPException(422, 'device_code and device_name are required')
        return register_device(engine, user, payload)

    @app.get('/v90bf/devices')
    def devices_list(request: Request):
        user = authenticate(request)
        if not _allowed(engine, user, 'security.view'):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as c:
            rows = c.execute(text("SELECT device_id,device_code,device_name,platform,active,created_at,last_seen_at FROM security_devices WHERE user_id=:u ORDER BY created_at DESC"), {'u': user.user_id}).mappings().all()
        return {'devices': [dict(r) for r in rows]}

    @app.post('/v90bf/devices/{device_id}/revoke')
    def device_revoke(device_id: str, request: Request):
        user = authenticate(request)
        if not _allowed(engine, user, 'security.manage'):
            raise HTTPException(403, 'permission denied')
        with engine.begin() as c:
            res = c.execute(text("UPDATE security_devices SET active=0 WHERE device_id=:d AND user_id=:u"), {'d': device_id, 'u': user.user_id})
            if res.rowcount != 1:
                raise HTTPException(404, 'device not found')
            c.execute(text("UPDATE security_sessions SET revoked_at=CURRENT_TIMESTAMP, revoked_reason='device revoked' WHERE device_id=:d AND user_id=:u AND revoked_at IS NULL"), {'d': device_id, 'u': user.user_id})
        return {'device_id': device_id, 'status': 'REVOKED'}

    @app.get('/v90bf/sessions')
    def sessions_list(request: Request, include_revoked: bool = False):
        user = authenticate(request)
        if not _allowed(engine, user, 'security.view'):
            raise HTTPException(403, 'permission denied')
        sql = "SELECT session_id,device_id,ip_address,user_agent,created_at,expires_at,last_seen_at,revoked_at,revoked_reason FROM security_sessions WHERE user_id=:u"
        if not include_revoked:
            sql += " AND revoked_at IS NULL AND expires_at > CURRENT_TIMESTAMP"
        sql += " ORDER BY created_at DESC"
        with engine.connect() as c:
            rows = c.execute(text(sql), {'u': user.user_id}).mappings().all()
        return {'sessions': [dict(r) for r in rows]}

    @app.post('/v90bf/sessions/{session_id}/revoke')
    def session_revoke(session_id: str, request: Request, reason: str = 'revoked by user'):
        user = authenticate(request)
        if not _allowed(engine, user, 'security.manage'):
            raise HTTPException(403, 'permission denied')
        with engine.begin() as c:
            res = c.execute(text("UPDATE security_sessions SET revoked_at=CURRENT_TIMESTAMP, revoked_reason=:r WHERE session_id=:s AND user_id=:u AND revoked_at IS NULL"), {'r': reason[:160], 's': session_id, 'u': user.user_id})
            if res.rowcount != 1:
                raise HTTPException(404, 'active session not found')
        return {'session_id': session_id, 'status': 'REVOKED'}

    @app.post('/v90bf/logout')
    def logout(request: Request):
        user = authenticate(request)
        token = request.headers.get('Authorization', '')[7:].strip()
        with engine.begin() as c:
            c.execute(text("UPDATE security_sessions SET revoked_at=CURRENT_TIMESTAMP, revoked_reason='logout' WHERE user_id=:u AND token_digest=:d AND revoked_at IS NULL"), {'u': user.user_id, 'd': _token_digest(token)})
        return {'status': 'LOGGED_OUT'}

    @app.get('/v90bf/security-status')
    def status(request: Request):
        user = authenticate(request)
        if not _allowed(engine, user, 'security.view'):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as c:
            active_sessions = c.execute(text("SELECT COUNT(*) FROM security_sessions WHERE user_id=:u AND revoked_at IS NULL AND expires_at > CURRENT_TIMESTAMP"), {'u': user.user_id}).scalar() or 0
            active_devices = c.execute(text("SELECT COUNT(*) FROM security_devices WHERE user_id=:u AND active=1"), {'u': user.user_id}).scalar() or 0
        return {'user_id': user.user_id, 'active_sessions': int(active_sessions), 'active_devices': int(active_devices), 'login_window_seconds': LOGIN_WINDOW_SECONDS, 'login_max_failures': LOGIN_MAX_FAILURES}
