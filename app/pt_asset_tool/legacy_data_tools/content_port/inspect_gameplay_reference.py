#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, struct
from pathlib import Path

MAGIC=b'SGRF'; VERSION=2
HEADER=struct.Struct('<4sHH10I32s'); QUEST=struct.Struct('<6I2i3I'); ENTRY=struct.Struct('<2I'); MIX=struct.Struct('<6Ii2I')
VALID_KINDS=set(range(1,13))|{100,101,102,103}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('pack',type=Path); a=ap.parse_args(); data=a.pack.read_bytes()
 if len(data)<HEADER.size: raise SystemExit('pack too small')
 h=HEADER.unpack_from(data,0); magic,ver,flags=h[:3]; ints=h[3:13]; digest=h[13]
 qc,qo,qs,ec,eo,es,mc,mo,ms,so=ints
 if magic!=MAGIC or ver!=VERSION or flags: raise SystemExit('header mismatch')
 if qo!=HEADER.size or qs!=QUEST.size or eo!=qo+qc*qs or es!=ENTRY.size or mo!=eo+ec*es or ms!=MIX.size or so!=mo+mc*ms or so>len(data): raise SystemExit('layout mismatch')
 if hashlib.sha256(data[HEADER.size:]).digest()!=digest: raise SystemExit('digest mismatch')
 ss=len(data)-so
 def s(off):
  if off>=ss: raise ValueError('string offset')
  b=so+off; e=data.find(b'\0',b,len(data))
  if e<0: raise ValueError('unterminated string')
  return data[b:e].decode('utf-8')
 supported=0
 for i in range(qc):
  r=QUEST.unpack_from(data,qo+i*qs)
  if r[8]&2: supported+=1
  for off in r[:6]: s(off)
  if r[9]>ec or r[10]>ec-r[9]: raise ValueError('quest entry range')
 for i in range(ec):
  kind,off=ENTRY.unpack_from(data,eo+i*es)
  if kind not in VALID_KINDS: raise ValueError(f'entry kind {kind}')
  s(off)
 recipes=0
 for i in range(mc):
  r=MIX.unpack_from(data,mo+i*ms)
  vals=[s(x) for x in r[:5]]
  if vals[0] != '__catalog__': recipes += 1
  if r[7]>ec or r[8]>ec-r[7]: raise ValueError('mix entry range')
 print(f'FORMAT=SGRF VERSION={ver} QUESTS={qc} SUPPORTED={supported} MIX_RECIPES={recipes} LIST_ENTRIES={ec} BYTES={len(data)} SHA256={hashlib.sha256(data).hexdigest()}')
 print('RESULT=PASS')
if __name__=='__main__':main()
