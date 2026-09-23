#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT/'config'/'release_manifest.json').read_text())
required = manifest['required_components']
missing = []
for name in required:
    key = f'NAMKEEN_{name.upper()}_READY'
    if os.getenv(key) != '1':
        missing.append(key)
print(f"Release {manifest['release']} preflight")
if missing:
    print('BLOCKED: missing readiness flags:')
    for item in missing: print(' -', item)
    sys.exit(2)
print('PASS: required component readiness flags present')
