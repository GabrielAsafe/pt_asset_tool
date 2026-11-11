#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, struct
from pathlib import Path
MAGIC=b'SCTB'; HEADER=struct.Struct('<4sHHIII32s'); ENTRY=struct.Struct('<IIII32s')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('file',type=Path);a=ap.parse_args();data=a.file.read_bytes()
 magic,ver,flags,count,string_off,string_sz,build_hash=HEADER.unpack_from(data,0)
 if magic!=MAGIC: raise SystemExit('invalid magic')
 body=data[HEADER.size:]
 if hashlib.sha256(body).digest()!=build_hash: raise SystemExit('body hash mismatch')
 strings=data[string_off:string_off+string_sz]
 def s(off):
  end=strings.find(b'\0',off); return strings[off:end].decode('utf-8')
 print(f'magic=SCTB version={ver} documents={count} string_bytes={string_sz} sha256={hashlib.sha256(data).hexdigest()}')
 for i in range(min(count,20)):
  ko,po,off,size,dig=ENTRY.unpack_from(data,HEADER.size+i*ENTRY.size)
  payload=data[off:off+size]
  status='OK' if hashlib.sha256(payload).digest()==dig else 'BAD'
  print(f'{i:4} {status} {s(ko):24} {size:7} {s(po)}')
 if count>20: print(f'... {count-20} more')
if __name__=='__main__': main()
