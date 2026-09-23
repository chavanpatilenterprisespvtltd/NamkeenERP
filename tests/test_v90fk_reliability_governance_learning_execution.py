from pathlib import Path
import json, hashlib

def test_v90fk_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text()); assert m['migrations'][-1]['version']>=263 and any(x['version']==262 and x['filename']=='262_v90gk_costing_profitability.sql' for x in m['migrations'])
    f=Path('migrations/240_v90fn_security_rbac_scope_hardening.sql'); historical=next(x for x in m['migrations'] if x['version']==240); assert hashlib.sha256(f.read_bytes()).hexdigest()==historical['sha256']

def test_v90fk_routes_and_guardrails():
    assert Path('app/v90fk_reliability_governance_learning_execution.py').exists()
    assert Path('web/maintenance-reliability-governance-learning-execution.html').exists()
    s=Path('app/v90fk_reliability_governance_learning_execution.py').read_text()
    for route in ['/v90fk/maintenance/reliability-governance-learning/executions','/executions/{execution_id}/start','/executions/{execution_id}/complete','/executions/{execution_id}/benefit','/benefits','/{period_key}/close']:
        assert route in s
    assert 'automatic_operational_mutation' in s and 'causal_attribution' in s
    assert "only OPEN learning recommendations can be executed" in s

def test_v90fk_main_registration():
    s=Path('app/__main__.py').read_text(); assert 'register_v90fk_routes(app, engine)' in s
