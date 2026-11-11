#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, hashlib, json, struct
from pathlib import Path
from compile_localization import build_sloc_bytes

EMBEDDED_LOCALIZATION_PATH = "__summit_internal__/localization.sloc"
EMBEDDED_LOCALIZATION_ID = "summit.localization.catalog.v2"

MAGIC=b'SRES'; VERSION=2
HEADER=struct.Struct('<4sHH10I32s')
RECORD=struct.Struct('<6I')
KIND={
 'monster_definition':1,'npc_definition':2,'open_item_definition':3,
 'localization_resource':4,'sin_resource':5,'message_catalog':6,'ini_config':7,'generic_text':8,
}


def norm(s:str)->str:
    parts=[]
    for p in s.replace('\\','/').split('/'):
        if not p or p=='.': continue
        if p=='..':
            if parts: parts.pop()
            continue
        parts.append(p)
    return '/'.join(parts)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('canonical',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    root=a.canonical.resolve(); index=json.loads((root/'index.json').read_text(encoding='utf-8'))['documents']
    strings=bytearray(); soff={}
    def intern(s:str)->int:
        b=s.encode('utf-8')
        if b'\0' in b: raise ValueError('NUL in string')
        if b not in soff:
            soff[b]=len(strings); strings.extend(b+b'\0')
        return soff[b]
    payload=bytearray(); payload_by_sha={}; rows=[]; resource_count=0
    for e in sorted(index,key=lambda x:(x['kind'],x['legacy_path'].casefold())):
        d=json.loads((root/e['json_path']).read_text(encoding='utf-8'))
        raw=base64.b64decode(d['compatibility']['legacy_payload_base64'],validate=True)
        sha=hashlib.sha256(raw).digest()
        poff=payload_by_sha.get(sha)
        if poff is None:
            poff=len(payload); payload.extend(raw); payload_by_sha[sha]=poff
        kind=KIND.get(d['kind'])
        if kind is None: raise ValueError(f'unsupported SRES kind {d["kind"]}')
        resource_count+=1
        source = d.get('source') if isinstance(d.get('source'), dict) else {}
        legacy_path = source.get('legacy_path') if isinstance(source.get('legacy_path'), str) else ''
        if not legacy_path:
            runtime_paths = d.get('runtime_paths') or []
            legacy_path = runtime_paths[0] if runtime_paths else ''
        legacy_key=norm(legacy_path).casefold()
        for alias in d['runtime_paths']:
            # bit 0: runtime alias (prefix stripped); bit 1: provenance/source alias
            flags = 2 if norm(alias).casefold()==legacy_key else 1
            rows.append((intern(norm(alias)),intern(d['id']),kind,flags,poff,len(raw)))
    # Embed the localized key catalog in the existing SRES v2 container. No second pack.
    loc_bytes, loc_report = build_sloc_bytes(root)
    internal_path = norm(EMBEDDED_LOCALIZATION_PATH).casefold()
    if any(norm(d).casefold() == internal_path for d in
           (bytes(strings[r[0]:strings.find(b'\0',r[0])]).decode('utf-8') for r in rows)):
        raise ValueError('reserved internal localization alias collides with canonical resource')
    loc_offset = len(payload)
    payload.extend(loc_bytes)
    rows.append((intern(EMBEDDED_LOCALIZATION_PATH), intern(EMBEDDED_LOCALIZATION_ID),
                 KIND['localization_resource'], 0, loc_offset, len(loc_bytes)))
    resource_count += 1
    rows.sort(key=lambda r: (bytes(strings[r[0]:strings.find(b'\0',r[0])]).lower(),r[2],r[1]))
    header_size=HEADER.size; record_off=header_size; record_size=RECORD.size
    string_off=record_off+len(rows)*record_size; payload_off=string_off+len(strings)
    body=bytearray()
    for r in rows: body.extend(RECORD.pack(*r))
    body.extend(strings); body.extend(payload)
    digest=hashlib.sha256(body).digest()
    header=HEADER.pack(MAGIC,VERSION,0,len(rows),record_off,record_size,string_off,len(strings),payload_off,len(payload),0,0,0,digest)
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_bytes(header+body)
    report={'format':'SRES','version':VERSION,'resources':resource_count,'aliases':len(rows),'unique_payloads':len(payload_by_sha),'strings_bytes':len(strings),'payload_bytes':len(payload),'bytes':a.output.stat().st_size,'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),'embedded_localization':loc_report,'internal_path':EMBEDDED_LOCALIZATION_PATH}
    a.output.with_suffix(a.output.suffix+'.report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
if __name__=='__main__':main()
