from pathlib import Path
import json

def test_v90ff_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text())
    assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text())
    assert m['migrations'][-1]['version']>=244 and m['latest_schema']>=244

def test_v90ff_module_ui_migration():
    assert Path('app/v90ff_reliability_executive_action.py').exists()
    assert Path('migrations/232_v90ff_reliability_executive_action.sql').exists()
    assert Path('web/maintenance-reliability-actions.html').exists()

def test_v90ff_routes_and_controls():
    s=Path('app/v90ff_reliability_executive_action.py').read_text()
    for route in ['/v90ff/maintenance/reliability-actions/generate','/v90ff/maintenance/reliability-actions','/v90ff/maintenance/reliability-actions/{action_id}/decide','/v90ff/maintenance/reliability-actions/{action_id}/complete','/v90ff/maintenance/reliability-actions/{period_key}/close']:
        assert route in s
    assert 'automatic_operational_mutation' in s
    assert 'evidence_note' in s
