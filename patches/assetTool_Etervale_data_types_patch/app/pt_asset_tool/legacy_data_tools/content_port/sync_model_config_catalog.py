#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, re, struct, sys
from pathlib import Path, PurePosixPath
from collections import defaultdict

MODEL_EXTS=(".ini", ".inx")
MODEL_GROUPS={"high":0x0C0,"default":0x104,"low":0x148}

def norm(p:str)->str:
    return '/'.join(x for x in str(p).replace('\\','/').split('/') if x not in ('','.'))

def slug(s:str)->str:
    s=norm(s).casefold()
    s=re.sub(r'\.(ini|inx)$','',s)
    s=re.sub(r'[^a-z0-9]+','.',s).strip('.')
    return s or 'unknown'

def cstr(data:bytes)->str:
    return data.split(b'\0',1)[0].decode('latin-1','replace')

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def load_pt_parser(root:Path|None):
    if not root: return None
    candidates=[root/'app'/'pt_inx_motion_core_v2.py',root/'pt_inx_motion_core_v2.py']
    p=next((x for x in candidates if x.is_file()),None)
    if not p: raise FileNotFoundError(f'pt_inx_motion_core_v2.py not found under {root}')
    spec=importlib.util.spec_from_file_location('pt_inx_motion_core_v2',p)
    mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod)
    return mod

def groups(data:bytes):
    out={}
    for key,off in MODEL_GROUPS.items():
        if off+68>len(data): continue
        count=struct.unpack_from('<i',data,off)[0]
        if not 0<=count<=4: continue
        names=[cstr(data[off+4+i*16:off+4+(i+1)*16]) for i in range(4)]
        out[key]={"count":count,"names":names[:count]}
    return out

def index_tree(root:Path|None):
    by_lower={}
    if not root or not root.exists(): return by_lower
    for p in root.rglob('*'):
        if p.is_file(): by_lower[norm(p.relative_to(root).as_posix()).casefold()]=p
    return by_lower

def resolve_asset(logical:str, roots:list[tuple[str,Path,dict]]):
    n=norm(logical); stem=re.sub(r'\.(ini|inx)$','',n,flags=re.I)
    wants=[stem+'.inx', n, stem+'.ini']
    for label,root,idx in roots:
        for w in wants:
            p=idx.get(w.casefold())
            if p: return label,p,w
    return None,None,None

def iter_defs(text_root:Path):
    for p in text_root.rglob('*.json'):
        try: d=json.loads(p.read_text(encoding='utf-8'))
        except Exception: continue
        if d.get('kind') not in ('monster_definition','npc_definition'): continue
        fields=((d.get('semantic') or {}).get('fields') or {})
        mf=fields.get('model_file')
        if isinstance(mf,str) and mf.strip(): yield p,d,mf

def main():
    ap=argparse.ArgumentParser(description='Build canonical model-config catalog from monster/NPC model_file references, optionally decoding shipped INX through PT Asset Tool.')
    ap.add_argument('canonical',type=Path,help='Content/canonical root')
    ap.add_argument('--server-char',type=Path)
    ap.add_argument('--client-char',type=Path)
    ap.add_argument('--pt-asset-tool-root',type=Path)
    ap.add_argument('--patch-definitions',action='store_true')
    args=ap.parse_args()
    root=args.canonical.resolve(); text=root/'text'; outroot=root/'model_configs'; models=outroot/'models'; models.mkdir(parents=True,exist_ok=True)
    parser=load_pt_parser(args.pt_asset_tool_root.resolve() if args.pt_asset_tool_root else None)
    roots=[]
    for label,r in [('server',args.server_char),('client',args.client_char)]:
        if r:
            rr=r.resolve(); roots.append((label,rr,index_tree(rr)))
    refs=defaultdict(list); defrows=[]
    for p,d,mf in iter_defs(text):
        key=norm(mf).casefold(); refs[key].append({"id":d['id'],"kind":d['kind'],"json_path":norm(p.relative_to(root).as_posix())})
        defrows.append((p,d,mf,key))
    docs=[]; id_by_key={}
    for key in sorted(refs):
        logical=next(mf for _,_,mf,k in defrows if k==key)
        mid='model.'+slug(logical); id_by_key[key]=mid
        label,p,resolved=resolve_asset(logical,roots)
        doc={
            "schema":"summit.model-config/v1","schema_version":1,"id":mid,
            "logical_config":norm(logical),
            "legacy_cache":re.sub(r'\.(ini|inx)$','.inx',norm(logical),flags=re.I),
            "consumers":sorted(refs[key],key=lambda x:(x['kind'],x['id'])),
            "source":{"status":"unresolved"},
            "semantic":{}
        }
        if p:
            doc['source']={"status":"resolved","profile":label,"path":norm(p.as_posix()),"resolved_as":resolved,"size":p.stat().st_size,"sha256":sha256(p)}
            if p.suffix.casefold()=='.inx' and parser:
                parsed=parser.parse_inx(p); data=p.read_bytes(); lay=parsed['layout']
                motion_count_off=int(lay['motion_count_off'])
                talk_link_off=int(lay['link_file_off'])+64
                talk_motion_off=talk_link_off+64
                doc['semantic']={
                    "layout":lay['name'],"model_file":cstr(data[0:64]),"motion_file":cstr(data[64:128]),"sub_model_file":cstr(data[128:192]),
                    "model_groups":groups(data),"motion_count":parsed['motion_count'],"link_file":parsed['link_file'],
                    "talk_link_file":cstr(data[talk_link_off:talk_link_off+64]) if talk_link_off+64<=len(data) else '',
                    "talk_motion_file":cstr(data[talk_motion_off:talk_motion_off+64]) if talk_motion_off+64<=len(data) else '',
                    "motions":parsed['motions']
                }
            else:
                doc['source']['decode_status']='legacy_text_source_or_parser_unavailable'
        path=models/(slug(logical)+'.json'); path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); docs.append({"id":mid,"json_path":norm(path.relative_to(outroot).as_posix()),"logical_config":norm(logical),"source_status":doc['source']['status']})
    if args.patch_definitions:
        for p,d,mf,key in defrows:
            fields=d['semantic']['fields']; fields['model_config_id']=id_by_key[key]
            p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    index={"schema":"summit.model-config-catalog/v1","schema_version":1,"model_count":len(docs),"models":docs}
    (outroot/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={"model_refs":len(defrows),"unique_model_configs":len(docs),"resolved":sum(1 for d in docs if d['source_status']=='resolved'),"unresolved":sum(1 for d in docs if d['source_status']!='resolved'),"definitions_patched":bool(args.patch_definitions)}
    (outroot/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__': main()
