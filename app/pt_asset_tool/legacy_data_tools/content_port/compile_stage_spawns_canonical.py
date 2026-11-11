#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,struct
from pathlib import Path
MAGIC=b'SSPB';VERSION=2
HEADER=struct.Struct('<4sHHIIIIIIIIII32s');RECORD=struct.Struct('<IIiiIiIIII');ACTOR=struct.Struct('<IIi');BOSS=struct.Struct('<IIIIiII');HOUR=struct.Struct('<I')

def _load_ptbr_runtime_names(root: Path):
 loc_path=root/'localization'/'pt-BR.json'
 if not loc_path.is_file():raise FileNotFoundError(f'pt-BR localization catalog not found: {loc_path}')
 doc=json.loads(loc_path.read_text(encoding='utf-8'));entries=doc.get('entries',[])
 if not isinstance(entries,list):raise ValueError(f'pt-BR localization entries must be a list: {loc_path}')
 names={}
 for row in entries:
  if not isinstance(row,dict):continue
  key=row.get('key');text=row.get('text')
  if not isinstance(key,str) or not key:continue
  if key in names:raise ValueError(f'duplicate pt-BR localization key: {key}')
  if isinstance(text,str):names[key]=text
 return names

def load_monster_names(root: Path):
 localized=_load_ptbr_runtime_names(root)
 idx=json.loads((root/'index.json').read_text(encoding='utf-8'))['documents']
 names={}
 for entry in idx:
  if entry.get('kind')!='monster_definition':continue
  d=json.loads((root/entry['json_path']).read_text(encoding='utf-8'))
  mid=d.get('id','')
  if not mid:continue
  key=f'{mid}.name';name=localized.get(key)
  if not isinstance(name,str) or not name.strip():raise ValueError(f'monster runtime pt-BR display name is missing or empty: {mid}: {key}')
  try:encoded=name.encode('cp1252')
  except UnicodeEncodeError as exc:raise ValueError(f'monster runtime pt-BR display name is not CP1252 encodable: {mid}: {name!r}') from exc
  if len(encoded)>=32:raise ValueError(f'monster runtime pt-BR display name exceeds legacy capacity: {mid}: {name!r}')
  names[mid]=encoded
 return names

def main():
 ap=argparse.ArgumentParser();ap.add_argument('canonical',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--canonical-text',type=Path,required=True);a=ap.parse_args();root=a.canonical.resolve();monster_names=load_monster_names(a.canonical_text.resolve());idx=json.loads((root/'index.json').read_text(encoding='utf-8'))['documents'];docs=[json.loads((root/e['json_path']).read_text(encoding='utf-8')) for e in idx];docs.sort(key=lambda d:d['logical_path'].casefold())
 strings=bytearray();off={}
 def ib(b):
  if b'\0' in b:raise ValueError('NUL in SSPB string')
  if b not in off:off[b]=len(strings);strings.extend(b+b'\0')
  return off[b]
 def it(s):return ib(s.encode('utf-8'))
 empty=ib(b'');actors=[];bosses=[];hours=[];records=[];filtered_legacy_missing=[];canonical_actor_names=0;canonical_boss_names=0
 for d in docs:
  ast=len(actors)
  for x in d.get('actors',[]):
   legacy=bytes.fromhex(x['legacy_name_bytes_hex']);mid=x.get('monster_id','')
   if not mid:
    if x.get('resolution')=='legacy_skip_if_missing':
     filtered_legacy_missing.append({'path':d['logical_path'],'legacy_name':x.get('legacy_name',''),'weight':int(x.get('weight',0))})
     continue
    raise ValueError(f"actor without monster_id is not explicitly skippable: {d['logical_path']}: {x.get('legacy_name','')}")
   display=monster_names.get(mid)
   if display is None:raise ValueError(f'actor monster_id has no canonical monster display name: {d["logical_path"]}: {mid}')
   canonical_actor_names+=1
   actors.append((ib(display),it(mid),int(x.get('weight',0))))
  bst=len(bosses)
  for x in d.get('bosses',[]):
   hs=[int(v) for v in x.get('open_hours',[])];hst=len(hours);hours.extend(hs);mid=x.get('master_monster_id','');sid=x.get('slave_monster_id','')
   if not mid or not sid:raise ValueError(f'boss without canonical monster IDs: {d["logical_path"]}')
   mr=monster_names.get(mid);sr=monster_names.get(sid)
   if mr is None or sr is None:raise ValueError(f'boss monster_id has no canonical monster display name: {d["logical_path"]}: {mid}/{sid}')
   canonical_boss_names+=2
   bosses.append((ib(mr),ib(sr),it(mid),it(sid),int(x.get('slave_count',0)),hst,len(hs)))
  delay=d.get('delay') or {};shift=int(delay.get('shift',7));oi=(1<<shift);oi=oi-1 if oi>1 else oi;records.append((it(d['logical_path'].lower()),it(d['id']),int(d.get('limit_max',0)),oi,int(delay.get('milliseconds',0)),int(d.get('open_limit',3)),ast,len(actors)-ast,bst,len(bosses)-bst))
 ro=HEADER.size;ao=ro+len(records)*RECORD.size;bo=ao+len(actors)*ACTOR.size;ho=bo+len(bosses)*BOSS.size;so=ho+len(hours)*HOUR.size;body=bytearray()
 for x in records:body.extend(RECORD.pack(*x))
 for x in actors:body.extend(ACTOR.pack(*x))
 for x in bosses:body.extend(BOSS.pack(*x))
 for x in hours:body.extend(HOUR.pack(x))
 body.extend(strings);digest=hashlib.sha256(body).digest();header=HEADER.pack(MAGIC,VERSION,0,len(records),ro,len(actors),ao,len(bosses),bo,len(hours),ho,so,len(strings),digest);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(header+body);report={'format':'SSPB','version':VERSION,'maps':len(records),'actors':len(actors),'bosses':len(bosses),'canonical_actor_names':canonical_actor_names,'canonical_boss_names':canonical_boss_names,'filtered_legacy_missing_actors':filtered_legacy_missing,'bytes':a.output.stat().st_size,'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()};a.output.with_suffix(a.output.suffix+'.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({**report,'filtered_legacy_missing_actors':len(filtered_legacy_missing)},ensure_ascii=False))
if __name__=='__main__':main()
