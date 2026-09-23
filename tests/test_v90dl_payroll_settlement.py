import json
from pathlib import Path

def test_release_manifest():
 d=json.loads((Path(__file__).resolve().parents[1]/'config/release_manifest.json').read_text()); assert str(d['release']).startswith('v90.') and d['schema_target']>=187

def test_settlement_artifacts():
 root=Path(__file__).resolve().parents[1]
 for p in ['app/v90dl_payroll_settlement.py','migrations/187_v90dl_payroll_settlement.sql','web/payroll-settlement.html','docs/release-history/release-notes/RELEASE_NOTES_V90DL.md']:
  assert (root/p).exists()
