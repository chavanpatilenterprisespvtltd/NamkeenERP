from fastapi.testclient import TestClient
from app.__main__ import app
from app.auth import UserRecord, hash_password, make_access_token, parse_access_token, verify_password


def test_password_hash_and_verify():
    h = hash_password("secret")
    assert verify_password("secret", h)
    assert not verify_password("wrong", h)


def test_token_round_trip():
    u = UserRecord("u1", "alice", "Manager")
    token = make_access_token(u)
    parsed = parse_access_token(token)
    assert parsed == u


def test_login_and_me(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "secret123")
    client = TestClient(app)
    r = client.post("/auth/login", json={"username": "admin", "password": "secret123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "Super Admin"


def test_auth_required_for_me():
    client = TestClient(app)
    r = client.get("/auth/me")
    assert r.status_code == 401
