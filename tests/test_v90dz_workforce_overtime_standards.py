from pathlib import Path
import re


def test_v90dz_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dz_workforce_overtime_standards.py').exists()
    assert (root/'migrations/201_v90dz_workforce_overtime_standards.sql').exists()
    assert (root/'web/workforce-overtime-standards.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90dz_workforce_overtime_standards' in main
    assert 'register_v90dz_routes(app, engine)' in main


def test_v90dz_contracts():
    root=Path(__file__).resolve().parents[1]
    py=(root/'app/v90dz_workforce_overtime_standards.py').read_text()
    sql=(root/'migrations/201_v90dz_workforce_overtime_standards.sql').read_text()
    for route in [
        '/v90dz/workforce/labour-standards',
        '/v90dz/workforce/labour-standards/performance',
        '/v90dz/workforce/overtime-efficiency',
        '/v90dz/workforce/dashboard',
        '/v90dz/workforce/periods/{period_id}/close']:
        assert route in py
    for table in ['hr_labour_standard','hr_labour_standard_performance','hr_overtime_efficiency_snapshot','hr_workforce_dz_period_close']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table,sql)
    for field in ['standard_hours','hours_variance','cost_variance','efficiency_pct','overtime_efficiency_pct','excess_overtime_hours']:
        assert field in py and field in sql
