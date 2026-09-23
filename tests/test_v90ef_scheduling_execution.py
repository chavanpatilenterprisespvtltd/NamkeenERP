import json
import re
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app, engine
from app.v90bf_security_hardening import ensure_security_schema
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]

def auth():
    from app.auth import make_access_token, UserRecord
    return {'Authorization': 'Bearer ' + make_access_token(UserRecord('erpadmin', 'erpadmin', 'super_admin'))}

def apply_sql(raw, path):
    sql = (ROOT / 'migrations' / path).read_text()
    for stmt in [x.strip() for x in sql.split(';') if x.strip()]:
        raw.execute(stmt)

def test_v90ef_artifacts_and_registration():
    assert (ROOT/'app/v90ef_scheduling_execution.py').exists()
    sql=(ROOT/'migrations/207_v90ef_scheduling_execution.sql').read_text()
    py=(ROOT/'app/v90ef_scheduling_execution.py').read_text()
    main=(ROOT/'app/__main__.py').read_text()
    for table in ['manufacturing_scenario_execution','manufacturing_scenario_execution_line','manufacturing_scenario_overtime','manufacturing_scenario_execution_close']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table, sql)
    for route in ['/v90ef/manufacturing/scenario-executions','/v90ef/manufacturing/scenario-executions/{execution_id}/approve','/v90ef/manufacturing/scenario-executions/{execution_id}/execute','/v90ef/manufacturing/scenario-executions/periods/close']:
        assert route in py
    assert 'v90ef_scheduling_execution' in main
    assert 'register_v90ef_routes(app, engine)' in main

def test_v90ef_live_execution_flow():
    ensure_security_schema(engine)
    c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
    raw=engine.raw_connection().connection
    for m in ('203_v90eb_workforce_bottleneck_analytics.sql','204_v90ec_factory_bottleneck_optimization.sql','205_v90ed_factory_bottleneck_scenarios.sql','206_v90ee_factory_scenario_handoff.sql','207_v90ef_scheduling_execution.sql'):
        apply_sql(raw, m)
    # Ensure the scheduling table used by the execution is present.
    raw.execute('''CREATE TABLE IF NOT EXISTS manufacturing_work_center(work_center_id TEXT PRIMARY KEY,organization_id TEXT,entity_id TEXT,code TEXT,name TEXT,capacity_per_shift NUMERIC DEFAULT 0,shifts_per_day NUMERIC DEFAULT 1,efficiency_pct NUMERIC DEFAULT 100,active BOOLEAN DEFAULT TRUE)''')
    raw.execute('''CREATE TABLE IF NOT EXISTS manufacturing_schedule(schedule_id TEXT PRIMARY KEY,organization_id TEXT,entity_id TEXT,production_order_id TEXT,product_id TEXT,work_center_id TEXT,schedule_date DATE,shift_code TEXT,planned_qty NUMERIC DEFAULT 0,required_hours NUMERIC DEFAULT 0,status TEXT DEFAULT 'PLANNED',approved_by TEXT,approved_at TIMESTAMP,created_by TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    from sqlalchemy import text as sqltext
    with engine.begin() as db:
        wc=str(uuid.uuid4())
        db.execute(sqltext("INSERT INTO manufacturing_work_center(work_center_id,organization_id,entity_id,code,name,capacity_per_shift,shifts_per_day,efficiency_pct,active) VALUES(:w,:o,:e,'WC1','Line 1',8,1,100,1)"),{'w':wc,'o':o,'e':e})
        sched=str(uuid.uuid4())
        db.execute(sqltext("INSERT INTO manufacturing_schedule(schedule_id,organization_id,entity_id,production_order_id,product_id,work_center_id,schedule_date,shift_code,planned_qty,required_hours,status,created_by) VALUES(:s,:o,:e,:po,:p,:w,'2026-09-01','A',100,8,'PLANNED','erpadmin')"),{'s':sched,'o':o,'e':e,'po':str(uuid.uuid4()),'p':str(uuid.uuid4()),'w':wc})
        scenario=str(uuid.uuid4())
        db.execute(sqltext("INSERT INTO hr_factory_bottleneck_scenario(scenario_id,organization_id,entity_id,period_start,period_end,scenario_name,status,created_by) VALUES(:s,:o,:e,'2026-09-01','2026-09-01','Reduce Load','APPROVED','erpadmin')"),{'s':scenario,'o':o,'e':e})
        result=str(uuid.uuid4())
        db.execute(sqltext("INSERT INTO hr_factory_bottleneck_scenario_result(result_id,scenario_id,work_center_id,schedule_reduction_hours,labour_reallocation_hours,overtime_hours,oee_gain_pct,scenario_load_pct,overtime_required_hours,status) VALUES(:r,:s,:w,2,0,1,0,75,0,'LOW')"),{'r':result,'s':scenario,'w':wc})
        approval=str(uuid.uuid4())
        comparison=str(uuid.uuid4())
        # approval record is enough for the handoff endpoint
        db.execute(sqltext("INSERT INTO hr_factory_bottleneck_scenario_comparison(comparison_id,organization_id,entity_id,period_start,period_end,scenario_count,status,created_by) VALUES(:c,:o,:e,'2026-09-01','2026-09-01',1,'APPROVED','erpadmin')"),{'c':comparison,'o':o,'e':e})
        db.execute(sqltext("INSERT INTO hr_factory_bottleneck_scenario_approval(approval_id,comparison_id,scenario_id,organization_id,entity_id,period_start,period_end,decision,remarks,approved_by) VALUES(:a,:c,:s,:o,:e,'2026-09-01','2026-09-01','APPROVED','ok','erpadmin')"),{'a':approval,'c':comparison,'s':scenario,'o':o,'e':e})
    hand=c.post(f'/v90ee/factory-bottleneck/scenarios/{scenario}/handoff',json={'notes':'ready'},headers=h)
    assert hand.status_code==200, hand.text
    ex=c.post('/v90ef/manufacturing/scenario-executions',json={'handoff_id':hand.json()['handoff_id']},headers=h)
    assert ex.status_code==200, ex.text
    execution_id=ex.json()['execution_id']
    ap=c.post(f'/v90ef/manufacturing/scenario-executions/{execution_id}/approve',json={'remarks':'approved'},headers=h)
    assert ap.status_code==200, ap.text
    run=c.post(f'/v90ef/manufacturing/scenario-executions/{execution_id}/execute',headers=h)
    assert run.status_code==200, run.text
    detail=c.get(f'/v90ef/manufacturing/scenario-executions/{execution_id}',headers=h)
    assert detail.status_code==200 and detail.json()['execution']['status']=='EXECUTED'
    row=engine.connect().execute(sqltext('SELECT planned_qty,required_hours FROM manufacturing_schedule WHERE schedule_id=:s'),{'s':sched}).one()
    assert float(row[0]) < 100 and float(row[1]) < 8
