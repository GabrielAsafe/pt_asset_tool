#!/usr/bin/env python3
import argparse, hashlib, json, struct
from pathlib import Path
H=struct.Struct('<4sHH6I32s'); E=struct.Struct('<32sIHBBI')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('pack',type=Path);a=ap.parse_args();b=a.pack.read_bytes()
 if len(b)<H.size:raise SystemExit('too small')
 magic,ver,flags,count,eo,es,z0,z1,z2,digest=H.unpack_from(b)
 if magic!=b'SCSP' or ver!=1 or flags or eo!=H.size or es!=E.size or z0 or z1 or z2:raise SystemExit('bad header')
 if eo+count*es!=len(b):raise SystemExit('bad layout')
 if hashlib.sha256(b[H.size:]).digest()!=digest:raise SystemExit('bad sha')
 kinds={1:0,2:0}; codes=set()
 for i in range(count):
  code,price,section,kind,eflags,reserved=E.unpack_from(b,eo+i*es)
  code=code.split(b'\0',1)[0].decode('ascii')
  if not code or price<=0 or section<1 or section>7 or kind not in kinds or eflags or reserved:raise SystemExit(f'bad entry {i}')
  k=(kind,code.casefold())
  if k in codes:raise SystemExit(f'duplicate entry {kind}:{code}')
  codes.add(k);kinds[kind]+=1
 if not kinds[1] or not kinds[2]:raise SystemExit('both shop kinds must be non-empty')
 print(json.dumps({'status':'PASS','entries':count,'coin_entries':kinds[1],'time_entries':kinds[2],'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}))
if __name__=='__main__':main()
