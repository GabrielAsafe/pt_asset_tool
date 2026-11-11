#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path
from sres_embedded_localization import extract_sloc_bytes
MAGIC=b'SLOC'; HEADER=struct.Struct('<4sHH10I32s'); RECORD=struct.Struct('<5I')
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('pack',type=Path); a=ap.parse_args(); data=extract_sloc_bytes(a.pack) if a.pack.suffix.lower()=='.sres' else a.pack.read_bytes()
 if len(data)<HEADER.size: raise SystemExit('SLOC too small')
 h=HEADER.unpack_from(data); magic,ver,flags=h[:3]; vals=h[3:13]; digest=h[13]
 rc,ro,rs,so,ss,z0,z1,z2,z3,z4=vals
 ok=(magic==MAGIC and ver==2 and flags==0 and ro==HEADER.size and rs==RECORD.size and so==ro+rc*rs and so+ss==len(data) and not any((z0,z1,z2,z3,z4)))
 actual=hashlib.sha256(data[HEADER.size:]).digest(); ok=ok and actual==digest
 def string(off):
  if off>=ss: raise ValueError('bad string offset')
  b=so+off; e=data.find(b'\0',b,so+ss)
  if e<0: raise ValueError('unterminated string')
  return data[b:e].decode('utf-8')
 locales={}; keys=set(); en=set()
 if ok:
  for i in range(rc):
   loc,key,text,source,fl=RECORD.unpack_from(data,ro+i*rs); l=string(loc); k=string(key); string(text); string(source); locales[l]=locales.get(l,0)+1; keys.add(k); en.add(k) if l=='en' else None
  ok=keys<=en
 report={'format':'SLOC','version':ver,'entries':rc,'keys':len(keys),'english_keys':len(en),'locales':locales,'bytes':len(data),'sha256_body_valid':actual==digest,'valid':ok}
 print(json.dumps(report,ensure_ascii=False,indent=2))
 if not ok: raise SystemExit(1)
if __name__=='__main__': main()
