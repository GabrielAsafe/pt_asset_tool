#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,struct
from pathlib import Path
from sres_embedded_localization import extract_sloc_bytes
MAGIC=b'SRES'; HEADER=struct.Struct('<4sHH10I32s'); RECORD=struct.Struct('<6I')

def main():
 ap=argparse.ArgumentParser();ap.add_argument('pack',type=Path);ap.add_argument('--list',action='store_true');a=ap.parse_args(); data=a.pack.read_bytes()
 if len(data)<HEADER.size: raise SystemExit('too small')
 h=HEADER.unpack_from(data,0); magic,version,flags,*rest=h
 if magic!=MAGIC or version!=2: raise SystemExit('bad magic/version')
 rc,ro,rs,so,ss,po,ps,profile,r0,r1,digest=rest
 if rs!=RECORD.size: raise SystemExit('record size mismatch')
 if ro!=HEADER.size or so!=ro+rc*rs or po!=so+ss or po+ps!=len(data): raise SystemExit('non-canonical layout')
 if hashlib.sha256(data[HEADER.size:]).digest()!=digest: raise SystemExit('SHA mismatch')
 def s(off):
  if off>=ss: raise ValueError('string offset')
  start=so+off; end=data.find(b'\0',start,so+ss)
  if end<0: raise ValueError('unterminated string')
  return data[start:end].decode('utf-8')
 rows=[]
 for i in range(rc):
  patho,ido,kind,flags,rel,size=RECORD.unpack_from(data,ro+i*rs)
  if rel>ps or size>ps-rel: raise SystemExit('payload range')
  rows.append({'path':s(patho),'id':s(ido),'kind':kind,'bytes':size})
 loc=extract_sloc_bytes(data)
 lh=struct.Struct('<4sHH10I32s').unpack_from(loc)
 if lh[:3] != (b'SLOC',2,0) or lh[5] != 20 or lh[4] != 80 or lh[6] != 80+lh[3]*20 or lh[6]+lh[7] != len(loc) or hashlib.sha256(loc[80:]).digest() != lh[-1]:
  raise SystemExit('invalid embedded localization SLOC')
 out={'embedded_localization':'PASS','embedded_localization_entries':lh[3],'status':'PASS','version':version,'aliases':rc,'string_bytes':ss,'payload_bytes':ps,'sha256':hashlib.sha256(data).hexdigest()}
 print(json.dumps(out,indent=2))
 if a.list: print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
