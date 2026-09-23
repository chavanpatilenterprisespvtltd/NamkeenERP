from __future__ import annotations
import json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / '.github/workflows/ci.yml',
    ROOT / 'config/migration_manifest.json',
    ROOT / 'config/release_manifest.json',
    ROOT / 'requirements.txt',
    ROOT / 'scripts/migration_smoke.py',
]

def fail(msg: str) -> None:
    print(f'CI GATE FAILED: {msg}')
    raise SystemExit(1)

for path in REQUIRED:
    if not path.is_file(): fail(f'missing required CI artifact: {path.relative_to(ROOT)}')

release = json.loads((ROOT/'config/release_manifest.json').read_text())
release_version = str(release.get('release', ''))
expected_target = int(release.get('schema_target', 0))
if not re.fullmatch(r'v90\.[a-z]{2}', release_version) or expected_target < 61:
    fail('release manifest has invalid release/schema target')

migrations = sorted((ROOT/'migrations').glob('*.sql'))
versions = [int(p.name[:3]) for p in migrations]
if versions != list(range(61, expected_target + 1)):
    fail(f'migrations are not contiguous 61..{expected_target}: {versions[-5:]}')
for p in migrations:
    if not re.fullmatch(r'\d{3}_[A-Za-z0-9_]+\.sql', p.name): fail(f'invalid migration filename: {p.name}')

workflow = (ROOT/'.github/workflows/ci.yml').read_text()
for required in ('pytest -q', 'scripts/ci_gate.py', 'scripts/verify_checksums.py', 'scripts/migration_smoke.py', 'postgres:16'):
    if required not in workflow: fail(f'CI workflow missing required step: {required}')

print('CI repository gate passed: workflows, release target, migration continuity, and required pipeline steps verified.')
