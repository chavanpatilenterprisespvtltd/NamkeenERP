from pathlib import Path
import re

def test_v90dy_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90dy_workforce_productivity_kpi.py').exists()
    assert (root/'migrations/200_v90dy_workforce_productivity_kpi.sql').exists()
    assert (root/'web/workforce-productivity-kpi.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90dy_workforce_productivity_kpi' in main
    assert 'register_v90dy_routes(app, engine)' in main

def test_v90dy_contracts():
    root=Path(__file__).resolve().parents[1]
    py=(root/'app/v90dy_workforce_productivity_kpi.py').read_text()
    sql=(root/'migrations/200_v90dy_workforce_productivity_kpi.sql').read_text()
    for route in ['/v90dy/workforce/kpi-targets','/v90dy/workforce/kpi-scorecards','/v90dy/workforce/productivity-benchmarks','/v90dy/workforce/kpi-scorecards','/v90dy/workforce/dashboard','/v90dy/workforce/periods/{period_id}/close']:
        assert route in py
    for table in ['hr_workforce_kpi_target','hr_workforce_kpi_scorecard','hr_workforce_productivity_benchmark']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table,sql)
    for field in ['achievement_pct','efficiency_score','peer_rank','percentile','gap_to_best']:
        assert field in py and field in sql
