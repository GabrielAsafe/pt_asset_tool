#!/usr/bin/env python3
"""Collect representative assets plus source/runtime dependency closure into a provenance ZIP."""
from __future__ import annotations
import argparse, json, shutil, zipfile
from collections import defaultdict, deque, Counter
from dataclasses import dataclass
from pathlib import Path
from asset_common import CaseIndex, extract_binary_refs, extract_text_refs, norm_rel, sha256_file
from reverse_inspect import inspect_one, parse_inx_core, replace_ext

HERE=Path(__file__).resolve().parent
TYPES=['.inx','.ini','.in','.smd','.smb','.spm','.spp','.spc','.inf','.npc','.zhoon','.bmp','.tga','.dds','.jpg','.jpeg','.png','.ase']
TEXT_REF_EXT={'.ini','.in','.inf','.npc','.zhoon','.spm','.txt'}

@dataclass(frozen=True)
class RootCtx:
    label:str; side:str; root:Path; family:str

@dataclass(frozen=True)
class RefSpec:
    ref:str
    relation:str='literal'


def load_cfg(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def roots_from_cfg(cfg):
    out=[RootCtx('summit_client','client',Path(cfg['target_client']).expanduser(),'summit'),RootCtx('summit_server','server',Path(cfg['target_server']).expanduser(),'summit')]
    for d in cfg.get('donors',[]): out.append(RootCtx(d['label'],d['side'],Path(d['root']).expanduser(),d.get('family') or d['label']))
    return [x for x in out if x.root.exists()]

def score(path):
    size=path.stat().st_size; ext=path.suffix.casefold(); special=9
    if ext=='.inx' and size in (95268,67084):special=0
    elif ext=='.spp' and size in (2400,600):special=0
    elif ext=='.spc' and size==50400:special=0
    elif ext in {'.smd','.smb'}:
        head=path.read_bytes()[:96]
        if b'SMD Model data Ver 0.62' in head:special=0
        elif b'SMD Stage data Ver 0.72' in head:special=1
    elif ext in {'.spm','.inf','.npc','.zhoon','.ini','.in'}:special=1
    return special,size,path.as_posix().casefold()

def dedup_specs(specs):
    out=[]; seen=set()
    for s in specs:
        key=(norm_rel(s.ref).casefold(),s.relation)
        if s.ref and key not in seen:
            seen.add(key);out.append(s)
    return out

def ref_specs_for(p:Path):
    ext=p.suffix.casefold(); specs=[]
    try:
        if ext=='.inx':
            core=parse_inx_core(p.read_bytes())
            for r in core.get('runtime_refs',[]):
                logical=r.get('logical',''); runtime=r.get('runtime','')
                if logical:specs.append(RefSpec(logical,f"inx_{r['role']}_source"))
                if runtime and runtime.casefold()!=logical.casefold():specs.append(RefSpec(runtime,f"inx_{r['role']}_runtime"))
            # Keep any other literal binary references as evidence.
            typed={norm_rel(s.ref).casefold() for s in specs}
            for ref in extract_binary_refs(p):
                if norm_rel(ref).casefold() not in typed:specs.append(RefSpec(ref,'binary_literal'))
        elif ext in TEXT_REF_EXT:
            for ref in extract_text_refs(p):
                specs.append(RefSpec(ref,'text_literal'))
                # smModelDecode accepts logical .INI/.IN paths while runtime can be only .INX.
                if Path(ref.replace('\\','/')).suffix.casefold() in {'.ini','.in'}:
                    specs.append(RefSpec(replace_ext(ref,'inx'),'modelinfo_runtime_alias'))
        else:
            specs.extend(RefSpec(ref,'binary_literal') for ref in extract_binary_refs(p))
    except Exception:
        return []
    return dedup_specs(specs)

def candidate_rels(ctx,p,ref):
    ref=norm_rel(ref); vals=[ref]
    try:
        parent=p.parent.relative_to(ctx.root).as_posix(); vals.append(norm_rel(parent+'/'+ref))
    except ValueError:pass
    seen=[]; folded=set()
    for v in vals:
        k=v.casefold()
        if v and k not in folded:seen.append(v);folded.add(k)
    return seen

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',default=str(HERE/'summit_paths.json')); ap.add_argument('--out',default='summit_reverse_samples.zip'); ap.add_argument('--per-type',type=int,default=3); ap.add_argument('--max-file-mb',type=int,default=16); ap.add_argument('--max-total-mb',type=int,default=180); ap.add_argument('--max-followed',type=int,default=600); ap.add_argument('--no-follow-references',action='store_true')
    a=ap.parse_args(); cfg=load_cfg(a.config); roots=roots_from_cfg(cfg); max_file=a.max_file_mb*1024*1024; max_total=a.max_total_mb*1024*1024
    pool=defaultdict(list); indexes={}
    for c in roots:
        indexes[(c.label,c.side,str(c.root.resolve()))]=CaseIndex(c.root)
        for p in c.root.rglob('*'):
            if p.is_file() and p.suffix.casefold() in TYPES and p.stat().st_size<=max_file: pool[(c.label,c.side,str(c.root.resolve()),p.suffix.casefold())].append(p)
    chosen=[]; keys=set(); total=0
    resolution_events=[]
    def add(c,p,reason,parent='',relation=''):
        nonlocal total
        key=(c.label,c.side,str(c.root.resolve()),str(p.resolve()))
        if key in keys or not p.is_file() or p.stat().st_size>max_file or total+p.stat().st_size>max_total:return False
        keys.add(key); chosen.append((c,p,reason,parent,relation)); total+=p.stat().st_size; return True
    for c in roots:
        for ext in TYPES:
            candidates=sorted(pool.get((c.label,c.side,str(c.root.resolve()),ext),[]),key=score); picked=0; seen_shape=set()
            for p in candidates:
                shape=p.stat().st_size if ext in {'.inx','.spp','.spc'} else p.name.casefold()
                if ext in {'.inx','.spp','.spc'} and shape in seen_shape:continue
                if add(c,p,'representative'):
                    seen_shape.add(shape); picked+=1
                if picked>=a.per_type:break
    if not a.no_follow_references:
        q=deque(chosen); followed=0
        by_family=defaultdict(list)
        for c in roots:by_family[c.family].append(c)
        attempted=set()
        while q and followed<a.max_followed:
            c,p,reason,parent,relation=q.popleft(); parent_id=f'{c.label}:{c.side}:{p.relative_to(c.root).as_posix()}'
            for spec in ref_specs_for(p):
                attempt_key=(parent_id,norm_rel(spec.ref).casefold(),spec.relation)
                if attempt_key in attempted:continue
                attempted.add(attempt_key)
                found=None
                for rel in candidate_rels(c,p,spec.ref):
                    order=[c]+[x for x in by_family[c.family] if x!=c]
                    for rc in order:
                        idx=indexes[(rc.label,rc.side,str(rc.root.resolve()))]; cand=idx.find(rel)
                        if cand:found=(rc,cand,rel);break
                    if found:break
                if not found:
                    basename=Path(norm_rel(spec.ref)).name; hits=[]
                    if basename:
                        for rc in by_family[c.family]:
                            idx=indexes[(rc.label,rc.side,str(rc.root.resolve()))]
                            hits += [(rc,x) for x in idx.find_basename(basename)]
                    if len(hits)==1:found=(hits[0][0],hits[0][1],basename)
                if found:
                    rc,cand,resolved_rel=found
                    added=add(rc,cand,'reference',parent_id,spec.relation)
                    resolution_events.append({'parent':parent_id,'family':c.family,'relation':spec.relation,'requested':norm_rel(spec.ref),'status':'RESOLVED','resolved_source_label':rc.label,'resolved_side':rc.side,'resolved_rel':cand.relative_to(rc.root).as_posix(),'added':added})
                    if added:
                        q.append((rc,cand,'reference','',spec.relation)); followed+=1
                else:
                    resolution_events.append({'parent':parent_id,'family':c.family,'relation':spec.relation,'requested':norm_rel(spec.ref),'status':'MISSING'})
    out=Path(a.out); stage=out.with_suffix('')
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir(parents=True); reports=[]; manifest=[]
    for c,p,reason,parent,relation in chosen:
        rel=p.relative_to(c.root).as_posix(); dst=stage/'samples'/c.label/c.side/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst)
        rep=inspect_one(p); rep.update({'source_label':c.label,'source_side':c.side,'source_family':c.family,'source_root':str(c.root),'source_rel':rel,'archive_rel':dst.relative_to(stage).as_posix(),'collection_reason':reason,'reference_parent':parent,'reference_relation':relation}); reports.append(rep)
        manifest.append({'source_label':c.label,'source_family':c.family,'side':c.side,'source_rel':rel,'size':p.stat().st_size,'sha256':sha256_file(p),'archive_rel':dst.relative_to(stage).as_posix(),'collection_reason':reason,'reference_parent':parent,'reference_relation':relation})
    (stage/'reverse_report.json').write_text(json.dumps(reports,indent=2,ensure_ascii=False),encoding='utf-8'); (stage/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    status=Counter(e['status'] for e in resolution_events); relation_counts=Counter((e['relation'],e['status']) for e in resolution_events)
    closure={'events':resolution_events,'summary':{'events':len(resolution_events),'resolved':status['RESOLVED'],'missing':status['MISSING'],'by_relation':{f'{k[0]}::{k[1]}':v for k,v in sorted(relation_counts.items())}}}
    (stage/'closure_report.json').write_text(json.dumps(closure,indent=2,ensure_ascii=False),encoding='utf-8')
    (stage/'README.txt').write_text('Read-only provenance corpus. v5 follows literal source references plus runtime aliases proven by Summit source: .INI/.IN -> .INX, INX model .ASE -> .SMD, INX motion/talk-motion .ASE -> .SMB, and INX link descriptors -> .INX. closure_report.json records resolved and missing edges.\n',encoding='utf-8')
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in stage.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(stage))
    shutil.rmtree(stage); print(json.dumps({'samples':len(chosen),'bytes':total,'zip':str(out.resolve()),'reference_following':not a.no_follow_references,'closure':closure['summary']},indent=2,ensure_ascii=False)); return 0
if __name__=='__main__':raise SystemExit(main())
