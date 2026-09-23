from pathlib import Path
import re

def test_v90ec_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90ec_factory_bottleneck_optimization.py').exists()
    assert (root/'migrations/204_v90ec_factory_bottleneck_optimization.sql').exists()
    assert (root/'web/factory-bottleneck.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90ec_factory_bottleneck_optimization' in main
    assert 'register_v90ec_routes(app, engine)' in main

def test_v90ec_contracts():
    root=Path(__file__).resolve().parents[1]
    py=(root/'app/v90ec_factory_bottleneck_optimization.py').read_text()
    sql=(root/'migrations/204_v90ec_factory_bottleneck_optimization.sql').read_text()
    for route in ['/v90ec/factory-bottleneck/calculate','/v90ec/factory-bottleneck','/v90ec/factory-bottleneck/dashboard','/v90ec/factory-bottleneck/periods/close']:
        assert route in py
    for table in ['hr_factory_bottleneck_optimization_snapshot','hr_factory_bottleneck_optimization_close']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table,sql)
    for token in ['machine_load_pct','labour_load_pct','combined_load_pct','overtime_required_hours','CRITICAL','HIGH','MODERATE','LOW','MACHINE_CAPACITY','LABOUR_CAPACITY','BOTH']:
        assert token in py and token in sql or token in py

def test_v90ec_uses_existing_capacity_and_bottleneck_sources():
    py=(Path(__file__).resolve().parents[1]/'app/v90ec_factory_bottleneck_optimization.py').read_text()
    for token in ['hr_workforce_bottleneck_snapshot','manufacturing_work_center','manufacturing_optimized_schedule','manufacturing_schedule','hr_workforce_capacity_plan','hr_labour_availability_forecast']:
        assert token in py
