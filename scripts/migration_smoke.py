# FILE PATH: scripts/migration_smoke.py
# ─── Migration Smoke v1.1 (Session CS2 — `app` importable from CI) ─
# [Session CS2] FIX — CI JOB "migration-smoke" COULD NOT IMPORT `app`.
# Confirmed live this session: `python scripts/migration_smoke.py` → ModuleNotFoundError: No module
# named 'app' (Python puts scripts/ on sys.path, not the repo root). THE FIX: insert the repo root on
# sys.path. NOTE: with the import fixed, the smoke run against a fresh PostgreSQL 16 database stops at
# migration 073 (column "request_id" does not exist) — a real, pre-existing migration defect recorded
# in docs/release-history/release-notes/RELEASE_NOTES_V90GX.md. NOT touched: migration logic.
from __future__ import annotations
import os
import sys
from pathlib import Path
# [Session CS2] FIX — see header. Make `app` importable when run as `python scripts/migration_smoke.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, text
from app.migrations import migrate, load_migrations

url = os.getenv('DATABASE_URL')
if not url:
    raise SystemExit('DATABASE_URL is required for migration smoke test')
engine = create_engine(url, future=True)
# [Session CS2] create the application runtime schema first, as the API container does (see app/migrate_cli.py).
os.environ.setdefault('DATABASE_URL', url)
import app.__main__  # noqa: E402,F401
root = Path(__file__).resolve().parents[1]
expected_target = load_migrations(root)[-1].version
applied = migrate(engine, root)
with engine.connect() as conn:
    row = conn.execute(text('SELECT max(version) AS version FROM schema_migrations')).mappings().one()
print(f'migration smoke passed: applied_now={list(applied)}, target={row["version"]}')
if int(row['version']) != expected_target:
    raise SystemExit(f'migration smoke did not reach schema {expected_target}')
