# FILE PATH: app/migrate_cli.py
# ─── Migration CLI v1.0 (Session CS2 — `python -m app.migrate_cli` applies ordered, checksum-verified migrations) ─
#
# [Session CS2] FEATURE — NO COMMAND EXISTED TO APPLY migrations/ INSIDE THE CONTAINER.
# Confirmed this session: app/migrations.py has migrate() but no entry point, the API image did not
# contain migrations/ or config/, and docker/entrypoint.sh was never used. Deployments therefore relied
# on each module's runtime CREATE TABLE IF NOT EXISTS only.
# THE FIX: thin CLI around app.migrations.migrate(); used by docker/entrypoint.sh when
# RUN_MIGRATIONS=true and by bootstrap/bootstrap.py. Uses the same DATABASE_URL(_FILE) resolution as
# the app (app.db → runtime_security). PostgreSQL only, exactly as app.migrations enforces.
# Runs the application runtime schema first (import app.__main__) unless --no-runtime-schema: confirmed
# this session that on an empty PostgreSQL database migrations 080+ need erp_users/erp_permissions,
# which only the runtime schema creates.
# NOT touched: migration files.
from __future__ import annotations

import argparse
import json

from .db import create_db_engine
from .migrations import load_migrations, migrate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply Namkeen ERP migrations (PostgreSQL)")
    ap.add_argument("--target", type=int, default=None, help="highest migration version to apply")
    ap.add_argument("--verify-only", action="store_true", help="validate manifest/checksums without connecting")
    ap.add_argument("--no-runtime-schema", action="store_true", help="do not create the application runtime schema first")
    args = ap.parse_args(argv)
    migrations = load_migrations()
    if args.verify_only:
        print(json.dumps({"migration_count": len(migrations), "latest": migrations[-1].version}))
        return 0
    if not args.no_runtime_schema:
        # Several migrations reference tables (erp_users, erp_permissions, …) that the application creates at
        # start-up; importing the app creates them first, exactly as a running API container would.
        from .__main__ import engine
    else:
        engine = create_db_engine()
    applied = migrate(engine, target=args.target)
    print(json.dumps({"applied_now": list(applied), "latest": migrations[-1].version}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
