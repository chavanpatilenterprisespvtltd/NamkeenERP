# FILE PATH: app/migrations.py
# ─── Migration Runner v1.1 (Session CS2 — superseded migrations recorded, not executed; fix-forward 279) ─
#
# [Session CS2] FIX — THE MIGRATION CHAIN STOPPED AT 073 ON A FRESH POSTGRESQL DATABASE.
# Confirmed live this session on PostgreSQL 16: after the application runtime schema exists, 073, 074 and
# 075 fail ("column request_id does not exist", "column validation_status does not exist"); every later
# migration was therefore never applied. 072 creates master_validation_run with the V84 shape, so 073's
# CREATE TABLE IF NOT EXISTS is skipped.
# ROOT CAUSE: 072 and 073 define the same table with different columns.
# THE FIX (no historical migration file or checksum changed): load_superseded() reads the manifest key
# "superseded" {version: {by, reason}}; migrate() inserts those versions into schema_migrations with their
# real checksum without executing them, and the superseding migration (279) applies the intended end state.
# NOT touched: manifest validation, checksum checks, ordering rules, PostgreSQL-only execution.
#
# ─── v1.0 HEADER (preserved) ─────────────────────────────────────────────
# Original V90.c migration runtime; no in-file changelog existed before Session CS2.
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    sha256: str


class MigrationError(RuntimeError):
    pass


def load_migrations(root: Path | None = None) -> tuple[Migration, ...]:
    base = root or Path(__file__).resolve().parents[1]
    manifest_path = base / "config" / "migration_manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    migrations = tuple(Migration(int(x["version"]), str(x["filename"]), str(x["sha256"])) for x in data["migrations"])
    validate_migration_set(base, migrations)
    return migrations


def validate_migration_set(root: Path, migrations: Iterable[Migration]) -> None:
    items = tuple(migrations)
    versions = [m.version for m in items]
    if not versions or versions != list(range(61, 61 + len(versions))):
        raise MigrationError("Migration versions must be contiguous and ordered from 61")
    if len({m.version for m in items}) != len(items):
        raise MigrationError("Duplicate migration version")
    seen_files: set[str] = set()
    for migration in items:
        if migration.filename in seen_files:
            raise MigrationError(f"Duplicate migration file: {migration.filename}")
        if not re.fullmatch(r"\d{3}_[A-Za-z0-9_]+\.sql", migration.filename):
            raise MigrationError(f"Invalid migration filename: {migration.filename}")
        prefix = int(migration.filename[:3])
        if prefix != migration.version:
            raise MigrationError(f"Migration filename/version mismatch: {migration.filename} vs {migration.version}")
        if not re.fullmatch(r"[0-9a-f]{64}", migration.sha256):
            raise MigrationError(f"Invalid SHA-256 in manifest: {migration.filename}")
        seen_files.add(migration.filename)
        path = root / "migrations" / migration.filename
        if not path.is_file():
            raise MigrationError(f"Missing migration file: {migration.filename}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != migration.sha256:
            raise MigrationError(f"Checksum mismatch: {migration.filename}")
    actual_files = {p.name for p in (root / "migrations").glob("*.sql")}
    manifest_files = {m.filename for m in items}
    unmanifested = sorted(actual_files - manifest_files)
    if unmanifested:
        raise MigrationError(f"Unmanifested migration files: {unmanifested}")


def ensure_history_table(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        raise MigrationError("Migration execution is supported only against PostgreSQL")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version integer PRIMARY KEY,
                filename varchar(255) NOT NULL,
                sha256 char(64) NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        """))


def applied_versions(engine: Engine) -> dict[int, str]:
    ensure_history_table(engine)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version, sha256 FROM schema_migrations ORDER BY version")).mappings().all()
    return {int(row["version"]): str(row["sha256"]) for row in rows}


def load_superseded(root: Path | None = None) -> dict[int, int]:
    """[Session CS2] {version: superseding_version} from config/migration_manifest.json "superseded"."""
    base = root or Path(__file__).resolve().parents[1]
    data = json.loads((base / "config" / "migration_manifest.json").read_text(encoding="utf-8"))
    out = {int(k): int(v["by"]) for k, v in (data.get("superseded") or {}).items()}
    for old, new in out.items():
        if new <= old:
            raise MigrationError(f"Superseding migration {new} must come after {old}")
    return out


def migrate(engine: Engine, root: Path | None = None, target: int | None = None) -> tuple[int, ...]:
    base = root or Path(__file__).resolve().parents[1]
    migrations = load_migrations(base)
    superseded = load_superseded(base)  # [Session CS2] FIX — see file header
    known = {m.version for m in migrations}
    for old, new in superseded.items():
        if new not in known:
            raise MigrationError(f"Superseding migration {new} for {old} is not in the manifest")
    if target is not None:
        migrations = tuple(m for m in migrations if m.version <= target)
    ensure_history_table(engine)
    applied = applied_versions(engine)
    expected_versions = set()
    applied_now: list[int] = []
    for migration in migrations:
        expected_versions.add(migration.version)
        if migration.version in applied:
            if applied[migration.version] != migration.sha256:
                raise MigrationError(f"Applied checksum mismatch: v{migration.version}")
            continue
        if migration.version in superseded and (target is None or superseded[migration.version] <= target):
            # [Session CS2] recorded with its real checksum, not executed; the superseding migration applies the end state.
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO schema_migrations(version, filename, sha256) VALUES (:v, :f, :s)"),
                    {"v": migration.version, "f": migration.filename, "s": migration.sha256},
                )
            applied_now.append(migration.version)
            continue
        sql = (base / "migrations" / migration.filename).read_text(encoding="utf-8")
        if not sql.strip():
            raise MigrationError(f"Empty migration: {migration.filename}")
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)
            conn.execute(
                text("INSERT INTO schema_migrations(version, filename, sha256) VALUES (:v, :f, :s)"),
                {"v": migration.version, "f": migration.filename, "s": migration.sha256},
            )
        applied_now.append(migration.version)
    return tuple(applied_now)
