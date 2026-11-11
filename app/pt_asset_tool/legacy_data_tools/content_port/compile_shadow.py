#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

# SCTB v1: deterministic generic container. JSON payloads remain UTF-8 inside the
# offline/runtime-transition container; domain-specific packed records can be added
# later without changing authorship JSON.
MAGIC=b'SCTB'; VERSION=1
HEADER=struct.Struct('<4sHHIII32s')
ENTRY=struct.Struct('<IIII32s')  # kindOff,pathOff,payloadOff,payloadSize,sha256

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('shadow',type=Path); ap.add_argument('output',type=Path); a=ap.parse_args()
    index=json.loads((a.shadow/'index.json').read_text(encoding='utf-8'))['documents']
    docs=[]
    for e in sorted(index,key=lambda x:x['source_path']):
        raw=(a.shadow/e['json_path']).read_bytes()
        # canonicalize JSON for deterministic build
        obj=json.loads(raw.decode('utf-8'))
        payload=json.dumps(obj,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode('utf-8')
        docs.append((e['kind'],e['source_path'],payload,hashlib.sha256(payload).digest()))
    strings=bytearray(); offsets={}
    def intern(s):
        if s not in offsets:
            offsets[s]=len(strings); strings.extend(s.encode('utf-8')+b'\0')
        return offsets[s]
    for kind,path,_,_ in docs: intern(kind); intern(path)
    table_size=ENTRY.size*len(docs)
    payload_base=HEADER.size+table_size+len(strings)
    table=bytearray(); payloads=bytearray()
    for kind,path,payload,digest in docs:
        off=payload_base+len(payloads)
        table.extend(ENTRY.pack(intern(kind),intern(path),off,len(payload),digest)); payloads.extend(payload)
    body=bytes(table)+bytes(strings)+bytes(payloads)
    build_hash=hashlib.sha256(body).digest()
    header=HEADER.pack(MAGIC,VERSION,0,len(docs),HEADER.size+table_size,len(strings),build_hash)
    a.output.write_bytes(header+body)
    print(f'written={a.output} documents={len(docs)} bytes={a.output.stat().st_size} sha256={hashlib.sha256(a.output.read_bytes()).hexdigest()}')
if __name__=='__main__': main()
