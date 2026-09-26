# FILE PATH: app/worker.py
# ─── Background Worker v1.0 (Session CS2 — sends the notification outbox and queues daily alerts) ─
#
# [Session CS2] FEATURE — THE WORKER CONTAINER DID NOTHING.
# Confirmed this session by reading the previous version: main() was `while True: time.sleep(30)`.
# THE FIX: every WORKER_POLL_SECONDS (default 30) the worker sends queued notifications
# (app/v90gx_notifications.process_outbox) and once per UTC day queues the daily alerts (FSSAI licence
# expiry, open HIGH complaints, oil discard). It creates only the tables it needs, uses the same
# DATABASE_URL(_FILE) and production-safety rules as the API, logs each cycle, and never exits on a
# single failed cycle. `python -m app.worker --once` runs one cycle (for cron or testing).
# NOT touched: the API process; Tally sync and other queues keep their existing manual endpoints.
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone

log = logging.getLogger('namkeen.worker')


def run_cycle(engine, state: dict) -> dict:
    from .v90gx_notifications import enqueue_daily_alerts, process_outbox
    today = datetime.now(timezone.utc).date().isoformat()
    alerts = 0
    if state.get('alerts_day') != today:
        try:
            alerts = enqueue_daily_alerts(engine)
            state['alerts_day'] = today
        except Exception as ex:  # tables of optional modules may not exist yet on a brand-new database
            log.warning('daily alerts skipped: %s', ex)
    result = {'alerts_queued': alerts, **process_outbox(engine)}
    log.info('worker cycle %s', result)
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description='Namkeen ERP background worker')
    ap.add_argument('--once', action='store_true')
    a = ap.parse_args(argv)
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'), format='%(asctime)s %(levelname)s %(name)s %(message)s')
    from .runtime_security import validate_runtime_configuration
    validate_runtime_configuration()
    from .db import create_db_engine
    from .v90gx_notifications import ensure_v90gx_notification_schema
    from .identity import ensure_identity_schema
    engine = create_db_engine()
    ensure_identity_schema(engine)  # permissions tables used by the outbox schema bootstrap
    ensure_v90gx_notification_schema(engine)
    state: dict = {}
    while True:
        try:
            run_cycle(engine, state)
        except Exception:
            log.exception('worker cycle failed')
        if a.once:
            return
        time.sleep(int(os.getenv('WORKER_POLL_SECONDS', '30')))


if __name__ == '__main__':
    main()
