#!/usr/bin/env python3
"""Verify all distributed patches, installers and evidence files by SHA-256."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

root=Path(__file__).resolve().parent
sha_file=root/'SHA256SUMS.txt'
errors=[]; count=0
for line in sha_file.read_text(encoding='utf-8').splitlines():
    if not line.strip():continue
    expected,rel=line.split('  ',1)
    candidate=root/rel
    if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest()!=expected:
        errors.append(rel)
    else:count+=1
for zpath in (root/'patches').glob('etervale_*.zip'):
    with zipfile.ZipFile(zpath) as z:
        if z.testzip() is not None:
            errors.append(zpath.name + ':crc')
        m=json.loads(z.read('PATCH_MANIFEST.json'))
        for item in m['changes']:
            if hashlib.sha256(z.read(item['path'])).hexdigest()!=item['sha256']:
                errors.append(zpath.name+':'+item['path'])
print(f'verificados={count}, erros={len(errors)}')
for entry in errors:print('ERROR',entry)
sys.exit(2 if errors else 0)
