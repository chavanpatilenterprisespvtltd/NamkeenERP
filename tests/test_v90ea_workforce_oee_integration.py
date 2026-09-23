from pathlib import Path
import re


def test_v90ea_artifacts_and_registration():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'app/v90ea_workforce_oee_integration.py').exists()
    assert (root / 'migrations/202_v90ea_workforce_oee_integration.sql').exists()
    assert (root / 'web/workforce-oee.html').exists()
    main = (root / 'app/__main__.py').read_text()
    assert 'v90ea_workforce_oee_integration' in main
    assert 'register_v90ea_routes(app, engine)' in main


def test_v90ea_contracts():
    root = Path(__file__).resolve().parents[1]
    py = (root / 'app/v90ea_workforce_oee_integration.py').read_text()
    sql = (root / 'migrations/202_v90ea_workforce_oee_integration.sql').read_text()
    for route in [
        '/v90ea/workforce-oee/calculate',
        '/v90ea/workforce-oee',
        '/v90ea/workforce-oee/dashboard',
        '/v90ea/workforce-oee/periods/close']:
        assert route in py
    for table in ['hr_workforce_oee_integration_snapshot', 'hr_workforce_oee_integration_close']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+' + table, sql)
    for field in ['availability_pct','oee_pct','labour_efficiency_pct','combined_efficiency_score','labour_oee_gap','output_per_labour_hour']:
        assert field in py and field in sql


def test_v90ea_weight_and_status_logic_present():
    root = Path(__file__).resolve().parents[1]
    py = (root / 'app/v90ea_workforce_oee_integration.py').read_text()
    for token in ['labour_efficiency_weight', 'oee_weight', "status = 'STRONG'", "status = 'WATCH'", "status = 'REVIEW'", 'manufacturing_machine_run', 'hr_labour_standard_performance', 'manufacturing_machine_oee']:
        assert token in py
