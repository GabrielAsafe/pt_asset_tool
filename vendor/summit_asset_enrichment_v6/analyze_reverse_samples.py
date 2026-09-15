#!/usr/bin/env python3
from __future__ import annotations
import argparse, collections, csv, json, re, struct, zipfile
from pathlib import Path, PurePosixPath

SPM_ALIASES = {
    'ACTOR': ('*ACTOR', '*출연자'),
    'BOSS_ACTOR': ('*BOSS_ACTOR', '*출연자두목'),
    'MAX_ACTOR_POS': ('*MAX_ACTOR_POS', '*최대동시출현수'),
    'DELAY': ('*DELAY', '*출현간격'),
    'MAX_ACTOR': ('*MAX_ACTOR', '*출현수'),
}
IMAGE_EXTS={'.bmp','.tga','.dds','.jpg','.jpeg','.png'}
ADD_NPC_CODE=0x48470070

def decode_text(data: bytes):
    for enc in ('utf-8-sig','cp949','cp1252','latin1'):
        try: return data.decode(enc), enc
        except UnicodeDecodeError: pass
    return data.decode('latin1',errors='replace'), 'latin1'

def clean_cstr(b: bytes, enc='cp949') -> str:
    b=b.split(b'\0',1)[0]
    if not b: return ''
    for e in (enc,'utf-8','cp1252','latin1'):
        try:return b.decode(e)
        except Exception:pass
    return repr(b)

def replace_ext(path:str, ext:str)->str:
    p=path.replace('\\','/')
    if not p:return p
    return str(PurePosixPath(p).with_suffix('.'+ext.lstrip('.')))

def norm(p:str)->str:return p.replace('\\','/').lstrip('./').casefold()

def family_of(x):
    if x.get('source_family'):return x['source_family']
    if x['source_label'] in {'summit_client','summit_server'}:return 'summit'
    return x['source_label']

def parent_id(x):
    return f"{x['source_label']}:{x['side']}:{x['source_rel']}"

def parse_inx(data:bytes):
    if len(data)==95268:ms=172; layout='MODERN_172'
    elif len(data)==67084:ms=120; layout='LEGACY_120'
    else:return {'layout':'UNKNOWN','runtime_refs':[]}
    base=396+512*ms
    c=lambda a,b:clean_cstr(data[a:b])
    model=c(0,64); motion=c(64,128); sub=c(128,192); link=c(base+12,base+76); talklink=c(base+76,base+140); talkmotion=c(base+140,base+204)
    refs=[]
    def add(role,logical,ext):
        if logical:refs.append({'role':role,'logical':logical.replace('\\','/'),'runtime':replace_ext(logical,ext)})
    add('model',model,'smd');add('motion',motion,'smb');add('sub_model',sub,'inx');add('link_modelinfo',link,'inx');add('talk_link_modelinfo',talklink,'inx');add('talk_motion',talkmotion,'smb')
    return {'layout':layout,'motion_record_size':ms,'model_file':model,'motion_file':motion,'sub_model_file':sub,'link_file':link,'talk_link_file':talklink,'talk_motion_file':talkmotion,'runtime_refs':refs}

def parse_spm(data: bytes):
    text, enc=decode_text(data); result={'encoding':enc,'directives':collections.Counter(),'actors':[],'boss_actors':[]}
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith('//'): continue
        upper=line.upper(); matched=None
        for key, aliases in SPM_ALIASES.items():
            if any(upper.startswith(a.upper()) for a in aliases):result['directives'][key]+=1;matched=key;break
        if matched=='ACTOR':
            m=re.search(r'(?i)(?:\*ACTOR|\*출연자)\s+(?:"([^"]+)"|(\S+))\s+(\d+)', line)
            if m: result['actors'].append({'name':m.group(1) or m.group(2),'weight':int(m.group(3))})
        elif matched=='BOSS_ACTOR':
            m=re.search(r'(?i)(?:\*BOSS_ACTOR|\*출연자두목)\s+(?:"([^"]+)"|(\S+))\s+(?:"([^"]+)"|(\S+))\s+(\d+)', line)
            if m: result['boss_actors'].append({'master':m.group(1) or m.group(2),'slave':m.group(3) or m.group(4),'slave_count':int(m.group(5))})
    result['directives']=dict(result['directives']);return result

