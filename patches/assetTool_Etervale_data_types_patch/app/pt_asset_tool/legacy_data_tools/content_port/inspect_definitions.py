#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,struct
from pathlib import Path
H=struct.Struct('<4sHH10I32s');R=struct.Struct('<5I');D=struct.Struct('<3I')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('pack',type=Path);a=ap.parse_args();data=a.pack.read_bytes();h=H.unpack_from(data)
 magic,ver,flags,rc,ro,rs,dc,do,ds,so,ss,r0,r1,digest=h
 assert magic==b'SCFG' and ver==1 and ro==H.size and rs==R.size and ds==D.size and do==ro+rc*rs and so==do+dc*ds and so+ss==len(data) and not r0 and not r1
 assert hashlib.sha256(data[H.size:]).digest()==digest
 def s(off):
  assert off<ss;b=so+off;e=data.find(b'\0',b,so+ss);assert e>=0;return data[b:e]
 for i in range(rc):
  po,io,k,st,c=R.unpack_from(data,ro+i*rs);assert st<=dc and c<=dc-st;s(po).decode('utf-8');s(io).decode('utf-8')
 for i in range(dc):
  co,vo,f=D.unpack_from(data,do+i*ds);s(co);s(vo)
 print(json.dumps({'status':'PASS','version':ver,'definitions':rc,'directives':dc,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}))
if __name__=='__main__':main()
