from pathlib import Path
import re

def test_v90du_artifacts_and_registration():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'app/v90du_workforce_benchmarking.py').exists()
    assert (root / 'migrations/196_v90du_workforce_benchmarking.sql').exists()
    assert (root / 'web/workforce-benchmarking.html').exists()
    main = (root / 'app/__main__.py').read_text()
    assert 'v90du_workforce_benchmarking' in main
    assert 'register_v90du_routes(app, engine)' in main

def test_v90du_routes_and_schema_contract():
    root = Path(__file__).resolve().parents[1]
    py = (root / 'app/v90du_workforce_benchmarking.py').read_text()
    sql = (root / 'migrations/196_v90du_workforce_benchmarking.sql').read_text()
    for route in ['/v90du/workforce/efficiency-targets','/v90du/workforce/benchmarks','/v90du/workforce/labour-cost-forecasts','/v90du/workforce/dashboard','/v90du/workforce/periods/{period_id}/close']:
        assert route in py
    for table in ['hr_labour_efficiency_target','hr_labour_performance_benchmark','hr_production_labour_cost_forecast']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+' + table, sql)
