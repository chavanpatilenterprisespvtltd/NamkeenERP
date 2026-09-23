from pathlib import Path
import json

def test_v90fe_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text())
    assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text())
    assert m['migrations'][-1]['version']>=244 and m['latest_schema']>=244

def test_v90fe_module_and_ui_exist():
    assert Path('app/v90fe_reliability_executive_command.py').exists()
    assert Path('migrations/231_v90fe_reliability_executive_command.sql').exists()
    assert Path('web/maintenance-reliability-command.html').exists()

def test_v90fe_routes_and_main_registration():
    s=Path('app/v90fe_reliability_executive_command.py').read_text()
    main=Path('app/__main__.py').read_text()
    for route in ['/v90fe/maintenance/reliability-command/snapshot','/v90fe/maintenance/reliability-command/dashboard','/v90fe/maintenance/reliability-command/exceptions/{exception_id}/resolve','/v90fe/maintenance/reliability-command/{period_key}/close']:
        assert route in s
    assert 'register_v90fe_routes(app, engine)' in main

def test_v90fe_no_automatic_mutation():
    s=Path('app/v90fe_reliability_executive_command.py').read_text()
    assert 'automatic_operational_mutation' in s
    assert 'causal_attribution' in s
