from pathlib import Path
import re

def test_v90eb_artifacts_and_registration():
    root=Path(__file__).resolve().parents[1]
    assert (root/'app/v90eb_workforce_bottleneck.py').exists()
    assert (root/'migrations/203_v90eb_workforce_bottleneck_analytics.sql').exists()
    assert (root/'web/workforce-bottleneck.html').exists()
    main=(root/'app/__main__.py').read_text()
    assert 'v90eb_workforce_bottleneck' in main
    assert 'register_v90eb_routes(app, engine)' in main

def test_v90eb_contracts():
    root=Path(__file__).resolve().parents[1]
    py=(root/'app/v90eb_workforce_bottleneck.py').read_text()
    sql=(root/'migrations/203_v90eb_workforce_bottleneck_analytics.sql').read_text()
    for route in ['/v90eb/workforce-bottleneck/calculate','/v90eb/workforce-bottleneck','/v90eb/workforce-bottleneck/dashboard','/v90eb/workforce-bottleneck/periods/close']:
        assert route in py
    for table in ['hr_workforce_bottleneck_snapshot','hr_workforce_bottleneck_close']:
        assert re.search(r'CREATE TABLE IF NOT EXISTS\s+'+table,sql)
    for token in ['labour_efficiency_pct','oee_pct','combined_efficiency_score','labour_oee_gap','downtime_minutes','SEVERE_BOTTLENECK','BOTTLENECK','WATCH','HEALTHY']:
        assert token in py and token in sql

def test_v90eb_uses_existing_ea_and_machine_sources():
    py=(Path(__file__).resolve().parents[1]/'app/v90eb_workforce_bottleneck.py').read_text()
    for token in ['hr_workforce_oee_integration_snapshot','manufacturing_machine_run','manufacturing_machine_status']:
        assert token in py
