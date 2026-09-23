from __future__ import annotations
import hashlib, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'artifact_checksums.json').read_text())
errors=[]
for item in data['artifacts']:
    p=ROOT/item['path']
    if not p.exists(): errors.append(f'missing: {item["path"]}'); continue
    got=hashlib.sha256(p.read_bytes()).hexdigest()
    if got != item['sha256']: errors.append(f'mismatch: {item["path"]}')
if errors:
    print('\n'.join(errors)); sys.exit(1)
print(f'checksum verification passed: {len(data["artifacts"])} files')
