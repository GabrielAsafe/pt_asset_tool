#!/usr/bin/env python3
"""Synchronize linked legacy text resources from the authoritative pt-BR catalog.

The localization catalog is authoritative for entity names/chats. Runtime systems that
still consume text_resources.sres must see the same Portuguese strings. This tool
updates canonical localization_resource semantic entries and their legacy-compatible
payload while keeping the embedded legacy payload SHA/size metadata consistent.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, sys
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument('--check', action='store_true')
    args=ap.parse_args()
    root=args.root.resolve()
    text=root/'Content/canonical/text'
    overrides=load(text/'localization_overrides/pt-BR.json')
    pt={row['key']:row for row in overrides['entries']}
    bindings=load(text/'localization/bindings.json')['bindings']

    resources={}
    paths={}
    for path in (text/'resources').rglob('*.json'):
        try: doc=load(path)
        except Exception: continue
        rid=doc.get('id')
        if rid:
            resources[rid]=doc; paths[rid]=path

    changes={}  # rid -> {(kind,index): text}
    errors=[]
    for binding in bindings:
        rid=binding.get('linked_resource_id')
        doc=resources.get(rid)
        if not doc or doc.get('kind')!='localization_resource':
            continue
        targets=[]
        nk=binding.get('name_key')
        if nk and nk in pt: targets.append(('name',0,pt[nk]['text'],nk,pt[nk].get('source','')))
        for i,key in enumerate(binding.get('chat_keys') or []):
            if key in pt: targets.append(('chat',i,pt[key]['text'],key,pt[key].get('source','')))
        dest=changes.setdefault(rid,{})
        for kind,index,value,key,source in targets:
            slot=(kind,index)
            priority = 2 if source == rid else 1
            old=dest.get(slot)
            if old is None or priority > old[1]:
                dest[slot]=(value,priority,key)
            elif old[0] != value and priority == old[1]:
                errors.append(f'{rid}: conflicting {slot}: {old[0]!r} vs {value!r} ({key})')

    modified=0; compared=0
    for rid, targets in sorted(changes.items()):
        doc=resources[rid]; path=paths[rid]
        entries=doc.get('semantic',{}).get('entries')
        if not isinstance(entries,list):
            errors.append(f'{path}: semantic.entries missing')
            continue
        by_kind={'name':[], 'chat':[]}
        for entry in entries:
            kind=entry.get('kind')
            if kind in by_kind: by_kind[kind].append(entry)
        entry_updates=[]
        for (kind,index),(value,_priority,_key) in sorted(targets.items()):
            arr=by_kind[kind]
            if index >= len(arr):
                errors.append(f'{path}: missing {kind}[{index}]')
                continue
            compared += 1
            entry=arr[index]
            if entry.get('text') != value:
                entry_updates.append((entry,value))
        compat=doc.get('compatibility',{})
        try: raw=base64.b64decode(compat['legacy_payload_base64'], validate=True)
        except Exception as exc:
            errors.append(f'{path}: invalid compatibility payload: {exc}')
            continue
        lines=raw.splitlines(keepends=True)
        # Semantic line numbers in some legacy imports are stale because blank lines
        # were normalized. Match directives in order instead of trusting those numbers.
        cursor=0
        for entry,value in entry_updates:
            try: encoded=value.encode('cp1252')
            except UnicodeEncodeError as exc:
                errors.append(f'{path}: pt-BR is not CP1252-compatible: {value!r}: {exc}')
                continue
            key=str(entry.get('legacy_key','')).encode('ascii','ignore').lower()
            found=-1
            for idx in range(cursor,len(lines)):
                stripped=lines[idx].lstrip().lower()
                if key and stripped.startswith(b'*'+key):
                    found=idx; break
            if found < 0:
                # A resource can be shared/normalized; retry from the beginning.
                for idx,line in enumerate(lines):
                    if key and line.lstrip().lower().startswith(b'*'+key):
                        found=idx; break
            if found < 0:
                errors.append(f'{path}: legacy directive {entry.get("legacy_key")!r} not found')
                continue
            line=lines[found]
            first=line.find(b'"'); last=line.rfind(b'"')
            if first < 0 or last <= first:
                errors.append(f'{path}:{found+1}: quoted legacy payload not found')
                continue
            lines[found]=line[:first+1]+encoded+line[last:]
            entry['text']=value
            cursor=found+1
        rebuilt=b''.join(lines)
        compat['legacy_payload_base64']=base64.b64encode(rebuilt).decode('ascii')
        source=doc.get('source',{})
        metadata_changed=False
        if source.get('migration_status') != 'native_canonical_generated':
            expected_sha=hashlib.sha256(rebuilt).hexdigest()
            expected_size=len(rebuilt)
            if source.get('legacy_sha256') != expected_sha:
                source['legacy_sha256']=expected_sha
                metadata_changed=True
            if source.get('legacy_size') != expected_size:
                source['legacy_size']=expected_size
                metadata_changed=True
        if entry_updates or metadata_changed:
            modified += 1
            if not args.check:
                path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    if errors:
        for e in errors: print('ERROR:',e,file=sys.stderr)
        return 1
    mode='would update' if args.check else 'updated'
    print(f'linked pt-BR text-resource sync: {mode} {modified} resources; compared {compared} bound strings')
    return 2 if args.check and modified else 0

if __name__=='__main__':
    raise SystemExit(main())
