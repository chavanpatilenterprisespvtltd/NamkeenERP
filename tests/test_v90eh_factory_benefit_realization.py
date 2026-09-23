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

def apply_sql(raw, name):
    for stmt in [x.strip() for x in (ROOT/'migrations'/name).read_text().split(';') if x.strip()]:
        raw.execute(stmt)

def test_v90eh_artifacts_and_registration():
    sql=(ROOT/'migrations/209_v90eh_factory_benefit_realization.sql').read_text()
    py=(ROOT/'app/v90eh_factory_benefit_realization.py').read_text()
    main=(ROOT/'app/__main__.py').read_text()
    for t in ['hr_factory_execution_benefit_realization','hr_factory_execution_benefit_realization_line','hr_factory_execution_benefit_close']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+t, sql)
    for r in ['/v90eh/factory-bottleneck/benefit-realizations','/v90eh/factory-bottleneck/benefit-realizations/{realization_id}','/v90eh/factory-bottleneck/benefit-realizations/{realization_id}/close']:
        assert r in py
    assert 'register_v90eh_routes(app, engine)' in main

def test_v90eh_live_benefit_flow():
    ensure_security_schema(engine)
    raw=engine.raw_connection().connection
    for m in ('203_v90eb_workforce_bottleneck_analytics.sql','204_v90ec_factory_bottleneck_optimization.sql','205_v90ed_factory_bottleneck_scenarios.sql','206_v90ee_factory_scenario_handoff.sql','207_v90ef_scheduling_execution.sql','208_v90eg_execution_reconciliation.sql','209_v90eh_factory_benefit_realization.sql'):
        apply_sql(raw,m)
    o,e=str(uuid.uuid4()),str(uuid.uuid4()); wc='wc1'; sid=str(uuid.uuid4()); execution=str(uuid.uuid4()); recon=str(uuid.uuid4()); scenario=str(uuid.uuid4()); handoff=str(uuid.uuid4());
    raw.execute("CREATE TABLE IF NOT EXISTS manufacturing_workforce_bottleneck_snapshot(snapshot_id TEXT PRIMARY KEY,organization_id TEXT,entity_id TEXT,period_start DATE,period_end DATE,work_center_id TEXT,department_id TEXT,oee_pct NUMERIC,labour_efficiency_pct NUMERIC,combined_efficiency_score NUMERIC,rank_no INTEGER)")
    raw.execute("CREATE TABLE IF NOT EXISTS manufacturing_schedule(schedule_id TEXT PRIMARY KEY,organization_id TEXT,entity_id TEXT,production_order_id TEXT,product_id TEXT,work_center_id TEXT,schedule_date DATE,shift_code TEXT,planned_qty NUMERIC DEFAULT 0,required_hours NUMERIC DEFAULT 0,status TEXT DEFAULT 'PLANNED',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    raw.execute("CREATE TABLE IF NOT EXISTS hr_workforce_bottleneck_snapshot(snapshot_id TEXT PRIMARY KEY,organization_id TEXT,entity_id TEXT,period_start DATE,period_end DATE,work_center_id TEXT,department_id TEXT,oee_pct NUMERIC,labour_efficiency_pct NUMERIC,combined_efficiency_score NUMERIC,rank_no INTEGER)")
    raw.execute("""CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_optimization_snapshot(snapshot_id TEXT PRIMARY KEY,organization_id TEXT,entity_id TEXT,period_start DATE,period_end DATE,work_center_id TEXT,department_id TEXT,machine_capacity_hours NUMERIC,scheduled_hours NUMERIC,machine_load_pct NUMERIC,labour_required_hours NUMERIC,labour_available_hours NUMERIC,labour_load_pct NUMERIC,combined_load_pct NUMERIC,capacity_gap_hours NUMERIC,labour_gap_hours NUMERIC,overtime_required_hours NUMERIC,oee_pct NUMERIC,labour_efficiency_pct NUMERIC,bottleneck_score NUMERIC,constraint_type TEXT,status TEXT,recommendation TEXT,source_bottleneck_snapshot_id TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    raw.commit()
    raw.execute("INSERT INTO hr_factory_bottleneck_scenario(scenario_id,organization_id,entity_id,period_start,period_end,scenario_name,status,created_by) VALUES(?,?,?,?,?,?,?,?)",(scenario,o,e,'2026-09-01','2026-09-01','Scenario','APPROVED','erpadmin'))
    raw.execute("INSERT INTO hr_factory_bottleneck_scenario_result(result_id,scenario_id,work_center_id,baseline_load_pct,scenario_load_pct,baseline_oee_pct,scenario_oee_pct,baseline_labour_gap_hours,scenario_labour_gap_hours,schedule_reduction_hours,labour_reallocation_hours,overtime_hours,oee_gain_pct,bottleneck_relief_pct,capacity_gap_hours,overtime_required_hours,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),scenario,wc,120,90,70,75,4,2,2,2,1,5,30,4,2,'HIGH'))
    raw.execute("INSERT INTO hr_factory_bottleneck_scenario_handoff(handoff_id,scenario_id,organization_id,entity_id,period_start,period_end,status,created_by) VALUES(?,?,?,?,?,?,?,?)",(handoff,scenario,o,e,'2026-09-01','2026-09-01','READY','erpadmin'))
    raw.execute("INSERT INTO manufacturing_scenario_execution(execution_id,handoff_id,organization_id,entity_id,period_start,period_end,status,proposal_line_count,created_by) VALUES(?,?,?,?,?,?,?,?,?)",(execution,handoff,o,e,'2026-09-01','2026-09-01','EXECUTED',1,'erpadmin'))
    raw.execute("INSERT INTO manufacturing_scenario_execution_reconciliation(reconciliation_id,execution_id,organization_id,entity_id,period_start,period_end,status,original_qty,planned_qty,actual_qty,original_hours,planned_hours,actual_hours,planned_overtime_hours,actual_overtime_hours,qty_variance,hours_variance,overtime_variance,reconciled_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(recon,execution,o,e,'2026-09-01','2026-09-01','CLOSED',100,90,90,8,6,6,1,1,0,0,0,'erpadmin'))
    raw.execute("INSERT INTO manufacturing_scenario_execution_reconciliation_line(reconciliation_line_id,reconciliation_id,work_center_id,schedule_id,planned_qty,actual_qty,qty_variance,planned_hours,actual_hours,hours_variance,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),recon,wc,sid,90,90,0,6,6,0,'ON_TRACK'))
    raw.commit()
    c=TestClient(app); h=auth()
    r=c.post('/v90eh/factory-bottleneck/benefit-realizations',json={'reconciliation_id':recon},headers=h)
    assert r.status_code==200, r.text
    data=r.json(); assert data['status']=='REALIZED'; assert data['benefit_score_pct'] >= 60
    rid=data['realization_id']
    d=c.get(f'/v90eh/factory-bottleneck/benefit-realizations/{rid}',headers=h)
    assert d.status_code==200 and len(d.json()['lines'])==1
    cl=c.post(f'/v90eh/factory-bottleneck/benefit-realizations/{rid}/close',headers=h)
    assert cl.status_code==200 and cl.json()['closure_status']=='CLOSED'
