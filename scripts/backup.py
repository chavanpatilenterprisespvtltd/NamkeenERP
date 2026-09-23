#!/usr/bin/env python3
from __future__ import annotations
import argparse
from app.db import create_db_engine
from app.v90bg_backup_restore import create_postgres_backup, write_backup_report

p=argparse.ArgumentParser(description='Create and verify a PostgreSQL custom-format Namkeen ERP backup.')
p.add_argument('output')
p.add_argument('--report', help='Optional JSON report path')
args=p.parse_args()
result=create_postgres_backup(create_db_engine(), args.output)
if args.report:
    write_backup_report(args.report, result)
print(result)
