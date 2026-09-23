from pathlib import Path
import re

def test_v90dx_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dx_workforce_cost_reconciliation.py').exists()
    assert (root/'migrations/199_v90dx_workforce_cost_reconciliation.sql').exists()
    assert (root/'web/workforce-cost-reconciliation.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90dx_workforce_cost_reconciliation' in main
    assert 'register_v90dx_routes(app, engine)' in main

def test_v90dx_contracts():
    root=Path(__file__).resolve().parents[1]
    py=(root/'app/v90dx_workforce_cost_reconciliation.py').read_text()
    sql=(root/'migrations/199_v90dx_workforce_cost_reconciliation.sql').read_text()
    for route in ['/v90dx/workforce/cost-reconciliation','/v90dx/workforce/cost-reconciliation/{period_id}/close','/v90dx/workforce/cost-reconciliation/dashboard']:
        assert route in py
    assert re.search(r'CREATE TABLE IF NOT EXISTS\s+hr_workforce_cost_reconciliation',sql)
    assert re.search(r'CREATE TABLE IF NOT EXISTS\s+hr_workforce_cost_reconciliation_close',sql)
    for field in ['payroll_employer_cost','allocated_labour_cost','production_labour_cost','labour_budget_cost','payroll_to_allocation_variance','allocation_to_production_variance']:
        assert field in py and field in sql
