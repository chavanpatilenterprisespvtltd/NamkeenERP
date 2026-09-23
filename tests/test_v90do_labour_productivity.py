import json
from decimal import Decimal
from pathlib import Path
from app.v90do_labour_productivity import _money

def test_release_manifest():
    d=json.loads((Path(__file__).resolve().parents[1]/'config/release_manifest.json').read_text())
    assert d['release'].startswith('v90.') and d['schema_target']>=190

def test_artifacts_and_money():
    root=Path(__file__).resolve().parents[1]
    for p in ['app/v90do_labour_productivity.py','migrations/190_v90do_labour_productivity.sql','web/labour-productivity.html','docs/release-history/release-notes/RELEASE_NOTES_V90DO.md']:
        assert (root/p).exists()
    assert _money('123.456') == Decimal('123.46')

def test_migration_is_next():
    root=Path(__file__).resolve().parents[1]
    assert (root/'migrations/189_v90dn_payroll_mis.sql').exists()
    assert (root/'migrations/190_v90do_labour_productivity.sql').exists()
