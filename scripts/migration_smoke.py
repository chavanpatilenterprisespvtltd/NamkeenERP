from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from app.migrations import migrate, load_migrations

url = os.getenv('DATABASE_URL')
if not url:
    raise SystemExit('DATABASE_URL is required for migration smoke test')
engine = create_engine(url, future=True)
root = Path(__file__).resolve().parents[1]
expected_target = load_migrations(root)[-1].version
applied = migrate(engine, root)
with engine.connect() as conn:
    row = conn.execute(text('SELECT max(version) AS version FROM schema_migrations')).mappings().one()
print(f'migration smoke passed: applied_now={list(applied)}, target={row["version"]}')
if int(row['version']) != expected_target:
    raise SystemExit(f'migration smoke did not reach schema {expected_target}')
