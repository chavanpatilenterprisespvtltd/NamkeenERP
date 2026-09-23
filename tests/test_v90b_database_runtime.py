from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import __main__
from app.db import DatabaseConfig, create_db_engine, database_ping, load_database_config

ROOT = Path(__file__).resolve().parents[1]


def test_database_config_defaults_to_local_safe_engine():
    cfg = load_database_config({})
    assert cfg.url == "sqlite+pysqlite:///:memory:"
    assert cfg.pool_pre_ping is True


def test_postgres_url_is_normalized_to_psycopg():
    cfg = load_database_config({"DATABASE_URL": "postgresql://u:p@localhost/db"})
    assert cfg.url.startswith("postgresql+psycopg://")


def test_sqlite_engine_can_ping():
    engine = create_db_engine(DatabaseConfig("sqlite+pysqlite:///:memory:"))
    ok, detail = database_ping(engine)
    assert (ok, detail) == (True, "ok")


def test_ready_endpoint_reports_database_health():
    old = __main__.engine
    try:
        __main__.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
        client = TestClient(__main__.app)
        payload = client.get("/ready").json()
        assert payload["status"] == "ready"
        assert payload["database"] == "ok"
        assert payload["version"] .startswith("v90.")
    finally:
        __main__.engine = old
