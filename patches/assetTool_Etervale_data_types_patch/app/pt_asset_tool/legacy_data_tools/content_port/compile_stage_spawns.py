#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,struct
from collections import defaultdict
from pathlib import Path, PurePosixPath

MAGIC=b'SSPB'; VERSION=2
HEADER=struct.Struct('<4sHHIIIIIIIIII32s')
RECORD=struct.Struct('<IIiiIiIIII')
ACTOR=struct.Struct('<IIi')              # legacyNameOffset, monsterIdOffset, weight
BOSS=struct.Struct('<IIIIiII')           # masterName, slaveName, masterId, slaveId, slaveCount, hourStart, hourCount
HOUR=struct.Struct('<I')


def runtime_path(source_path:str)->str:
    s=source_path.replace('\\','/')
    if s.lower().startswith('servidor/'):
        s=s[len('Servidor/'):]
    elif s.lower().startswith('cliente/'):
        s=s[len('cliente/'):]
    parts=[p for p in s.split('/') if p and p!='.']
    return '/'.join(parts)

def canonical_path(s:str)->str:return runtime_path(s).lower()

def raw_first_value(doc:dict,key:str)->bytes|None:
    for d in doc.get('content',{}).get('directives',[]):
        if d.get('key')==key:
            r=d.get('raw_values_hex') or []
            if r:
                try:return bytes.fromhex(r[0])
                except ValueError:return None
    return None

