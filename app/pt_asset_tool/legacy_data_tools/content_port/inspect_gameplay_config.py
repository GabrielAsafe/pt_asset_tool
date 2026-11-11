#!/usr/bin/env python3
import argparse,hashlib,json,struct
from pathlib import Path
H=struct.Struct('<4sHH10I32s');R=struct.Struct('<5I');E=struct.Struct('<4I')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('pack',type=Path);a=ap.parse_args();b=a.pack.read_bytes()
 if len(b)<H.size:raise SystemExit('too small')
 x=H.unpack_from(b);magic,ver,flags=x[:3];vals=x[3:13];dig=x[13];rc,ro,rs,ec,eo,es,so,ss,z0,z1=vals
 if magic!=b'SGCF' or ver!=1 or flags or rs!=R.size or es!=E.size or z0 or z1:raise SystemExit('bad header')
 if ro!=H.size or eo!=ro+rc*rs or so!=eo+ec*es or so+ss!=len(b):raise SystemExit('bad layout')
 if hashlib.sha256(b[H.size:]).digest()!=dig:raise SystemExit('bad sha')
 print(json.dumps({'status':'PASS','configs':rc,'entries':ec,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}))
if __name__=='__main__':main()
