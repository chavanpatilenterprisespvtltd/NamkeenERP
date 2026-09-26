# FILE PATH: app/business_date.py
# ─── Business Date Helpers v1.0 (Session CS2 — record yesterday's production today, with a back-date limit) ─
#
# [Session CS2] FEATURE — PRODUCTION BATCHES AND MACHINE RUNS HAD NO BUSINESS DATE.
# Confirmed this session by reading app/v90r_production_execution.py (production_batch: created_at,
# start_at, end_at only) and app/v90db_machine_oee.py (manufacturing_machine_run: created_at only; OEE
# periods filtered on DATE(created_at)). A night-shift batch entered next morning was dated wrongly.
# (Labour allocation and attendance already carry work_date — not changed.)
# THE FIX: helpers used by those two modules:
#   - ensure_column(): adds a nullable column when missing (SQLite + PostgreSQL), idempotent;
#   - parse_business_date(): YYYY-MM-DD, never in the future, and not older than
#     BUSINESS_DATE_MAX_BACKDATE_DAYS (default 7) so old periods cannot be silently changed.
# NOT touched: any existing column or stored value; rows without a business date fall back to created_at.
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_column(engine: Engine, table: str, column: str, ddl_type: str) -> None:
    cols = {c['name'] for c in inspect(engine).get_columns(table)}
    if column not in cols:
        with engine.begin() as c:
            c.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}'))


def parse_business_date(value, today: date | None = None) -> str | None:
    if value in (None, ''):
        return None
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise HTTPException(422, 'business_date must be YYYY-MM-DD') from exc
    today = today or datetime.now(timezone.utc).date()
    if d > today + timedelta(days=1):  # +1 day tolerance for IST vs UTC around midnight
        raise HTTPException(422, 'business_date cannot be in the future')
    max_back = int(os.getenv('BUSINESS_DATE_MAX_BACKDATE_DAYS', '7'))
    if d < today - timedelta(days=max_back):
        raise HTTPException(422, f'business_date is older than {max_back} days; ask an administrator (BUSINESS_DATE_MAX_BACKDATE_DAYS)')
    return d.isoformat()
