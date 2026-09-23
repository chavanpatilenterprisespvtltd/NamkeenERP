from pathlib import Path
import json

def test_v90fi_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text()); assert m['migrations'][-1]['version']>=244 and m['latest_schema']>=244

def test_v90fi_files_and_routes():
    assert Path('app/v90fi_reliability_executive_governance_effectiveness.py').exists()
    assert Path('migrations/235_v90fi_reliability_executive_governance_effectiveness.sql').exists()
    assert Path('web/maintenance-reliability-governance-effectiveness.html').exists()
    s=Path('app/v90fi_reliability_executive_governance_effectiveness.py').read_text()
    for route in ['/v90fi/maintenance/reliability-governance-effectiveness/snapshot','/v90fi/maintenance/reliability-governance-effectiveness/dashboard','/v90fi/maintenance/reliability-governance-effectiveness/reviews','/v90fi/maintenance/reliability-governance-effectiveness/reviews/{review_id}/resolve','/v90fi/maintenance/reliability-governance-effectiveness/{period_key}/close']:
        assert route in s
    assert 'automatic_operational_mutation' in s and 'causal_attribution' in s
