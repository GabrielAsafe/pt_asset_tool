#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,shutil
from collections import defaultdict,Counter
from pathlib import Path,PurePosixPath

def norm(s):
    parts=[]
    for p in s.replace('\\','/').split('/'):
        if not p or p=='.': continue
        if p=='..':
            if parts: parts.pop()
        else: parts.append(p)
    return '/'.join(parts)
def runtime(s):
    s=norm(s); low=s.casefold()
    if low.startswith('servidor/'): return s[len('Servidor/'):]
    if low.startswith('cliente/'): return s[len('cliente/'):]
    return s
def raw_name(d):
    for x in d.get('semantic',{}).get('directives',[]):
        if x.get('key')=='name' and x.get('raw_values_hex'):
            try:return bytes.fromhex(x['raw_values_hex'][0])
            except ValueError:return None
    return None
def top_monster(d):
    p=PurePosixPath(d['source']['legacy_path'].replace('\\','/'))
    parts=[x.casefold() for x in p.parts]
    return len(parts)==4 and parts[:3]==['servidor','gameserver','monster'] and p.suffix.casefold()=='.inf'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--shadow',type=Path,required=True);ap.add_argument('--canonical-text',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    out=a.out.resolve();sh=a.shadow.resolve();cr=a.canonical_text.resolve()
    if out.exists():shutil.rmtree(out)
    (out/'spawns').mkdir(parents=True)
    monster_by_name=defaultdict(list)
    cidx=json.loads((cr/'index.json').read_text(encoding='utf-8'))['documents']
    for e in cidx:
        if e['kind']!='monster_definition':continue
        d=json.loads((cr/e['json_path']).read_text(encoding='utf-8'))
        if top_monster(d):
            raw=raw_name(d)
            if raw is not None:monster_by_name[raw].append(d['id'])
    # Explicit compatibility decisions after audit.
    override={(b'Cavaleiro Fantasma','actor'):'monster.60_cavaleiro_fantasma',(b'Cavaleiro Fantasma','boss_slave'):'monster.60_cavaleiro_fantasma'}
    sidx=json.loads((sh/'index.json').read_text(encoding='utf-8'))['documents'];manifest=[];stats=Counter();issues=[]
    for e in sidx:
        if e['kind']!='stage_spawn':continue
        d=json.loads((sh/e['json_path']).read_text(encoding='utf-8'));sem=d.get('semantic',{});rp=runtime(d['source']['path'])
        def resolve(raw,role):
            ids=monster_by_name.get(raw,[])
            if (raw,role) in override:return override[(raw,role)],'explicit_compatibility_override',ids
            if len(ids)==1:return ids[0],'exact',ids
            if not ids:return '','legacy_skip_if_missing',ids
            return '','ambiguous',ids
        actors=[]
        for x in sem.get('actors',[]):
            raw=bytes.fromhex(x.get('legacy_name_bytes_hex','')) if x.get('legacy_name_bytes_hex') else str(x.get('legacy_name','')).encode('utf-8')
            mid,status,cands=resolve(raw,'actor');stats['actor_'+status]+=1
            if status=='ambiguous':issues.append({'spawn':d['id'],'role':'actor','name_hex':raw.hex(),'candidates':cands})
            actors.append({'monster_id':mid,'legacy_name':x.get('legacy_name',''),'legacy_name_bytes_hex':raw.hex(),'weight':int(x.get('weight',0)),'resolution':status})
        bosses=[]
        for x in sem.get('bosses',[]):
            mr=bytes.fromhex(x.get('master_legacy_name_bytes_hex','')) if x.get('master_legacy_name_bytes_hex') else str(x.get('master_legacy_name','')).encode('utf-8')
            sr=bytes.fromhex(x.get('slave_legacy_name_bytes_hex','')) if x.get('slave_legacy_name_bytes_hex') else str(x.get('slave_legacy_name','')).encode('utf-8')
            mid,ms,mc=resolve(mr,'boss_master');sid,ss,sc=resolve(sr,'boss_slave');stats['boss_master_'+ms]+=1;stats['boss_slave_'+ss]+=1
            if ms=='ambiguous':issues.append({'spawn':d['id'],'role':'boss_master','name_hex':mr.hex(),'candidates':mc})
            if ss=='ambiguous':issues.append({'spawn':d['id'],'role':'boss_slave','name_hex':sr.hex(),'candidates':sc})
            bosses.append({'master_monster_id':mid,'slave_monster_id':sid,'master_legacy_name':x.get('master_legacy_name',''),'slave_legacy_name':x.get('slave_legacy_name',''),'master_legacy_name_bytes_hex':mr.hex(),'slave_legacy_name_bytes_hex':sr.hex(),'slave_count':int(x.get('slave_count',0)),'open_hours':[int(v) for v in x.get('open_hours',[])],'master_resolution':ms,'slave_resolution':ss})
        doc={'schema':'summit.stage-spawn/v1','schema_version':1,'id':d.get('id'),'logical_path':rp,'legacy_source':{'path':d['source']['path'],'sha256':d['source']['sha256']},'limit_max':0 if sem.get('max_actor_position') is None else int(sem['max_actor_position']),'delay':sem.get('delay'),'open_limit':3 if sem.get('max_actor') is None else int(sem['max_actor']),'actors':actors,'bosses':bosses}
        rel=Path('spawns')/(rp+'.json');dest=out/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest.append({'id':doc['id'],'logical_path':rp,'json_path':rel.as_posix()})
    manifest.sort(key=lambda x:x['logical_path'].casefold());(out/'index.json').write_text(json.dumps({'schema':'summit.stage-spawn-index/v1','documents':manifest},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'spawns':len(manifest),'relations':dict(stats),'unresolved_ambiguous':issues,'explicit_overrides':{'Cavaleiro Fantasma':'monster.60_cavaleiro_fantasma','Itens 165':'legacy_skip_if_missing'}};(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if issues:raise SystemExit('ambiguous stage-spawn relations remain')
if __name__=='__main__':main()
