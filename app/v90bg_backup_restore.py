from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import Engine, text

from .auth import authenticate
from .identity import permissions_for_user
from .migrations import MigrationError, applied_versions, load_migrations
from .release import load_release_info


@dataclass(frozen=True)
class MigrationValidationReport:
    expected_target: int
    applied_target: int | None
    applied_count: int
    valid: bool
    detail: str


def _has_permission(engine: Engine, request: Request, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail="permission denied")
    return user


def ensure_backup_schema(engine: Engine) -> None:
    ddl = {
        "postgresql": """
        CREATE TABLE IF NOT EXISTS erp_backup_runs (
            run_id VARCHAR(64) PRIMARY KEY,
            backup_type VARCHAR(32) NOT NULL,
            status VARCHAR(24) NOT NULL,
            release_version VARCHAR(32) NOT NULL,
            migration_target INTEGER NOT NULL,
            file_path TEXT,
            file_size_bytes BIGINT,
            sha256 CHAR(64),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            error_message TEXT
        )
        """,
        "sqlite": """
        CREATE TABLE IF NOT EXISTS erp_backup_runs (
            run_id TEXT PRIMARY KEY,
            backup_type TEXT NOT NULL,
            status TEXT NOT NULL,
            release_version TEXT NOT NULL,
            migration_target INTEGER NOT NULL,
            file_path TEXT,
            file_size_bytes INTEGER,
            sha256 TEXT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            error_message TEXT
        )
        """,
    }
    dialect = engine.dialect.name
    if dialect not in ddl:
        raise MigrationError(f"Unsupported database dialect: {dialect}")
    with engine.begin() as conn:
        conn.execute(text(ddl[dialect]))


def validate_release_files(root: Path | None = None) -> tuple[int, str]:
    base = root or Path(__file__).resolve().parents[1]
    migrations = load_migrations(base)
    return migrations[-1].version, migrations[-1].filename


def validate_migration_history(engine: Engine, root: Path | None = None, expected_target: int | None = None) -> MigrationValidationReport:
    """Validate applied PostgreSQL migration history against the immutable release manifest."""
    base = root or Path(__file__).resolve().parents[1]
    migrations = load_migrations(base)
    expected = expected_target if expected_target is not None else migrations[-1].version
    known = {m.version: m for m in migrations if m.version <= expected}
    applied = applied_versions(engine)
    versions = sorted(applied)
    if not versions:
        return MigrationValidationReport(expected, None, 0, False, "no schema migrations are recorded")
    unknown = [v for v in versions if v not in known]
    if unknown:
        return MigrationValidationReport(expected, versions[-1], len(versions), False, f"unknown applied migration versions: {unknown}")
    expected_versions = list(range(migrations[0].version, min(expected, versions[-1]) + 1))
    missing = [v for v in expected_versions if v not in applied]
    if missing:
        return MigrationValidationReport(expected, versions[-1], len(versions), False, f"missing applied migration versions: {missing}")
    mismatches = [v for v, m in known.items() if v in applied and applied[v] != m.sha256]
    if mismatches:
        return MigrationValidationReport(expected, versions[-1], len(versions), False, f"applied checksum mismatch: {mismatches}")
    if versions[-1] != expected:
        return MigrationValidationReport(expected, versions[-1], len(versions), False, f"database schema target {versions[-1]} does not match release target {expected}")
    return MigrationValidationReport(expected, versions[-1], len(versions), True, "migration history matches release manifest")


