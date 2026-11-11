#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,struct
from pathlib import Path
MAGIC=b'SGCF';VERSION=1;HEADER=struct.Struct('<4sHH10I32s');REC=struct.Struct('<5I');ENT=struct.Struct('<4I')
def norm(s):return '/'.join(p for p in s.replace('\\','/').split('/') if p and p!='.')
def runtime(d):
 for x in d.get('runtime_paths',[]):
  n=norm(x)
  if not n.casefold().startswith(('servidor/','cliente/')):return n
 return norm(d['source']['legacy_path'])
def main():
 ap=argparse.ArgumentParser();ap.add_argument('canonical',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args();root=a.canonical.resolve();idx=json.loads((root/'index.json').read_text(encoding='utf-8'))['documents'];docs=[]
 for e in idx:
  if e['kind']=='ini_config':
   d=json.loads((root/e['json_path']).read_text(encoding='utf-8'))
   if d.get('selection_reason')=='immutable_gameplay_config':docs.append(d)
 docs.sort(key=lambda d:runtime(d).casefold());strings=bytearray();off={}
 def it(s):
  b=str(s).encode('utf-8');
  if b'\0' in b:raise ValueError('NUL')
  if b not in off:off[b]=len(strings);strings.extend(b+b'\0')
  return off[b]
 entries=[];records=[]
 for d in docs:
  st=len(entries)
  for e in d.get('semantic',{}).get('entries',[]):entries.append((it(e.get('section','')),it(e.get('key','')),it(e.get('value','')),int(e.get('line',0))))
  records.append((it(runtime(d)),it(d['id']),st,len(entries)-st,0))
 ro=HEADER.size;eo=ro+len(records)*REC.size;so=eo+len(entries)*ENT.size;body=bytearray()
 for r in records:body.extend(REC.pack(*r))
 for e in entries:body.extend(ENT.pack(*e))
 body.extend(strings);dig=hashlib.sha256(body).digest();header=HEADER.pack(MAGIC,VERSION,0,len(records),ro,REC.size,len(entries),eo,ENT.size,so,len(strings),0,0,dig);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(header+body);rep={'format':'SGCF','version':1,'configs':len(records),'entries':len(entries),'bytes':a.output.stat().st_size,'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()};a.output.with_suffix(a.output.suffix+'.report.json').write_text(json.dumps(rep,indent=2)+'\n');print(json.dumps(rep))
if __name__=='__main__':main()
