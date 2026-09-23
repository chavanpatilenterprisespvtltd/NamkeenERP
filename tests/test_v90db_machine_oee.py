# FILE PATH: tests/test_v90db_machine_oee.py
# ─── Machine OEE Tests v1.1 (Session CS1 — hardcoded period date replaced with today's date) ─

# [Session CS1] FIX — TEST FAILS ONCE THE CALENDAR MOVES PAST THE HARDCODED DATE.
# Confirmed live this session via a scratch rerun: with the original hardcoded
# 'period_start'/'period_end' of 2026-09-08 and pytest run on 2026-09-21, the
# assertion failed with availability_pct == 0.0 instead of 75.0. Copying this
# same test into a scratch file with the date changed to today (2026-09-21)
# made it pass (availability_pct == 75.0) with no other change.
#
# ROOT CAUSE: app/v90db_machine_oee.py aggregates
# 'WHERE ... DATE(created_at) BETWEEN :s AND :d', and manufacturing_machine_run
# rows are stored with created_at DEFAULT CURRENT_TIMESTAMP (today, at insert
# time). The test posted the run today but queried a fixed calendar date, so
# the WHERE clause matched zero rows once "today" no longer equalled the
# hardcoded string.
#
# THE FIX: period_start/period_end now come from date.today().isoformat(),
# computed when the test runs, so the query window always matches the day the
# row was actually inserted. No change to app/v90db_machine_oee.py, to the
# OEE calculation formula, or to any other test in this file.
# Follow-up: the underlying table has no user-supplied business date for a
# machine run (it always uses insertion time) — worth a product decision
# during UAT on whether a supervisor should be able to log a prior day's run.

import json, uuid
from datetime import date
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app
ROOT=Path(__file__).resolve().parents[1]
def auth():
 from app.auth import make_access_token,UserRecord
 return {'Authorization':'Bearer '+make_access_token(UserRecord('erpadmin','erpadmin','super_admin'))}
def test_release_ui():
 d=json.loads((ROOT/'config/release_manifest.json').read_text()); assert d['release'].startswith('v90.') and d['schema_target']>=179
 assert TestClient(app).get('/ui/manufacturing-machine-oee').status_code==200
def test_machine_oee_calculation():
 c=TestClient(app); h=auth(); o,e,w=[str(uuid.uuid4()) for _ in range(3)]
 today=date.today().isoformat()  # [Session CS1] FIX — see file header. Was a hardcoded '2026-09-08'.
 assert c.post('/v90db/machines/reasons',json={'organization_id':o,'entity_id':e,'reason_code':'BREAKDOWN','reason_name':'Breakdown'},headers=h).status_code==200
 assert c.post('/v90db/machines/status',json={'organization_id':o,'entity_id':e,'work_center_id':w,'status_code':'DOWN','reason_code':'BREAKDOWN','duration_minutes':30},headers=h).status_code==200
 assert c.post('/v90db/machines/runs',json={'organization_id':o,'entity_id':e,'work_center_id':w,'planned_qty':100,'good_qty':90,'reject_qty':10,'ideal_cycle_minutes':1,'planned_minutes':120,'actual_run_minutes':90,'downtime_minutes':30},headers=h).status_code==200
 r=c.post('/v90db/machines/oee/calculate',json={'organization_id':o,'entity_id':e,'work_center_id':w,'period_start':today,'period_end':today},headers=h)
 assert r.status_code==200 and round(r.json()['availability_pct'],2)==75.0 and round(r.json()['performance_pct'],2)==100.0 and round(r.json()['quality_pct'],2)==90.0 and round(r.json()['oee_pct'],2)==67.5
