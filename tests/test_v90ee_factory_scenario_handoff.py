import json
import re
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.__main__ import app

ROOT = Path(__file__).resolve().parents[1]

def auth():
    from app.auth import make_access_token, UserRecord
    return {'Authorization': 'Bearer ' + make_access_token(UserRecord('erpadmin', 'erpadmin', 'super_admin'))}

def test_v90ee_artifacts_registration_and_contracts():
    assert (ROOT/'app/v90ee_factory_scenario_handoff.py').exists()
    sql=(ROOT/'migrations/206_v90ee_factory_scenario_handoff.sql').read_text()
    py=(ROOT/'app/v90ee_factory_scenario_handoff.py').read_text()
    main=(ROOT/'app/__main__.py').read_text()
    for table in ['hr_factory_bottleneck_scenario_comparison','hr_factory_bottleneck_scenario_comparison_line','hr_factory_bottleneck_scenario_approval','hr_factory_bottleneck_scenario_handoff','hr_factory_bottleneck_scenario_handoff_action']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table, sql)
    for route in ['/v90ee/factory-bottleneck/scenarios/compare','/v90ee/factory-bottleneck/scenarios/comparisons/{comparison_id}','/v90ee/factory-bottleneck/scenarios/comparisons/{comparison_id}/approve','/v90ee/factory-bottleneck/scenarios/{scenario_id}/handoff','/v90ee/factory-bottleneck/handoffs']:
        assert route in py
    assert 'v90ee_factory_scenario_handoff' in main
    assert 'register_v90ee_routes(app, engine)' in main

def test_v90ee_live_api_compare_approve_handoff():
    c=TestClient(app); h=auth(); o,e=str(uuid.uuid4()),str(uuid.uuid4())
    # Seed the V90.ed baseline and simulate two scenarios.
    from app.__main__ import engine
    from sqlalchemy import text
    with engine.begin() as db:
        # Runtime app startup does not automatically apply historical migrations, so this API test
        # installs the V90.ed schema it exercises plus the V90.ee schema under test.
        for migration in ('205_v90ed_factory_bottleneck_scenarios.sql', '206_v90ee_factory_scenario_handoff.sql'):
            sql = (ROOT/'migrations'/migration).read_text()
            raw = db.connection.driver_connection
            for stmt in [x.strip() for x in sql.split(';') if x.strip()]:
                raw.execute(stmt)
        wc=str(uuid.uuid4())
        db.execute(text('''CREATE TABLE IF NOT EXISTS hr_factory_bottleneck_optimization_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT, entity_id TEXT, period_start DATE, period_end DATE,
            work_center_id TEXT, department_id TEXT, machine_capacity_hours NUMERIC, scheduled_hours NUMERIC,
            machine_load_pct NUMERIC, labour_required_hours NUMERIC, labour_available_hours NUMERIC,
            labour_load_pct NUMERIC, combined_load_pct NUMERIC, capacity_gap_hours NUMERIC, labour_gap_hours NUMERIC,
            overtime_required_hours NUMERIC, oee_pct NUMERIC, labour_efficiency_pct NUMERIC, bottleneck_score NUMERIC,
            constraint_type TEXT, status TEXT, recommendation TEXT, source_bottleneck_snapshot_id TEXT, created_by TEXT)'''))
        db.execute(text('''INSERT INTO hr_factory_bottleneck_optimization_snapshot(snapshot_id,organization_id,entity_id,period_start,period_end,work_center_id,created_by,machine_capacity_hours,scheduled_hours,machine_load_pct,labour_required_hours,labour_available_hours,labour_load_pct,combined_load_pct,oee_pct,labour_efficiency_pct) VALUES(:id,:o,:e,:s,:d,:w,:created_by,8,10,125,8,8,100,125,70,80) ON CONFLICT(snapshot_id) DO NOTHING'''), {'id':str(uuid.uuid4()),'o':o,'e':e,'s':'2026-09-01','d':'2026-09-07','w':wc,'created_by':'erpadmin'})
    a=c.post('/v90ed/factory-bottleneck/scenarios/simulate',json={'organization_id':o,'entity_id':e,'period_start':'2026-09-01','period_end':'2026-09-07','scenario_name':'OT Relief','overtime_hours':4},headers=h); assert a.status_code==200
    b=c.post('/v90ed/factory-bottleneck/scenarios/simulate',json={'organization_id':o,'entity_id':e,'period_start':'2026-09-01','period_end':'2026-09-07','scenario_name':'OEE Relief','oee_gain_pct':10},headers=h); assert b.status_code==200
    sids=[a.json()['scenario_id'],b.json()['scenario_id']]
    r=c.post('/v90ee/factory-bottleneck/scenarios/compare',json={'organization_id':o,'entity_id':e,'period_start':'2026-09-01','period_end':'2026-09-07','scenario_ids':sids},headers=h); assert r.status_code==200; assert r.json()['recommended_scenario_id'] in sids
    cid=r.json()['comparison_id']; chosen=r.json()['recommended_scenario_id']
    r=c.post(f'/v90ee/factory-bottleneck/scenarios/comparisons/{cid}/approve',json={'scenario_id':chosen,'decision':'APPROVED'},headers=h); assert r.status_code==200
    r=c.post(f'/v90ee/factory-bottleneck/scenarios/{chosen}/handoff',json={'notes':'Approved for scheduling review'},headers=h); assert r.status_code==200
    assert r.json()['status']=='READY'
