#!/usr/bin/env python3
from __future__ import annotations
import argparse
from app.db import create_db_engine
from app.v90bg_backup_restore import restore_postgres_backup, verify_backup_file

p=argparse.ArgumentParser(description='Safely verify/restore a PostgreSQL custom-format Namkeen ERP backup.')
p.add_argument('backup')
p.add_argument('--verify-only', action='store_true')
p.add_argument('--execute-destructive-restore', action='store_true', help='Explicitly allow pg_restore --clean')
args=p.parse_args()
print(verify_backup_file(args.backup))
if not args.verify_only:
    if not args.execute_destructive_restore:
        raise SystemExit('Refusing destructive restore. Use --execute-destructive-restore explicitly after taking a verified backup.')
    print(restore_postgres_backup(create_db_engine(), args.backup, allow_destructive=True))
