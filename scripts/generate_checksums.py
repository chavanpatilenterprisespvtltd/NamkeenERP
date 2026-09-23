from __future__ import annotations
import hashlib, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parents[1]
items=[]
for p in ROOT.rglob('*'):
    if p.is_file() and '.git' not in p.parts and p.name not in {'artifact_checksums.json'} and not any(part == '__pycache__' or part == '.pytest_cache' for part in p.parts) and p.suffix not in {'.db', '.sqlite', '.sqlite3', '.pyc'}:
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        items.append({'path': str(p.relative_to(ROOT)).replace('\\','/'), 'sha256': h})
items.sort(key=lambda x:x['path'])
release = json.loads((ROOT/'config/release_manifest.json').read_text(encoding='utf-8'))['release']
(ROOT/'artifact_checksums.json').write_text(json.dumps({'release':release,'artifacts':items}, indent=2)+"\n")
print(f'generated {len(items)} checksums')
