from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.migrations import Migration, MigrationError, validate_migration_set
from app.v90bg_backup_restore import ensure_backup_schema, validate_migration_history, verify_backup_file

ROOT = Path(__file__).resolve().parents[1]


def test_v90bg_migration_manifest_and_filename_validation():
    from app.migrations import load_migrations
    ms = load_migrations(ROOT)
    assert ms[-1].version >= 132
    assert any(m.version == 132 and m.filename == "132_v90bg_backup_restore_migration_validation.sql" for m in ms)


def test_unmanifested_sql_is_rejected(tmp_path):
    (tmp_path / "migrations").mkdir()
    payload = b"SELECT 1;\n"
    p = tmp_path / "migrations" / "061_test.sql"
    p.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (tmp_path / "migrations" / "062_extra.sql").write_bytes(payload)
    with pytest.raises(MigrationError, match="Unmanifested migration files"):
        validate_migration_set(tmp_path, (Migration(61, p.name, digest),))


def test_filename_version_mismatch_is_rejected(tmp_path):
    (tmp_path / "migrations").mkdir()
    payload = b"SELECT 1;\n"
    p = tmp_path / "migrations" / "062_test.sql"
    p.write_bytes(payload)
    with pytest.raises(MigrationError, match="filename/version mismatch"):
        validate_migration_set(tmp_path, (Migration(61, p.name, hashlib.sha256(payload).hexdigest()),))


def test_backup_schema_is_created_for_test_runtime():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    ensure_backup_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='erp_backup_runs'")).scalar_one() == "erp_backup_runs"


def test_backup_file_missing_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_backup_file(tmp_path / "missing.dump")
