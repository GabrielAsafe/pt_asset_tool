#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


def norm_path(s: str) -> str:
    return s.replace('\\', '/').replace('//', '/').strip('/').casefold()


def load_docs(shadow: Path):
    index = json.loads((shadow/'index.json').read_text(encoding='utf-8'))['documents']
    for rec in index:
        p = shadow/rec['json_path']
        yield rec, json.loads(p.read_text(encoding='utf-8'))


def raw_first_value(doc: dict, key: str) -> bytes | None:
    for d in doc.get('content',{}).get('directives',[]):
        if d.get('key') == key:
            raw=d.get('raw_values_hex') or []
            if raw:
                try:return bytes.fromhex(raw[0])
                except ValueError:return None
    return None


def source_dir(path: str) -> PurePosixPath:
    return PurePosixPath(path.replace('\\','/')).parent


def resolve_relative(source_path: str, relative: str) -> str:
    rel = relative.replace('\\','/')
    # Legacy BuildPathFromFileDirectory treats it as file-relative rather than root-relative.
    return str(source_dir(source_path)/PurePosixPath(rel))


def suggested_unique_id(doc: dict) -> str | None:
    kind=doc.get('kind'); src=doc.get('source',{}).get('path','').replace('\\','/')
    p=PurePosixPath(src)
    roots={
      'monster_definition':'Servidor/GameServer/Monster',
      'npc_definition':'Servidor/GameServer/NPC',
      'open_item_definition':'Servidor/GameServer/OpenItem',
      'stage_spawn':'Servidor/GameServer/Field',
      'localization_resource':'Servidor/GameServer',
    }
    root=roots.get(kind)
    if not root or not src.casefold().startswith(root.casefold()+'/'):
        return doc.get('id')
    rel=src[len(root)+1:]
    # Strip only the outer authored extension; for foo.ase.spm retain map stem foo.
    low=rel.lower()
    for suffix in ('.ase.spm','.spm','.inf','.npc','.txt','.zhoon'):
        if low.endswith(suffix):
            rel=rel[:-len(suffix)]; break
    import re
    parts=[]
    for part in rel.split('/'):
        # filenames from ZIP may include #UXXXX escapes; preserve as deterministic id atoms.
        atom=re.sub(r'[^A-Za-z0-9]+','_',part).strip('_').lower()
        if atom: parts.append(atom)
    prefix={'monster_definition':'monster','npc_definition':'npc','open_item_definition':'item','stage_spawn':'spawn','localization_resource':'text'}.get(kind,'content')
    return prefix+'.'+'.'.join(parts) if parts else prefix


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--shadow',type=Path,required=True)
    ap.add_argument('--corpus',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()

    shadow=args.shadow.resolve(); corpus=args.corpus.resolve(); out=args.out.resolve()
    docs=[]; by_source={}; by_norm_source={}; by_kind=defaultdict(list)
    for rec,doc in load_docs(shadow):
        docs.append(doc); src=doc['source']['path']; by_source[src]=doc; by_norm_source[norm_path(src)]=doc; by_kind[doc['kind']].append(doc)

    issues=[]; metrics=Counter(); details={}

    # ID uniqueness: distinguish current provisional IDs from path-stable proposed IDs.
    cur=defaultdict(list); proposed=defaultdict(list)
    for d in docs:
        if d.get('id'): cur[d['id']].append(d['source']['path'])
        pid=suggested_unique_id(d)
        if pid: proposed[pid].append(d['source']['path'])
    cur_dups={k:v for k,v in cur.items() if len(v)>1}
    prop_dups={k:v for k,v in proposed.items() if len(v)>1}
    metrics['current_id_collision_keys']=len(cur_dups)
    metrics['proposed_id_collision_keys']=len(prop_dups)
    critical_prop_dups={k:v for k,v in prop_dups.items() if k.startswith(('monster.','npc.','item.','spawn.'))}
    metrics['critical_proposed_id_collision_keys']=len(critical_prop_dups)
    details['current_id_collisions']=cur_dups
    details['proposed_id_collisions']=prop_dups
    details['critical_proposed_id_collisions']=critical_prop_dups

    # Linked-file references for active authored families.
    link_results=[]
    for kind in ('monster_definition','npc_definition','open_item_definition'):
        for d in by_kind[kind]:
            fields=d.get('content',{}).get('fields',{})
            vals=fields.get('linked_file')
            if vals is None: continue
            if isinstance(vals,dict) and '$repeated' in vals: vals=vals['$repeated']
            elif not isinstance(vals,list) or (vals and not isinstance(vals[0],str)): vals=[vals]
            # A 2-item string list can theoretically be one multi-valued directive, but linked_file is scalar in loaders.
            if isinstance(vals,list) and vals and all(isinstance(x,str) for x in vals): candidates=vals
            else: candidates=[vals]
            for rel in candidates:
                if not isinstance(rel,str): continue
                target=resolve_relative(d['source']['path'],rel)
                found=by_norm_source.get(norm_path(target))
                ok=found is not None
                metrics['linked_file_total']+=1
                metrics['linked_file_found' if ok else 'linked_file_missing']+=1
                link_results.append({'source':d['source']['path'],'kind':kind,'reference':rel,'resolved':target,'found':ok,'target_kind':found.get('kind') if found else None})
    details['linked_files']=link_results

    # Stage actor -> monster exact byte name relation. This intentionally mirrors strcmp on legacy bytes.
    # InitMonster() enumerates only GameServer/monster/*.inf (non-recursive).
    runtime_monsters=[]
    for d in by_kind['monster_definition']:
        src=PurePosixPath(d['source']['path'].replace('\\','/'))
        parts=[x.casefold() for x in src.parts]
        if len(parts)>=4 and parts[0].casefold()=='servidor' and parts[1].casefold()=='gameserver' and parts[2].casefold()=='monster' and len(parts)==4:
            runtime_monsters.append(d)
    monster_names=defaultdict(list)
    for d in runtime_monsters:
        raw=raw_first_value(d,'name')
        if raw is not None:
            monster_names[raw].append(d)
    metrics['monster_definitions']=len(by_kind['monster_definition'])
    metrics['runtime_top_level_monster_definitions']=len(runtime_monsters)
    metrics['monster_definitions_with_raw_name']=sum(len(v) for v in monster_names.values())
    metrics['monster_unique_raw_names']=len(monster_names)
    stage_results=[]
    for d in by_kind['stage_spawn']:
        sem=d.get('semantic',{})
        rows=[]
        for a in sem.get('actors',[]):
            raw=bytes.fromhex(a.get('legacy_name_bytes_hex','')) if a.get('legacy_name_bytes_hex') else b''
            matches=monster_names.get(raw,[])
            status='exact' if len(matches)==1 else ('ambiguous' if len(matches)>1 else 'missing')
            metrics['stage_actor_rows']+=1; metrics['stage_actor_'+status]+=1
            rows.append({'type':'actor','legacy_name':a.get('legacy_name'),'legacy_name_bytes_hex':raw.hex(),'weight':a.get('weight'),'status':status,'matches':[m['source']['path'] for m in matches]})
        for b in sem.get('bosses',[]):
            for role,key,label in [('master','master_legacy_name_bytes_hex','master_legacy_name'),('slave','slave_legacy_name_bytes_hex','slave_legacy_name')]:
                hx=b.get(key,''); raw=bytes.fromhex(hx) if hx else b''; matches=monster_names.get(raw,[])
                status='exact' if len(matches)==1 else ('ambiguous' if len(matches)>1 else 'missing')
                metrics['stage_boss_name_rows']+=1; metrics['stage_boss_name_'+status]+=1
                rows.append({'type':'boss_'+role,'legacy_name':b.get(label),'legacy_name_bytes_hex':raw.hex(),'status':status,'matches':[m['source']['path'] for m in matches]})
        if not sem.get('actors') and not sem.get('bosses'):
            metrics['stage_files_empty']+=1
        stage_results.append({'source':d['source']['path'],'id':d.get('id'),'actor_count':len(sem.get('actors',[])),'boss_count':len(sem.get('bosses',[])),'rows':rows})
    details['stage_monster_relations']=stage_results

    # Detect byte-level likely irreversible corruption in relation-critical display/name values.
    suspect=[]
    for kind in ('monster_definition','npc_definition','open_item_definition','stage_spawn'):
        for d in by_kind[kind]:
            for directive in d.get('content',{}).get('directives',[]):
                if directive.get('key') not in ('name','english_name','actor','boss_actor','linked_file','model_file','code'): continue
                for val in directive.get('values',[]):
                    if isinstance(val,str) and ('�' in val or '?' in val or '\ufffd' in val):
                        suspect.append({'source':d['source']['path'],'line':directive.get('line'),'key':directive.get('key'),'value':val,'raw_values_hex':directive.get('raw_values_hex',[])})
    metrics['relation_critical_suspect_text_values']=len(suspect)
    details['relation_critical_suspect_values']=suspect

    # Loader status aggregate. Supported-unmapped is a blocker; not-consumed is historical/nonactive data.
    loader_status=Counter()
    not_consumed=Counter()
    for d in docs:
        for x in d.get('content',{}).get('directives',[]):
            st=x.get('loader_status')
            if st:
                loader_status[st]+=1
                if st=='not_consumed_by_active_loader': not_consumed[(d['kind'],x.get('legacy_token',''))]+=1
    metrics.update({f'loader_{k}':v for k,v in loader_status.items()})
    details['not_consumed_tokens']=[{'kind':k[0],'token':k[1],'count':v} for k,v in not_consumed.most_common()]

    # Hard blockers are conditions that prevent source-of-truth conversion without a deliberate decision.
    blockers=[]
    if metrics.get('loader_supported_unmapped',0): blockers.append({'type':'supported_unmapped_tokens','count':metrics['loader_supported_unmapped']})
    if critical_prop_dups: blockers.append({'type':'critical_proposed_id_collisions','count':len(critical_prop_dups)})
    # Missing legacy links are reported, but not all are runtime-fatal: historical loader often ends parsing successfully.
    # Missing stage actor names ARE semantic runtime mismatches because strcmp cannot resolve them.
    if metrics.get('stage_actor_missing',0): blockers.append({'type':'unresolved_stage_actor_names','count':metrics['stage_actor_missing']})
    if metrics.get('stage_boss_name_missing',0): blockers.append({'type':'unresolved_stage_boss_names','count':metrics['stage_boss_name_missing']})

    report={'schema':'summit.text-relations-report/v1','shadow':'.','corpus':corpus.name,'metrics':dict(metrics),'blockers':blockers,'details':details}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    md=[]
    md += ['# Summit text corpus relation audit','']
    md += [f'- Documents: **{len(docs)}**', f'- Active mapped directives: **{metrics.get("loader_supported_mapped",0)}**', f'- Active but unmapped directives: **{metrics.get("loader_supported_unmapped",0)}**', f'- Directives not consumed by active loader: **{metrics.get("loader_not_consumed_by_active_loader",0)}**','']
    md += ['## Stage spawn → monster exact legacy-name relation','']
    md += [f'- Actor rows: **{metrics.get("stage_actor_rows",0)}**', f'- Exact: **{metrics.get("stage_actor_exact",0)}**', f'- Ambiguous duplicate names: **{metrics.get("stage_actor_ambiguous",0)}**', f'- Missing: **{metrics.get("stage_actor_missing",0)}**', f'- Boss name rows: **{metrics.get("stage_boss_name_rows",0)}**', f'- Empty SPM files: **{metrics.get("stage_files_empty",0)}**','']
    missing=[s for s in stage_results if any(r['status']=='missing' for r in s['rows'])]
    if missing:
        md += ['### SPM files with unresolved names','']
        for s in missing:
            vals=[r['legacy_name'] for r in s['rows'] if r['status']=='missing']
            md.append(f'- `{s["source"]}`: '+', '.join(f'`{v}`' for v in vals))
        md.append('')
    md += ['## Linked files','', f'- References: **{metrics.get("linked_file_total",0)}**', f'- Found case-insensitively in supplied corpus: **{metrics.get("linked_file_found",0)}**', f'- Missing: **{metrics.get("linked_file_missing",0)}**','']
    missing_links=[r for r in link_results if not r['found']]
    for r in missing_links[:100]: md.append(f'- `{r["source"]}` → `{r["reference"]}` (expected `{r["resolved"]}`)')
    if len(missing_links)>100: md.append(f'- ... {len(missing_links)-100} more in JSON report')
    md += ['', '## IDs','', f'- Current provisional collision keys: **{len(cur_dups)}**', f'- Proposed path-qualified collision keys (all documents): **{len(prop_dups)}**', f'- Proposed collisions in runtime content domains: **{len(critical_prop_dups)}**','']
    md += ['## Relation-critical suspicious text','', f'- Values containing `?`/replacement characters: **{len(suspect)}**','']
    for r in suspect[:100]: md.append(f'- `{r["source"]}:{r["line"]}` `{r["key"]}` = `{r["value"]}`')
    if len(suspect)>100: md.append(f'- ... {len(suspect)-100} more in JSON report')
    md += ['', '## Blockers for a lossless canonical migration','']
    if not blockers: md.append('- None found by this validator.')
    else:
        for b in blockers: md.append(f'- `{b["type"]}`: {b["count"]}')
    out.with_suffix('.md').write_text('\n'.join(md)+'\n',encoding='utf-8')

    print(json.dumps({'metrics':dict(metrics),'blockers':blockers,'json':str(out)},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