def parse_spp(data: bytes):
    if len(data)%12: return {'record_size':12,'valid_multiple':False}
    recs=[struct.unpack_from('<iii',data,o) for o in range(0,len(data),12)];active=[{'state':s,'x':x,'z':z} for s,x,z in recs if s]
    return {'record_size':12,'record_count':len(recs),'active_count':len(active),'active_sample':active[:12],'layout':'CURRENT_200' if len(recs)==200 else ('LEGACY_50' if len(recs)==50 else 'OTHER')}

def parse_spc(data: bytes):
    if len(data)%504:return {'record_size':504,'valid_multiple':False}
    recs=[]; runtime_active=0; standard_add_npc=0; occupied=0; blank=0; disabled_stale=0
    for idx,o in enumerate(range(0,len(data),504)):
        r=data[o:o+504];size,code=struct.unpack_from('<ii',r,0)
        if not any(r):blank+=1;continue
        occupied+=1
        tail=struct.unpack_from('<8i',r,472)
        code_u32=code & 0xffffffff; active=code_u32!=0; standard=code_u32==ADD_NPC_CODE
        if active:runtime_active+=1
        if standard:standard_add_npc+=1
        elif code_u32==0:disabled_stale+=1
        recs.append({'index':idx,'size':size,'code_u32':code_u32,'runtime_active':active,'standard_add_npc_code':standard,'name':clean_cstr(r[8:40]),'model_ini':clean_cstr(r[40:104]),'server_npc':clean_cstr(r[104:164]),'object_serial_u32':tail[0]&0xffffffff,'x':tail[1],'y':tail[2],'z':tail[3],'ax':tail[4],'ay':tail[5],'az':tail[6],'state':tail[7]})
    return {'record_size':504,'record_count':len(data)//504,'occupied_record_count':occupied,'runtime_active_count':runtime_active,'standard_add_npc_count':standard_add_npc,'blank_slot_count':blank,'disabled_stale_count':disabled_stale,'records':recs}

def text_refs(data:bytes):
    text,_=decode_text(data)
    refs=re.findall(r'(?i)([A-Za-z0-9_ .@+\-\\/]+\.(?:ini|in|inx|npc|zhoon|smd|smb|ase|bmp|tga|dds|jpg|jpeg|png))',text)
    return [r.strip().strip('"\'') for r in refs]

def resolve(index,family,path):
    return index.get((family,norm(path)))

def closure_bundle(bundle, family_rel_nodes, event_adj):
    roots=family_rel_nodes.get((bundle['family'],norm(bundle['server_def'])),[])
    result={'closure_root':roots[0] if roots else '', 'runtime_missing':[], 'textures':[], 'visited_nodes':0}
    if not roots:return result
    q=[roots[0]];seen=set()
    while q:
        node=q.pop(0)
        if node in seen:continue
        seen.add(node)
        for e in event_adj.get(node,[]):
            rel=e.get('relation',''); req=e.get('requested',''); ext=PurePosixPath(req.replace('\\','/')).suffix.lower()
            follow=False
            if rel=='modelinfo_runtime_alias' or (rel.startswith('inx_') and rel.endswith('_runtime')):
                follow=True
                if e.get('status')!='RESOLVED':result['runtime_missing'].append({'parent':node,'relation':rel,'requested':req})
            elif rel=='binary_literal' and ext in IMAGE_EXTS:
                result['textures'].append({'parent':node,'requested':req,'status':e.get('status','MISSING'),'resolved_rel':e.get('resolved_rel',''),'resolved_source_label':e.get('resolved_source_label',''),'resolved_side':e.get('resolved_side','')})
            if follow and e.get('status')=='RESOLVED':
                q.append(f"{e['resolved_source_label']}:{e['resolved_side']}:{e['resolved_rel']}")
    result['visited_nodes']=len(seen)
    return result

def build_bundles(z,manifest,index,closure=None):
    family_rel_nodes=collections.defaultdict(list)
    for x in manifest: family_rel_nodes[(family_of(x),norm(x['source_rel']))].append(parent_id(x))
    event_adj=collections.defaultdict(list)
    if closure:
        for e in closure.get('events',[]):event_adj[e['parent']].append(e)
    bundles=[]
    for x in manifest:
        rel=x['source_rel'];ext=Path(rel).suffix.lower(); lower=rel.replace('\\','/').casefold()
        if not ((ext=='.inf' and '/gameserver/monster/' in '/'+lower) or (ext=='.npc' and '/gameserver/npc/' in '/'+lower)):continue
        family=family_of(x);data=z.read(x['archive_rel']);refs=text_refs(data)
        model=next((r for r in refs if Path(r.replace('\\','/')).suffix.lower() in {'.ini','.in','.inx'} and ('char/' in r.replace('\\','/').casefold())), '')
        loc=next((r for r in refs if r.lower().endswith('.zhoon')), '')
        model_inx=replace_ext(model,'inx') if model else ''
        inx_entry=resolve(index,family,model_inx) if model_inx else None
        inx_info=None;runtime=[]
        if inx_entry:
            inx_info=parse_inx(z.read(inx_entry['archive_rel']))
            for rr in inx_info.get('runtime_refs',[]):
                target=resolve(index,family,rr['runtime'])
                runtime.append({'role':rr['role'],'logical':rr['logical'],'runtime':rr['runtime'],'present':bool(target),'target':target['source_rel'] if target else ''})
        loc_target=None
        if loc:
            loc_rel=str(PurePosixPath(rel.replace('\\','/')).parent / loc.replace('\\','/'))
            loc_target=resolve(index,family,loc_rel) or resolve(index,family,loc)
        bundle={
            'family':family,'kind':'monster' if ext=='.inf' else 'npc','server_def':rel,'model_logical':model,'model_inx':model_inx,
            'model_inx_present':bool(inx_entry),'localization_ref':loc,'localization_present':bool(loc_target) if loc else None,
            'localization_target':loc_target['source_rel'] if loc_target else '',
            'authoring_descriptor_present':bool(resolve(index,family,model)) if model else None,'inx':inx_info,'runtime_dependencies':runtime,
        }
        essential=[r for r in runtime if r['role'] in {'model','motion'}]
        bundle['runtime_visual_complete']=bool(inx_entry) and bool(essential) and all(r['present'] for r in essential)
        if closure:
            c=closure_bundle(bundle,family_rel_nodes,event_adj);bundle.update(c)
            bundle['texture_dependencies']=c['textures']
            bundle['texture_complete']=not any(t['status']!='RESOLVED' for t in c['textures'])
            bundle['runtime_closure_complete']=bool(inx_entry) and not c['runtime_missing']
        else:
            bundle['texture_dependencies']=[];bundle['texture_complete']=None;bundle['runtime_closure_complete']=bundle['runtime_visual_complete']
        layout=(inx_info or {}).get('layout')
        bundle['current_summit_inx_compatible']=layout=='MODERN_172'
        loc_ok=(bundle['localization_present'] is not False)
        tex_ok=bundle['texture_complete'] is not False
        bundle['summit_ready_complete']=bool(inx_entry) and bundle['runtime_closure_complete'] and tex_ok and loc_ok and bundle['current_summit_inx_compatible']
        bundles.append(bundle)
    return bundles

def md_report(summary:dict)->str:
    lines=['# Summit reverse corpus — findings','',f"Corpus: **{summary['total_samples']} samples**, {len(summary['by_ext'])} extensions.",'',
           '## Deterministic layout findings','',
           '- **INX 95,268 bytes = MODERN_172**: current Summit `smMODELINFO`, `MOTION_TOOL_MAX=104`, `smMOTIONINFO=172`.',
           '- **INX 67,084 bytes = LEGACY_120**: older layout (`MOTION_TOOL_MAX=52`, `smMOTIONINFO=120`); not native to the current 95,268-byte Summit loader.',
           '- **Physical `.INI` is not a runtime requirement when the corresponding `.INX` exists**: `smModelDecode()` calls `smFindFile(logicalPath, "inx")`.',
           '- **INX runtime chain is typed**: `szModelFile(.ASE) → .SMD`, `szMotionFile(.ASE) → .SMB`, link descriptors `.INI/.IN → .INX`.',
           '- **SPP 2,400 bytes = current canonical**: 200 records × 12 bytes `{int state,int x,int z}`; 600 bytes is the legacy 50-record form.',
           '- **SPC 50,400 bytes = current canonical**: 100 × 504-byte `smTRNAS_PLAYERINFO`; runtime opens records when `code != 0`; every active code observed in this corpus is the standard `0x48470070 (smTRANSCODE_ADD_NPC)`.',
           '- **SPC `dwObjectSerial` is ephemeral**: `OpenNpc()` replaces it with `GetNewObjectSerial()` at runtime, so a writer must not preserve a donor serial as identity.',
           '- **SPM is text**, normally CP949 in historical data; current source also accepts English aliases for spawn directives.','',
           '## Corpus coverage','', '| extension | samples | observed sizes |','|---|---:|---|']
    for ext,d in sorted(summary['by_ext'].items()):
        sizes=', '.join(f"{k}×{v}" for k,v in sorted(((int(k),v) for k,v in d['sizes'].items())))
        lines.append(f"| `{ext}` | {d['count']} | {sizes} |")
    lines += ['', '## Runtime character bundles', '', '| family | kind | server definition | INX | runtime chain | textures | Summit-ready |', '|---|---|---|---|---|---|---|']
    for b in summary.get('bundles',[])[:100]:
        run='OK' if b.get('runtime_closure_complete') else 'MISSING'
        tex='OK' if b.get('texture_complete') else ('MISSING' if b.get('texture_complete') is False else 'N/A')
        lines.append(f"| `{b['family']}` | {b['kind']} | `{b['server_def']}` | {'OK' if b['model_inx_present'] else 'MISSING'} | {run} | {tex} | {'YES' if b.get('summit_ready_complete') else 'NO'} |")
    ini_count=summary['by_ext'].get('.ini',{}).get('count',0); char_ini=summary.get('character_ini_count',0)
    base_complete=sum(1 for b in summary.get('bundles',[]) if b.get('runtime_visual_complete'))
    tex_complete=sum(1 for b in summary.get('bundles',[]) if b.get('runtime_closure_complete') and b.get('texture_complete'))
    ready=sum(1 for b in summary.get('bundles',[]) if b.get('summit_ready_complete'))
    lines += ['', '## Bundle closure gate', '']
    lines.append(f"- Basic `INX → SMD/SMB` closure: **{base_complete}/{len(summary.get('bundles',[]))}**.")
    lines.append(f"- Recursive runtime + texture closure: **{tex_complete}/{len(summary.get('bundles',[]))}**.")
    lines.append(f"- Native Summit-ready bundles (`MODERN_172` + localization + recursive runtime + textures): **{ready}/{len(summary.get('bundles',[]))}**.")
    missing=collections.Counter()
    for b in summary.get('bundles',[]):
        for e in b.get('runtime_missing',[]):missing[f"runtime:{e['requested']}"]+=1
        for t in b.get('texture_dependencies',[]):
            if t.get('status')!='RESOLVED':missing[f"texture:{t['requested']}"]+=1
    if missing:
        lines += ['', '### Repeated unresolved bundle dependencies','']
        for k,v in missing.most_common():lines.append(f"- `{k}` × {v}")
    lines += ['', '## Other gaps / evidence quality', '']
    lines.append(f"- The corpus contains **{ini_count} `.ini` files**, of which **{char_ini}** are under `char/npc` or `char/monster`. Physical character `.INI` remains authoring evidence, not necessarily a runtime dependency.")
    empties=summary.get('empty_files',{})
    if empties:lines.append('- Empty evidence files remain present: '+', '.join(f"`{k}`={v}" for k,v in sorted(empties.items()))+'. Keep them as provenance, never as templates.')
    lines += ['', '## Recommended authoring confidence', '', '| family | status |','|---|---|',
              '| SPP current writer | GREEN |','| SPM template/writer | GREEN after actor-name validation against loaded monster list |','| SPC parser/dumper | GREEN |','| SPC clone-based record writer | GREEN with a known-good active donor record, exact 50,400-byte file, base SHA-256 guard, and transactional replacement |','| SPC synthetic-from-zero writer | BLOCKED — unknown `smCHAR_INFO` semantics should not be invented |','| INX classify/read/core dependency parse | GREEN |','| INX roundtrip | GREEN only through the already-certified PT Asset Tool path |','| Full new NPC/monster bundle | GREEN when the v6 `summit_ready_complete` gate passes; 3D authoring remains delegated to PT Asset Tool |','']
    return '\n'.join(lines)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('zip');ap.add_argument('--out-dir',default='reverse_analysis');args=ap.parse_args()
    zpath=Path(args.zip);out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        manifest=json.loads(z.read('manifest.json'));byext={};index={}
        for x in manifest:
            ext=Path(x['source_rel']).suffix.lower();d=byext.setdefault(ext,{'count':0,'sizes':collections.Counter()});d['count']+=1;d['sizes'][x['size']]+=1
            index[(family_of(x),norm(x['source_rel']))]=x
        for d in byext.values():d['sizes']=dict(d['sizes'])
        closure=json.loads(z.read('closure_report.json')) if 'closure_report.json' in z.namelist() else None
        result={'total_samples':len(manifest),'by_side':dict(collections.Counter(x['side'] for x in manifest)),'by_label':dict(collections.Counter(x['source_label'] for x in manifest)),'by_ext':byext,'inx':[],'spp':[],'spc':[],'spm':[]}
        empties=collections.Counter()
        for x in manifest:
            ext=Path(x['source_rel']).suffix.lower();data=z.read(x['archive_rel']);base={'source_label':x['source_label'],'family':family_of(x),'side':x['side'],'source_rel':x['source_rel'],'size':len(data)}
            if len(data)==0:empties[ext]+=1
            if ext=='.inx':base.update(parse_inx(data));result['inx'].append(base)
            elif ext=='.spp':base['analysis']=parse_spp(data);result['spp'].append(base)
            elif ext=='.spc':base['analysis']=parse_spc(data);result['spc'].append(base)
            elif ext=='.spm':base['analysis']=parse_spm(data);result['spm'].append(base)
        result['character_ini_count']=sum(1 for x in manifest if Path(x['source_rel']).suffix.lower()=='.ini' and re.search(r'(?i)(?:^|/)char/(?:npc|monster)/',x['source_rel'].replace('\\','/')))
        result['empty_files']=dict(empties);result['bundles']=build_bundles(z,manifest,index,closure)
        if closure:result['collector_closure']=closure['summary']
    (out/'reverse_findings.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8');(out/'REVERSE_CORPUS_FINDINGS.md').write_text(md_report(result),encoding='utf-8')
    with (out/'spc_records.csv').open('w',newline='',encoding='utf-8') as f:
        cols=['source_label','source_rel','index','runtime_active','name','model_ini','server_npc','object_serial_u32','x','y','z','ax','ay','az','state','code_u32'];w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for s in result['spc']:
            for r in s['analysis']['records']:w.writerow({'source_label':s['source_label'],'source_rel':s['source_rel'],**{k:r[k] for k in cols if k in r}})
    print(json.dumps({'samples':len(manifest),'out_dir':str(out.resolve()),'inx_layouts':dict(collections.Counter(x['layout'] for x in result['inx'])),'bundles':len(result['bundles']),'basic_runtime_complete':sum(1 for b in result['bundles'] if b['runtime_visual_complete']),'runtime_texture_complete':sum(1 for b in result['bundles'] if b.get('runtime_closure_complete') and b.get('texture_complete')),'summit_ready_complete':sum(1 for b in result['bundles'] if b.get('summit_ready_complete'))},indent=2,ensure_ascii=False))
if __name__=='__main__':main()
