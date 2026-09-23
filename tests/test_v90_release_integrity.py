import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_integrity():
 rel=json.loads((ROOT/"config/release_manifest.json").read_text()); assert rel["release"].startswith("v90.") and int(rel["erp_schema_target"])>=89
 paths=sorted((ROOT/"migrations").glob("*.sql")); nums=[int(p.name[:3]) for p in paths]; assert nums==list(range(61, max(nums)+1))
 m=json.loads((ROOT/"config/migration_manifest.json").read_text())["migrations"]; assert [x["version"] for x in m]==nums
 for x in m: assert hashlib.sha256((ROOT/"migrations"/x["filename"]).read_bytes()).hexdigest()==x["sha256"]
