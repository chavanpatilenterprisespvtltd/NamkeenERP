import json
from pathlib import Path
from decimal import Decimal
from app.v90dm_payroll_accounting import _money

def test_release_manifest():
    d=json.loads((Path(__file__).resolve().parents[1]/'config/release_manifest.json').read_text())
    assert d['release'].startswith('v90.') and d['schema_target']>=189

def test_artifacts_and_money():
    root=Path(__file__).resolve().parents[1]
    for p in ['app/v90dm_payroll_accounting.py','migrations/188_v90dm_payroll_accounting.sql','web/payroll-accounting.html','docs/release-history/release-notes/RELEASE_NOTES_V90DM.md']:
        assert (root/p).exists()
    assert _money('123.456') == Decimal('123.46')
