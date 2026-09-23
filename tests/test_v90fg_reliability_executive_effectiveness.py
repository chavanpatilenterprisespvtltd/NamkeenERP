from pathlib import Path
import json

def test_v90fg_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text()); assert m['migrations'][-1]['version']>=244 and m['latest_schema']>=244

def test_v90fg_files_and_routes():
    assert Path('app/v90fg_reliability_executive_effectiveness.py').exists(); assert Path('migrations/233_v90fg_reliability_executive_effectiveness.sql').exists(); assert Path('web/maintenance-reliability-effectiveness.html').exists()
    s=Path('app/v90fg_reliability_executive_effectiveness.py').read_text()
    for route in ['/v90fg/maintenance/reliability-effectiveness/snapshot','/v90fg/maintenance/reliability-effectiveness/dashboard','/v90fg/maintenance/reliability-effectiveness/actions','/v90fg/maintenance/reliability-effectiveness/actions/{action_id}/review','/v90fg/maintenance/reliability-effectiveness/{period_key}/close']:
        assert route in s
    assert 'causal_attribution' in s and 'automatic_operational_mutation' in s
