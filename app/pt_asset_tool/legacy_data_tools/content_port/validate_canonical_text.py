#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, hashlib, json
from collections import Counter
from pathlib import Path


def norm(s: str) -> str:
    return '/'.join(p for p in s.replace('\\','/').split('/') if p and p != '.').casefold()


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('canonical',type=Path); a=ap.parse_args()
    root=a.canonical.resolve(); idx=json.loads((root/'index.json').read_text(encoding='utf-8'))['documents']
    ids=set(); paths={}; kinds=Counter(); errors=[]
    for e in idx:
        p=root/e['json_path']
        try:d=json.loads(p.read_text(encoding='utf-8'))
        except Exception as exc:
            errors.append(f'{e["json_path"]}: invalid JSON: {exc}'); continue
        if d.get('schema')!='summit.canonical-text-resource/v1': errors.append(f'{e["json_path"]}: bad schema')
        cid=d.get('id','')
        if not cid: errors.append(f'{e["json_path"]}: missing id')
        elif cid in ids: errors.append(f'{e["json_path"]}: duplicate id {cid}')
        ids.add(cid); kinds[d.get('kind','')]+=1
        try:raw=base64.b64decode(d['compatibility']['legacy_payload_base64'],validate=True)
        except Exception as exc:
            errors.append(f'{e["json_path"]}: bad compatibility payload: {exc}'); continue
        source=d.get('source',{})
        if source.get('migration_status') == 'native_canonical_generated':
            if not source.get('generated_from'):
                errors.append(f'{e["json_path"]}: native canonical source missing generated_from')
        else:
            sha=hashlib.sha256(raw).hexdigest()
            if sha!=source.get('legacy_sha256'): errors.append(f'{e["json_path"]}: payload SHA mismatch')
            if len(raw)!=source.get('legacy_size'): errors.append(f'{e["json_path"]}: payload size mismatch')
        for alias in d.get('runtime_paths',[]):
            k=norm(alias); old=paths.get(k)
            if old and old!=cid: errors.append(f'alias collision {alias}: {old} vs {cid}')
            paths[k]=cid
    loc_index_path=root/'localization'/'index.json'
    localization_keys=set(); english_keys=set(); locale_counts={}
    if not loc_index_path.is_file():
        errors.append('missing localization/index.json')
    else:
        try:
            loc_index=json.loads(loc_index_path.read_text(encoding='utf-8'))
            for catalog in loc_index.get('catalogs',[]):
                doc=json.loads((root/catalog['path']).read_text(encoding='utf-8'))
                locale=doc.get('locale',''); locale_counts[locale]=len(doc.get('entries',[]))
                seen=set()
                for entry in doc.get('entries',[]):
                    key=entry.get('key','')
                    if not key: errors.append(f'{catalog["path"]}: empty localization key'); continue
                    if key in seen: errors.append(f'{catalog["path"]}: duplicate localization key {key}')
                    seen.add(key); localization_keys.add(key)
                    if locale=='en': english_keys.add(key)
                    text=entry.get('text')
                    if not isinstance(text,str) or not text: errors.append(f'{catalog["path"]}: empty text for {key}')
            missing=sorted(localization_keys-english_keys)
            if missing: errors.append(f'missing English fallback for {len(missing)} localization keys: {missing[:20]}')
        except Exception as exc:
            errors.append(f'invalid localization catalog: {exc}')
    if errors:
        print(json.dumps({'status':'FAIL','errors':errors[:100],'error_count':len(errors)},ensure_ascii=False,indent=2)); raise SystemExit(1)
    print(json.dumps({'status':'PASS','resources':len(idx),'ids':len(ids),'aliases':len(paths),'families':dict(kinds),'localization_keys':len(localization_keys),'locales':locale_counts},ensure_ascii=False))
if __name__=='__main__': main()
