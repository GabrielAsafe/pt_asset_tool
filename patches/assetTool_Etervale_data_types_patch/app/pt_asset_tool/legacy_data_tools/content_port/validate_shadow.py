#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sys
from collections import Counter
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('shadow',type=Path); ap.add_argument('--corpus',type=Path)
    a=ap.parse_args(); root=a.shadow
    idx=json.loads((root/'index.json').read_text(encoding='utf-8'))
    errors=[]; warnings=[]; kinds=Counter(); ids={}; sources=set()
    for entry in idx['documents']:
        jp=root/entry['json_path']
        if not jp.is_file(): errors.append(f'missing JSON: {entry["json_path"]}'); continue
        doc=json.loads(jp.read_text(encoding='utf-8'))
        kinds[doc['kind']]+=1
        sp=doc['source']['path']
        if sp in sources: errors.append(f'duplicate source path: {sp}')
        sources.add(sp)
        if doc.get('id'):
            ids.setdefault(doc['id'],[]).append(sp)
        unknown=doc.get('content',{}).get('unknown_tokens',{})
        if unknown: warnings.append(f'{sp}: {len(unknown)} unmapped token(s)')
        if a.corpus:
            p=a.corpus/sp
            if not p.is_file(): errors.append(f'missing source: {sp}')
            else:
                sha=hashlib.sha256(p.read_bytes()).hexdigest()
                if sha != doc['source']['sha256']: errors.append(f'hash mismatch: {sp}')
    for i,paths in ids.items():
        if len(paths)>1: warnings.append(f'duplicate suggested id {i}: {len(paths)} files')
    print(f'files={sum(kinds.values())} errors={len(errors)} warnings={len(warnings)}')
    for e in errors[:100]: print('ERROR',e)
    for w in warnings[:100]: print('WARN ',w)
    if len(warnings)>100: print(f'... {len(warnings)-100} more warnings')
    return 1 if errors else 0
if __name__=='__main__': raise SystemExit(main())
