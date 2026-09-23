from app.__main__ import app
from app.release import load_release_info

def test_v90aa_routes_exist():
    paths={r.path for r in app.routes}
    assert '/v90aa/price-check' in paths
    assert '/v90aa/price-policies' in paths
    assert '/v90aa/price-exceptions' in paths

def test_v90aa_manifest():
    r=load_release_info()
    assert r.version.startswith('v90.') and int(r.schema_target)>=104

def test_v90aa_release_notes_exist():
    from pathlib import Path
    assert Path(__file__).resolve().parents[1].joinpath('docs/release-history/release-notes/RELEASE_NOTES_V90AA.md').exists()

def test_v90aa_migration_manifest_contains_100():
    import json
    from pathlib import Path
    d=json.loads(Path(__file__).resolve().parents[1].joinpath('config/migration_manifest.json').read_text())
    assert any(m['version']==100 for m in d['migrations'])
