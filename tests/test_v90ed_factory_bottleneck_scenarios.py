from pathlib import Path
import re

def test_v90ed_artifacts_and_registration():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'app/v90ed_factory_bottleneck_scenarios.py').exists()
    assert (root / 'migrations/205_v90ed_factory_bottleneck_scenarios.sql').exists()
    assert (root / 'web/factory-bottleneck-scenarios.html').exists()
    main = (root / 'app/__main__.py').read_text()
    assert 'v90ed_factory_bottleneck_scenarios' in main
    assert 'register_v90ed_routes(app, engine)' in main

def test_v90ed_contracts():
    root = Path(__file__).resolve().parents[1]
    py = (root / 'app/v90ed_factory_bottleneck_scenarios.py').read_text()
    sql = (root / 'migrations/205_v90ed_factory_bottleneck_scenarios.sql').read_text()
    for route in [
        '/v90ed/factory-bottleneck/scenarios/simulate',
        '/v90ed/factory-bottleneck/scenarios',
        '/v90ed/factory-bottleneck/scenarios/{scenario_id}',
        '/v90ed/factory-bottleneck/scenarios/periods/close']:
        assert route in py
    for table in ['hr_factory_bottleneck_scenario','hr_factory_bottleneck_scenario_result','hr_factory_bottleneck_scenario_close']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+' + table, sql)
    for token in ['overtime_hours','labour_reallocation_hours','schedule_reduction_hours','oee_gain_pct','bottleneck_relief_pct','remaining_overloaded_work_centers']:
        assert token in py and token in sql

def test_v90ed_uses_v90ec_baseline():
    py = (Path(__file__).resolve().parents[1] / 'app/v90ed_factory_bottleneck_scenarios.py').read_text()
    for token in ['hr_factory_bottleneck_optimization_snapshot','machine_capacity_hours','combined_load_pct','labour_gap_hours','oee_pct']:
        assert token in py
