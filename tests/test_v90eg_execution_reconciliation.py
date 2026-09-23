import re
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.__main__ import app, engine
from app.v90bf_security_hardening import ensure_security_schema

ROOT = Path(__file__).resolve().parents[1]

def auth():
    from app.auth import make_access_token, UserRecord
    return {'Authorization': 'Bearer ' + make_access_token(UserRecord('erpadmin', 'erpadmin', 'super_admin'))}

def apply_sql(path):
    raw = engine.raw_connection().connection
    for stmt in [x.strip() for x in (ROOT/'migrations'/path).read_text().split(';') if x.strip()]:
        raw.execute(stmt)

def test_v90eg_artifacts_and_registration():
    sql=(ROOT/'migrations/208_v90eg_execution_reconciliation.sql').read_text()
    py=(ROOT/'app/v90eg_execution_reconciliation.py').read_text()
    main=(ROOT/'app/__main__.py').read_text()
    for t in ['manufacturing_scenario_execution_reconciliation','manufacturing_scenario_execution_reconciliation_line','manufacturing_scenario_execution_reconciliation_exception']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+t, sql)
    for r in ['/v90eg/manufacturing/scenario-executions/{execution_id}/reconcile','/v90eg/manufacturing/scenario-execution-reconciliations/{reconciliation_id}','/v90eg/manufacturing/scenario-execution-reconciliations/{reconciliation_id}/close']:
        assert r in py
    assert 'register_v90eg_routes(app, engine)' in main

def test_v90eg_reconcile_executed_schedule():
    ensure_security_schema(engine)
    apply_sql('203_v90eb_workforce_bottleneck_analytics.sql')
    apply_sql('204_v90ec_factory_bottleneck_optimization.sql')
    apply_sql('205_v90ed_factory_bottleneck_scenarios.sql')
    apply_sql('206_v90ee_factory_scenario_handoff.sql')
    apply_sql('207_v90ef_scheduling_execution.sql')
    apply_sql('208_v90eg_execution_reconciliation.sql')
    raw=engine.raw_connection().connection
    raw.execute('''CREATE TABLE IF NOT EXISTS manufacturing_schedule(schedule_id TEXT PRIMARY KEY,organization_id TEXT,entity_id TEXT,planned_qty NUMERIC DEFAULT 0,required_hours NUMERIC DEFAULT 0,status TEXT DEFAULT 'PLANNED')''')
    o,e='o-'+str(uuid.uuid4()),'e-'+str(uuid.uuid4())
    execution=str(uuid.uuid4()); sid=str(uuid.uuid4())
    raw.execute("INSERT INTO manufacturing_schedule(schedule_id,organization_id,entity_id,production_order_id,product_id,work_center_id,schedule_date,shift_code,planned_qty,required_hours,status,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (sid,o,e,str(uuid.uuid4()),str(uuid.uuid4()),'wc1','2026-09-01','A',90,7,'PLANNED','erpadmin'))
    raw.execute("INSERT INTO manufacturing_scenario_execution(execution_id,handoff_id,organization_id,entity_id,period_start,period_end,status,proposal_line_count,notes,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)", (execution,str(uuid.uuid4()),o,e,'2026-09-01','2026-09-01','EXECUTED',1,'','erpadmin'))
    raw.execute("INSERT INTO manufacturing_scenario_execution_line(line_id,execution_id,work_center_id,schedule_id,original_planned_qty,original_required_hours,proposed_planned_qty,proposed_required_hours,overtime_hours,status) VALUES(?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()),execution,'wc1',sid,100,8,90,7,1,'EXECUTED'))
    raw.execute("INSERT INTO manufacturing_scenario_overtime(overtime_id,execution_id,work_center_id,overtime_hours,status) VALUES(?,?,?,?,?)", (str(uuid.uuid4()),execution,'wc1',1,'EXECUTED'))
    raw.commit()
    c=TestClient(app); h=auth()
    r=c.post(f'/v90eg/manufacturing/scenario-executions/{execution}/reconcile',json={'qty_tolerance':0.1,'hours_tolerance':0.1,'overtime_tolerance':0.1},headers=h)
    assert r.status_code==200, r.text
    data=r.json(); assert data['status']=='ON_TRACK'; assert data['line_count']==1
    rid=data['reconciliation_id']
    detail=c.get(f'/v90eg/manufacturing/scenario-execution-reconciliations/{rid}',headers=h)
    assert detail.status_code==200 and len(detail.json()['lines'])==1
    closed=c.post(f'/v90eg/manufacturing/scenario-execution-reconciliations/{rid}/close',headers=h)
    assert closed.status_code==200 and closed.json()['status']=='CLOSED'