def _db_connection_args(engine: Engine) -> tuple[list[str], dict[str, str]]:
    url = engine.url
    if url.get_backend_name() != "postgresql":
        raise MigrationError("Backup/restore tooling requires PostgreSQL")
    args: list[str] = []
    if url.host:
        args += ["-h", url.host]
    if url.port:
        args += ["-p", str(url.port)]
    if url.username:
        args += ["-U", url.username]
    if url.database:
        args += ["-d", url.database]
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    query = dict(url.query)
    if "sslmode" in query:
        env["PGSSLMODE"] = str(query["sslmode"])
    return args, env


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _insert_backup_run(engine: Engine, row: dict[str, Any]) -> None:
    ensure_backup_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO erp_backup_runs
            (run_id, backup_type, status, release_version, migration_target, file_path, file_size_bytes, sha256, completed_at, error_message)
            VALUES (:run_id,:backup_type,:status,:release_version,:migration_target,:file_path,:file_size_bytes,:sha256,:completed_at,:error_message)
        """), row)


def create_postgres_backup(engine: Engine, output_path: str | Path, root: Path | None = None) -> dict[str, Any]:
    report = validate_migration_history(engine, root)
    if not report.valid:
        raise MigrationError(f"Backup blocked: {report.detail}")
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Backup target already exists: {output}")
    shutil.which("pg_dump") or (_ for _ in ()).throw(FileNotFoundError("pg_dump is required"))
    run_id = "bkp_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    started = datetime.now(timezone.utc).isoformat()
    args, env = _db_connection_args(engine)
    cmd = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(output), *args]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            try:
                output.unlink()
            except FileNotFoundError:
                pass
            _insert_backup_run(engine, {
                "run_id": run_id, "backup_type": "postgres_custom", "status": "FAILED",
                "release_version": load_release_info(root).version, "migration_target": report.expected_target,
                "file_path": str(output), "file_size_bytes": None, "sha256": None,
                "completed_at": datetime.now(timezone.utc).isoformat(), "error_message": proc.stderr[-4000:],
            })
            raise RuntimeError(proc.stderr.strip() or "pg_dump failed")
        verify = subprocess.run(["pg_restore", "--list", str(output)], capture_output=True, text=True, check=False)
        if verify.returncode != 0:
            raise RuntimeError(verify.stderr.strip() or "pg_restore validation failed")
        digest = _hash_file(output)
        row = {
            "run_id": run_id, "backup_type": "postgres_custom", "status": "COMPLETED",
            "release_version": load_release_info(root).version, "migration_target": report.expected_target,
            "file_path": str(output), "file_size_bytes": output.stat().st_size, "sha256": digest,
            "completed_at": datetime.now(timezone.utc).isoformat(), "error_message": None,
        }
        _insert_backup_run(engine, row)
        row["started_at"] = started
        return row
    except Exception:
        raise


def verify_backup_file(backup_path: str | Path, expected_sha256: str | None = None) -> dict[str, Any]:
    path = Path(backup_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if shutil.which("pg_restore") is None:
        raise FileNotFoundError("pg_restore is required")
    digest = _hash_file(path)
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("backup SHA-256 mismatch")
    proc = subprocess.run(["pg_restore", "--list", str(path)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip() or "backup archive is not a valid PostgreSQL custom dump")
    return {"valid": True, "path": str(path), "size_bytes": path.stat().st_size, "sha256": digest}


def restore_postgres_backup(engine: Engine, backup_path: str | Path, *, allow_destructive: bool = False) -> dict[str, Any]:
    if not allow_destructive:
        raise PermissionError("Restore is destructive and requires allow_destructive=True")
    verify_backup_file(backup_path)
    args, env = _db_connection_args(engine)
    cmd = ["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "--clean", "--if-exists", str(Path(backup_path).resolve()), *args]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "pg_restore failed")
    return {"restored": True, "path": str(Path(backup_path).resolve())}


def register_v90bg_routes(app: FastAPI, engine: Engine) -> None:
    ensure_backup_schema(engine)

    @app.get("/v90bg/backups/status")
    def backup_status(request: Request):
        _has_permission(engine, request, "backup.view")
        report = validate_migration_history(engine)
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT run_id, backup_type, status, release_version, migration_target, file_path, file_size_bytes, sha256, started_at, completed_at, error_message FROM erp_backup_runs ORDER BY started_at DESC LIMIT 20")).mappings().all()
        return {"migration": report.__dict__, "backups": [dict(r) for r in rows]}

    @app.post("/v90bg/backups/validate")
    def validate_backup_payload(payload: dict[str, Any], request: Request):
        _has_permission(engine, request, "backup.view")
        try:
            return verify_backup_file(payload["path"], payload.get("sha256"))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))


def write_backup_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
