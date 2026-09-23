import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.migrations import Migration, MigrationError, load_migrations, validate_migration_set, ensure_history_table

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_migrations_load_and_checksum():
    migrations = load_migrations(ROOT)
    assert migrations[0].version == 61
    assert migrations[-1].version >= 89
    assert len(migrations) >= 29


def test_checksum_tamper_is_rejected(tmp_path):
    root = tmp_path
    (root / "migrations").mkdir()
    payload = b"SELECT 1;\n"
    path = root / "migrations" / "061_test.sql"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(MigrationError, match="Checksum mismatch"):
        validate_migration_set(root, (Migration(61, "061_test.sql", "0" * 64),))
    validate_migration_set(root, (Migration(61, "061_test.sql", digest),))


def test_sqlite_execution_is_blocked():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with pytest.raises(MigrationError, match="PostgreSQL"):
        ensure_history_table(engine)
