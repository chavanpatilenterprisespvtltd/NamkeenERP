# FILE PATH: tests/test_v90gp_manufacturing_workforce_integration.py
# ─── Manufacturing Workforce Integration Tests v1.1 (Session CS1 — hardcoded work_date/query-window replaced with today's date) ─

# [Session CS1] FIX — TEST FAILS ONCE THE CALENDAR MOVES PAST THE HARDCODED DATE.
# Confirmed live this session via a scratch rerun: with the original hardcoded
# '2026-09-12' (both the labour-capture work_date literal embedded in the SQL
# text and the dashboard query's from_date/to_date), pytest run on 2026-09-21
# failed with batch_count == 0 instead of 1. Copying this same test into a
# scratch file with the date changed to today (2026-09-21) made it pass
# (batch_count == 1) with no other change.
#
# ROOT CAUSE: app/v90gp_manufacturing_workforce_integration.py's dashboard
# query filters production_batch with 'DATE(created_at) BETWEEN :fd AND :td',
# and production_batch/hr_production_labour_capture rows are stored with
# created_at DEFAULT CURRENT_TIMESTAMP (today, at insert time), independent of
# the hr_production_labour_capture.work_date value this test hardcoded. The
# test inserted today but queried a fixed calendar window, so once "today"
# stopped being 2026-09-12 the batch fell outside the window.
#
# THE FIX: env()'s labour-capture insert now binds work_date to a real
# parameter (:wd) instead of a literal '2026-09-12' baked into the SQL text,
# and test_dashboard_and_snapshot's from_date/to_date now come from
# date.today().isoformat(), computed when the test runs. No change to
# app/v90gp_manufacturing_workforce_integration.py or to test_action_and_rbac
# (which does not depend on the date window).
# Follow-up: same as the OEE test — worth a product decision during UAT on
# whether production_batch should carry its own business date separate from
# created_at, so a supervisor can log yesterday's run today.

from uuid import uuid4
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.auth import make_access_token, UserRecord
from app.identity import create_user

def env(role='manager'):
    uid=str(uuid4()); uname='gp_'+uid[:8]; create_user(engine,uid,uname,'pw','GP Tester',role)
    c=TestClient(app,headers={'Authorization':'Bearer '+make_access_token(UserRecord(uid,uname,'GP Tester',role))})
    org,e,l,b=map(str,[uuid4(),uuid4(),uuid4(),uuid4()])
    today=date.today().isoformat()  # [Session CS1] FIX — see file header. Was a hardcoded '2026-09-12'.
    with engine.begin() as db:
        db.execute(text("INSERT INTO erp_entities(entity_id,entity_code,entity_name,entity_type,active) VALUES(:e,:c,'GP','legal_entity',1)"),{'e':e,'c':'GP'+e[:5]})
        db.execute(text("INSERT INTO erp_locations(location_id,entity_id,location_code,location_name,location_type,active) VALUES(:l,:e,:c,'GP','site',1)"),{'l':l,'e':e,'c':'GPL'+l[:5]})
        db.execute(text("INSERT INTO erp_entity_user_access(user_id,entity_id) VALUES(:u,:e)"),{'u':uid,'e':e})
        db.execute(text("INSERT INTO erp_location_user_access(user_id,location_id) VALUES(:u,:l)"),{'u':uid,'l':l})
        db.execute(text("INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,created_by) VALUES(:b,:o,:org,:e,:l,'GP-B1',:p,100,'KG','COMPLETED',:u)"),{'b':b,'o':str(uuid4()),'org':org,'e':e,'l':l,'p':str(uuid4()),'u':uid})
        # [Session CS1] FIX — work_date is now bound as :wd instead of a literal '2026-09-12' in the SQL text.
        db.execute(text("INSERT INTO hr_production_labour_capture(capture_id,organization_id,entity_id,run_id,production_batch_id,work_date,labour_hours,labour_cost,output_qty,output_uom,downtime_hours,overtime_hours,created_by) VALUES(:i,:o,:e,:r,:b,:wd,10,500,80,'KG',2,1,:u)"),{'i':str(uuid4()),'o':org,'e':e,'r':str(uuid4()),'b':b,'wd':today,'u':uid})
    return c,org,e,l,b

def test_dashboard_and_snapshot():
    c,o,e,l,b=env(); today=date.today().isoformat()  # [Session CS1] FIX — was a hardcoded '2026-09-12'.
    q={'organization_id':o,'entity_id':e,'location_id':l,'from_date':today,'to_date':today}
    r=c.get('/v90gp/manufacturing-workforce',params=q); assert r.status_code==200,r.text; d=r.json(); assert d['batch_count']==1 and d['completed_batch_count']==1 and d['labour_hours']==10.0 and d['productive_hours']==8.0 and d['workforce_coverage_pct']==100.0
    r=c.post('/v90gp/manufacturing-workforce/snapshots',json=q); assert r.status_code==200 and r.json()['snapshot_id']

def test_action_and_rbac():
    c,o,e,l,b=env(); q={'organization_id':o,'entity_id':e,'location_id':l,'batch_id':b,'action_type':'CAPTURE_RECONCILIATION','priority':'HIGH','reason':'Review labour capture'}
    r=c.post('/v90gp/manufacturing-workforce/actions',json=q); assert r.status_code==200
    r=c.get('/v90gp/manufacturing-workforce/actions',params={'organization_id':o,'entity_id':e,'location_id':l}); assert r.status_code==200 and r.json()['actions']
    s,_,ee,ll,_=env('salesperson'); r=s.get('/v90gp/manufacturing-workforce',params={'organization_id':str(uuid4()),'entity_id':ee,'location_id':ll}); assert r.status_code==403
