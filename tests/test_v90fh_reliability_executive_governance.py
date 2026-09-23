from pathlib import Path
import json

def test_v90fh_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text()); assert m['migrations'][-1]['version']>=244 and m['latest_schema']>=244

def test_v90fh_files_and_routes():
    assert Path('app/v90fh_reliability_executive_governance.py').exists()
    assert Path('migrations/234_v90fh_reliability_executive_governance.sql').exists()
    assert Path('web/maintenance-reliability-governance.html').exists()
    s=Path('app/v90fh_reliability_executive_governance.py').read_text()
    for route in ['/v90fh/maintenance/reliability-governance/snapshot','/v90fh/maintenance/reliability-governance/dashboard','/v90fh/maintenance/reliability-governance/escalations','/v90fh/maintenance/reliability-governance/escalations/{escalation_id}/resolve','/v90fh/maintenance/reliability-governance/{period_key}/close']:
        assert route in s
    assert 'automatic_operational_mutation' in s and 'causal_attribution' in s
