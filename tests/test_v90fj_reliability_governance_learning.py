from pathlib import Path
import json

def test_v90fj_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text()); assert m['migrations'][-1]['version']>=244 and m['latest_schema']>=244

def test_v90fj_files_routes_and_guardrails():
    assert Path('app/v90fj_reliability_governance_learning.py').exists()
    assert Path('migrations/236_v90fj_reliability_governance_learning.sql').exists()
    assert Path('web/maintenance-reliability-governance-learning.html').exists()
    s=Path('app/v90fj_reliability_governance_learning.py').read_text()
    for route in ['/v90fj/maintenance/reliability-governance-learning/snapshot','/v90fj/maintenance/reliability-governance-learning/dashboard','/v90fj/maintenance/reliability-governance-learning/trend','/v90fj/maintenance/reliability-governance-learning/recommendations','/v90fj/maintenance/reliability-governance-learning/recommendations/{recommendation_id}/resolve','/v90fj/maintenance/reliability-governance-learning/{period_key}/close']:
        assert route in s
    assert 'automatic_operational_mutation' in s and 'causal_attribution' in s