def is_runtime_top_level_monster(doc:dict)->bool:
    p=PurePosixPath(doc.get('source',{}).get('path','').replace('\\','/'))
    parts=[x.casefold() for x in p.parts]
    return len(parts)==4 and parts[:3]==['servidor','gameserver','monster'] and p.suffix.casefold()=='.inf'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('shadow',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    idx=json.loads((a.shadow/'index.json').read_text(encoding='utf-8'))['documents']
    entries=[]; monsters=defaultdict(list)
    for e in idx:
        d=None
        if e['kind']=='stage_spawn':
            d=json.loads((a.shadow/e['json_path']).read_text(encoding='utf-8')); entries.append(d)
        elif e['kind']=='monster_definition':
            d=json.loads((a.shadow/e['json_path']).read_text(encoding='utf-8'))
            if is_runtime_top_level_monster(d):
                raw=raw_first_value(d,'name')
                if raw is not None: monsters[raw].append(d.get('id') or '')
    entries.sort(key=lambda d:canonical_path(d['source']['path']))
    strings=bytearray();soff={}
    def intern_bytes(b:bytes)->int:
        if b not in soff:
            if b'\0' in b: raise ValueError('NUL in string')
            soff[b]=len(strings);strings.extend(b+b'\0')
        return soff[b]
    def intern_text(s:str)->int:return intern_bytes(s.encode('utf-8'))
    empty_offset=intern_bytes(b'')
    def resolve_id(raw:bytes)->tuple[str,str]:
        ids=[x for x in monsters.get(raw,[]) if x]
        if len(ids)==1:return ids[0],'exact'
        if not ids:return '','missing'
        return '','ambiguous'

    actor_rows=[];boss_rows=[];hours=[];records=[];empty=[];relations=[]
    relation_counts=defaultdict(int)
    for d in entries:
        sem=d.get('semantic',{})
        rpath=runtime_path(d['source']['path'])
        ident=d.get('id') or ('spawn.'+Path(rpath).stem.lower())
        actor_start=len(actor_rows)
        for x in sem.get('actors',[]):
            raw=bytes.fromhex(x.get('legacy_name_bytes_hex','')) if x.get('legacy_name_bytes_hex') else str(x.get('legacy_name','')).encode('utf-8')
            monster_id,status=resolve_id(raw); relation_counts['actor_'+status]+=1
            actor_rows.append((intern_bytes(raw),intern_text(monster_id) if monster_id else empty_offset,int(x.get('weight',0))))
            if status!='exact':relations.append({'spawn':ident,'path':rpath,'role':'actor','legacy_name':x.get('legacy_name'),'status':status,'candidate_ids':monsters.get(raw,[])})
        boss_start=len(boss_rows)
        for x in sem.get('bosses',[]):
            hstart=len(hours); hs=[int(v) for v in x.get('open_hours',[])];hours.extend(hs)
            master=bytes.fromhex(x.get('master_legacy_name_bytes_hex','')) if x.get('master_legacy_name_bytes_hex') else str(x.get('master_legacy_name','')).encode('utf-8')
            slave=bytes.fromhex(x.get('slave_legacy_name_bytes_hex','')) if x.get('slave_legacy_name_bytes_hex') else str(x.get('slave_legacy_name','')).encode('utf-8')
            mid,ms=resolve_id(master);sid,ss=resolve_id(slave);relation_counts['boss_master_'+ms]+=1;relation_counts['boss_slave_'+ss]+=1
            boss_rows.append((intern_bytes(master),intern_bytes(slave),intern_text(mid) if mid else empty_offset,intern_text(sid) if sid else empty_offset,int(x.get('slave_count',0)),hstart,len(hs)))
            if ms!='exact':relations.append({'spawn':ident,'path':rpath,'role':'boss_master','legacy_name':x.get('master_legacy_name'),'status':ms,'candidate_ids':monsters.get(master,[])})
            if ss!='exact':relations.append({'spawn':ident,'path':rpath,'role':'boss_slave','legacy_name':x.get('slave_legacy_name'),'status':ss,'candidate_ids':monsters.get(slave,[])})
        delay=sem.get('delay') or {}; shift=int(delay.get('shift',7))
        if shift<0 or shift>=30:raise ValueError(f'{rpath}: invalid delay shift {shift}')
        open_interval=(1<<shift);open_interval=open_interval-1 if open_interval>1 else open_interval
        interval_ms=int(delay.get('milliseconds',0));limit=sem.get('max_actor_position');limit=0 if limit is None else int(limit);open_limit=sem.get('max_actor');open_limit=3 if open_limit is None else int(open_limit)
        records.append((intern_text(canonical_path(rpath)),intern_text(ident),limit,open_interval,interval_ms,open_limit,actor_start,len(actor_rows)-actor_start,boss_start,len(boss_rows)-boss_start))
        if len(actor_rows)==actor_start and len(boss_rows)==boss_start:empty.append(rpath)
    header_size=HEADER.size;record_off=header_size;actor_off=record_off+len(records)*RECORD.size;boss_off=actor_off+len(actor_rows)*ACTOR.size;hour_off=boss_off+len(boss_rows)*BOSS.size;string_off=hour_off+len(hours)*HOUR.size
    body=bytearray()
    for r in records:body.extend(RECORD.pack(*r))
    for r in actor_rows:body.extend(ACTOR.pack(*r))
    for r in boss_rows:body.extend(BOSS.pack(*r))
    for h in hours:body.extend(HOUR.pack(h))
    body.extend(strings);digest=hashlib.sha256(body).digest()
    header=HEADER.pack(MAGIC,VERSION,0,len(records),record_off,len(actor_rows),actor_off,len(boss_rows),boss_off,len(hours),hour_off,string_off,len(strings),digest)
    a.output.write_bytes(header+body)
    report=a.output.with_suffix(a.output.suffix+'.report.json')
    report.write_text(json.dumps({'format_version':VERSION,'records':len(records),'actors':len(actor_rows),'bosses':len(boss_rows),'hours':len(hours),'empty_spawn_files':empty,'monster_relations':dict(relation_counts),'unresolved_or_ambiguous_relations':relations,'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'written={a.output} version={VERSION} maps={len(records)} actors={len(actor_rows)} bosses={len(boss_rows)} empty={len(empty)} relation_issues={len(relations)} bytes={a.output.stat().st_size}')
if __name__=='__main__':main()
