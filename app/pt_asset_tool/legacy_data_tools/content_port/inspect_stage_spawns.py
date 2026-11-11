#!/usr/bin/env python3
import argparse,struct
from pathlib import Path
H=struct.Struct('<4sHHIIIIIIIIII32s');R=struct.Struct('<IIiiIiIIII');A=struct.Struct('<IIi');B=struct.Struct('<IIIIiII');U=struct.Struct('<I')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('pack',type=Path);a=ap.parse_args();d=a.pack.read_bytes();h=H.unpack_from(d);magic,ver,flags,rc,ro,ac,ao,bc,bo,hc,ho,so,ss,dig=h
 print(f'magic={magic!r} version={ver} maps={rc} actors={ac} bosses={bc} hours={hc} strings={ss}')
 def st(off):
  p=so+off;e=d.find(b'\0',p,so+ss);return d[p:e]
 empty_actor_ids=0;empty_boss_ids=0
 for j in range(ac):
  no,io,w=A.unpack_from(d,ao+j*A.size)
  if not st(io):empty_actor_ids+=1
 for j in range(bc):
  mno,sno,mio,sio,sc,hst,hn=B.unpack_from(d,bo+j*B.size)
  if not st(mio) or not st(sio):empty_boss_ids+=1
 for i in range(rc):
  r=R.unpack_from(d,ro+i*R.size);path,idoff,lim,inter,ms,openlim,ast,an,bst,bn=r
  print(f'[{i}] path={st(path).decode("utf-8")} id={st(idoff).decode("utf-8")} limit={lim} interval={inter}/{ms} open={openlim} actors={an} bosses={bn}')
  for j in range(ast,ast+min(an,3)):
   no,io,w=A.unpack_from(d,ao+j*A.size);name=st(no);mid=st(io).decode('utf-8')
   print('  actor',name.decode('cp1252',errors='replace'),'id='+mid,'weight='+str(w))
 print(f'EMPTY_ACTOR_IDS={empty_actor_ids}')
 print(f'EMPTY_BOSS_IDS={empty_boss_ids}')
 if empty_actor_ids or empty_boss_ids:raise SystemExit('RESULT=FAIL: compiled stage spawn pack contains empty monster ids')
 print('RESULT=PASS')
if __name__=='__main__':main()
