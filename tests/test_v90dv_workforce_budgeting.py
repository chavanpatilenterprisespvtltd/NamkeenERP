from pathlib import Path
import re

def test_v90dv_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dv_workforce_budgeting.py').exists()
    assert (root/'migrations/197_v90dv_workforce_budgeting.sql').exists()
    assert (root/'web/workforce-budgeting.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90dv_workforce_budgeting' in main
    assert 'register_v90dv_routes(app, engine)' in main

def test_v90dv_contracts():
    root=Path(__file__).resolve().parents[1]
    py=(root/'app/v90dv_workforce_budgeting.py').read_text()
    sql=(root/'migrations/197_v90dv_workforce_budgeting.sql').read_text()
    for route in ['/v90dv/workforce/budgets','/v90dv/workforce/actuals','/v90dv/workforce/snapshots','/v90dv/workforce/dashboard']:
        assert route in py
    for table in ['hr_labour_budget','hr_labour_budget_actual','hr_labour_benchmark_snapshot']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table,sql)
