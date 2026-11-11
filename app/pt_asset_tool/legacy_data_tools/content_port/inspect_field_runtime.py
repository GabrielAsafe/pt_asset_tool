#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

FH=struct.Struct('<4sHHIIIIII32s'); FS=struct.Struct('<4sHHII32s')
SPH=struct.Struct('<4sHHIIIIII32s'); MAP=struct.Struct('<IIII'); POINT=struct.Struct('<Iiii'); NPC=struct.Struct('<III7i')

def check_digest(data:bytes, expected:bytes, label:str):
    actual=hashlib.sha256(data).digest()
    if actual!=expected: raise ValueError(f'{label} SHA-256 mismatch')

def read_inner(data:bytes, magic:bytes, row_struct:struct.Struct, item_struct:struct.Struct):
    if len(data)<SPH.size: raise ValueError(f'{magic.decode()} section too small')
    fields=SPH.unpack_from(data,0)
    mg,ver,flags,map_count,map_off,item_count,item_off,string_off,string_size,digest=fields
    if mg!=magic or ver!=1 or flags!=0: raise ValueError(f'{magic.decode()} header invalid')
    if map_off!=SPH.size or item_off!=map_off+map_count*row_struct.size or string_off!=item_off+item_count*item_struct.size or string_off+string_size!=len(data):
        raise ValueError(f'{magic.decode()} layout invalid')
    check_digest(data[SPH.size:],digest,magic.decode())
    return {'maps':map_count,'items':item_count,'bytes':len(data)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('pack',type=Path); a=ap.parse_args(); data=a.pack.read_bytes()
    if len(data)<FH.size: raise SystemExit('SFLD too small')
    mg,ver,flags,count,table_off,data_off,file_size,r0,r1,digest=FH.unpack_from(data,0)
    if mg!=b'SFLD' or ver!=1 or flags!=0 or table_off!=FH.size or data_off!=FH.size+count*FS.size or file_size!=len(data) or r0 or r1:
        raise SystemExit('SFLD header/layout invalid')
    check_digest(data[FH.size:],digest,'SFLD')
    sections={}
    for i in range(count):
        tag,sv,sflags,off,size,sd=FS.unpack_from(data,table_off+i*FS.size)
        if sflags or off<data_off or off+size>len(data): raise SystemExit('SFLD section invalid')
        payload=data[off:off+size]; check_digest(payload,sd,tag.decode('ascii','replace'))
        key=tag.decode('ascii'); sections[key]={'version':sv,'bytes':size,'sha256':hashlib.sha256(payload).hexdigest()}
        if tag==b'SPPT': sections[key].update(read_inner(payload,b'SPPT',MAP,POINT))
        if tag==b'SPCN': sections[key].update(read_inner(payload,b'SPCN',MAP,NPC))
        if tag==b'GMSP':
            gh=struct.Struct('<4sHHII32s')
            gr=struct.Struct('<IIiiiIII64s')
            if len(payload)<gh.size:raise SystemExit('GM section too small')
            mg,version,flags,n,stride,sd=gh.unpack_from(payload,0)
            if mg!=b'GMS1' or version!=1 or flags!=0 or stride!=gr.size or n>96 or len(payload)!=gh.size+n*gr.size:
                raise SystemExit('bad GM section layout')
            check_digest(payload[gh.size:],sd,'GMS1')
            sections[key]['points']=n
        if tag==b'SSPB' and payload[:4]!=b'SSPB': raise SystemExit('embedded SSPB invalid')
    # # SUMMIT386A GMSP JSON GM XYZ
    required={'SSPB','SPPT','SPCN','GMSP'}
    if set(sections)!=required: raise SystemExit(f'SFLD sections mismatch: {sorted(sections)}')
    print(json.dumps({'status':'PASS','format':'SFLD','version':ver,'bytes':len(data),'sections':sections},ensure_ascii=False))
if __name__=='__main__': main()
