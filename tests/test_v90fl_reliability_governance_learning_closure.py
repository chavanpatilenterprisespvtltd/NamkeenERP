from pathlib import Path
import hashlib,json

def test_v90fl_release_and_migration():
    r=json.loads(Path('config/release_manifest.json').read_text()); assert r['version'].startswith('v90.') and r['schema_target']>=266
    m=json.loads(Path('config/migration_manifest.json').read_text()); assert m['migrations'][-1]['version']>=263 and any(x['version']==262 and x['filename']=='262_v90gk_costing_profitability.sql' for x in m['migrations'])
    f=Path('migrations/240_v90fn_security_rbac_scope_hardening.sql'); historical=next(x for x in m['migrations'] if x['version']==240); assert hashlib.sha256(f.read_bytes()).hexdigest()==historical['sha256']

def test_v90fl_routes_and_guardrails():
    assert Path('app/v90fl_reliability_governance_learning_closure.py').exists() and Path('web/maintenance-reliability-governance-learning-closure.html').exists()
    s=Path('app/v90fl_reliability_governance_learning_closure.py').read_text()
    for route in ['/v90fl/maintenance/reliability-governance-learning/closure','/v90fl/maintenance/reliability-governance-learning/knowledge','/knowledge/{knowledge_id}/approve','/knowledge/{knowledge_id}/retire']:
        assert route in s
    assert 'automatic_operational_mutation' in s and 'causal_attribution' in s

def test_v90fl_main_registration():
    s=Path('app/__main__.py').read_text(); assert 'register_v90fl_routes(app, engine)' in s
