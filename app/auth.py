# FILE PATH: app/auth.py
# ─── Authentication v1.1 (Session CS2 — token secret read from Docker secret file; demo users dev-only) ─
#
# [Session CS2] FIX — PRODUCTION TOKENS WERE SIGNED WITH THE PUBLIC DEFAULT SECRET "dev-only-change-me".
# Confirmed this session by reading the code: make_access_token()/parse_access_token() read only
# AUTH_TOKEN_SECRET, while config/.env.production.example and the compose file supply only
# JWT_SECRET_FILE=/run/secrets/jwt_secret. Result: any production container used the default secret,
# so anyone who read this repo could forge a Super Admin token.
#
# ROOT CAUSE: the V90.bh deployment templates introduced *_FILE secrets but the V90.d auth code
# was never updated to read them.
#
# THE FIX: both functions now call runtime_security.token_secret(), which reads AUTH_TOKEN_SECRET,
# JWT_SECRET or their *_FILE variants and refuses missing/default/short secrets in staging/production.
# default_demo_users() now returns {} unless runtime_security.demo_login_enabled() (dev/test only).
# NOT touched: token format, TTL, password hashing (PBKDF2), session validator hook, require_roles().
# Verified by tests/test_v90gx_runtime_security.py and the unchanged tests/test_v90d_auth.py.
#
# ─── v1.0 HEADER (preserved) ─────────────────────────────────────────────
# Original V90.d authentication foundation; no in-file changelog existed before Session CS2.
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request

from .runtime_security import demo_login_enabled, token_secret

PBKDF2_ITERS = 210_000
TOKEN_TTL_SECONDS = 8 * 60 * 60

@dataclass(frozen=True)
class UserRecord:
    user_id: str
    username: str
    role: str
    active: bool = True


def _iterations() -> int:
    return int(os.getenv("AUTH_PBKDF2_ITERATIONS", str(PBKDF2_ITERS)))


def hash_password(password: str, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _iterations())
    return f"pbkdf2_sha256${_iterations()}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def make_access_token(user: UserRecord, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    expiry = int(time.time()) + ttl_seconds
    nonce = secrets.token_urlsafe(18)
    secret = token_secret()  # [Session CS2] FIX — see file header (reads *_FILE, strict in production).
    body = f"{user.user_id}|{user.username}|{user.role}|{expiry}|{nonce}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def parse_access_token(token: str) -> UserRecord:
    secret = token_secret()  # [Session CS2] FIX — see file header (reads *_FILE, strict in production).
    parts = token.split("|")
    if len(parts) != 6:
        raise HTTPException(status_code=401, detail="invalid authentication token")
    user_id, username, role, expiry, nonce, sig = parts
    body = "|".join(parts[:5])
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="invalid authentication token")
    if int(expiry) < int(time.time()):
        raise HTTPException(status_code=401, detail="authentication token expired")
    return UserRecord(user_id=user_id, username=username, role=role, active=True)


_SESSION_VALIDATOR = None

def set_session_validator(validator):
    global _SESSION_VALIDATOR
    _SESSION_VALIDATOR = validator


def authenticate(request: Request) -> UserRecord:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="authentication required")
    token = auth[7:].strip()
    if _SESSION_VALIDATOR is not None and not _SESSION_VALIDATOR(token):
        raise HTTPException(status_code=401, detail="session revoked or expired")
    return parse_access_token(token)


def require_roles(*roles: str):
    def dependency(request: Request) -> UserRecord:
        user = authenticate(request)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient permissions")
        return user
    return dependency


def default_demo_users() -> dict[str, tuple[UserRecord, str]]:
    # [Session CS2] FIX — see file header. Legacy demo logins exist only in development/test.
    if not demo_login_enabled():
        return {}
    return {
        "admin": (UserRecord("u-admin", "admin", "Super Admin"), os.getenv("DEMO_ADMIN_PASSWORD", "change-me")),
        "manager": (UserRecord("u-manager", "manager", "Manager"), os.getenv("DEMO_MANAGER_PASSWORD", "change-me")),
    }
