#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, re, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from legacy_text import decode_atom, decode_line_best, lex_bytes, sha256_bytes, strip_inline_comment
from source_tokens import load_source_token_maps
from active_tokens import load_active_token_sets

SCHEMA_VERSION=1


def rel_posix(path:Path, root:Path)->str:
    return path.relative_to(root).as_posix()


def classify(path:Path,root:Path)->str:
    s='/' + rel_posix(path,root).lower()
    e=path.suffix.lower()
    if '/gameserver/openitem/' in s:
        if e=='.txt': return 'open_item_definition'
        if e=='.zhoon': return 'localization_resource'
        return 'open_item_auxiliary'
    if '/gameserver/monster/' in s:
        if e=='.inf': return 'monster_definition'
        if e=='.zhoon': return 'localization_resource'
        return 'monster_auxiliary'
    if '/gameserver/npc/' in s:
        if e=='.npc': return 'npc_definition'
        if e=='.zhoon': return 'localization_resource'
        return 'npc_auxiliary'
    if '/gameserver/field/' in s and e=='.spm': return 'stage_spawn'
    if e=='.zhoon': return 'localization_resource'
    if '/char/tmabcd/' in s and e=='.inf': return 'model_config_text'
    if e=='.msg': return 'message_catalog'
    if e=='.sin': return 'sin_resource'
    if e=='.lua': return 'lua_script'
    if e=='.ini': return 'ini_config'
    if e=='.txt': return 'generic_text'
    return 'generic_text'


def family_token_map(kind:str,maps):
    if kind=='stage_spawn': return maps['spawn']
    if kind in ('monster_definition','npc_definition'): return maps['character']
    if kind=='open_item_definition': return maps['item']
    if kind=='character_preset': return maps['character']
    return {}


def atom_value(tok):
    s=tok.text
    # Exact decimal integer/float conversion only. Codes such as OS101 remain strings.
    if re.fullmatch(r'[+-]?\d+',s):
        try:return int(s)
        except:return s
    if re.fullmatch(r'[+-]?(?:\d+\.\d*|\d*\.\d+)',s):
        try:return float(s)
        except:return s
    return s


def add_field(fields:dict,key:str,values:list[Any]):
    value = True if not values else (values[0] if len(values)==1 else values)
    if key not in fields: fields[key]=value
    elif isinstance(fields[key],dict) and '$repeated' in fields[key]: fields[key]['$repeated'].append(value)
    else: fields[key]={'$repeated':[fields[key],value]}


def parse_directive_document(data:bytes, token_map:dict[bytes,str], active_tokens:set[bytes]):
    directives=[]; fields={}; comments=[]; unknown=Counter(); codecs=Counter()
    for lineno,line in enumerate(data.splitlines(),1):
        body,comment=strip_inline_comment(line)
        if comment is not None:
            c,enc=decode_line_best(comment); comments.append({'line':lineno,'text':c}); codecs[enc]+=1
        tokens=lex_bytes(line)
        if not tokens: continue
        cmd=tokens[0]
        if not cmd.raw.startswith(b'*'): continue
        canonical=token_map.get(cmd.raw)
        if canonical is None:
            # ASCII tokens are preserved legibly; byte-only unknowns receive a stable hex identity.
            display=cmd.text
            canonical='unmapped.' + (re.sub(r'[^a-z0-9]+','_',display.lstrip('*').lower()).strip('_') if display.isascii() else cmd.raw.hex())
            unknown[display]+=1
        values=[atom_value(t) for t in tokens[1:]]
        codecs[cmd.encoding]+=1
        for t in tokens[1:]: codecs[t.encoding]+=1
        status=('supported_mapped' if cmd.raw in active_tokens and not canonical.startswith('unmapped.') else ('supported_unmapped' if cmd.raw in active_tokens else 'not_consumed_by_active_loader'))
        entry={'line':lineno,'key':canonical,'legacy_token':cmd.text,'legacy_token_hex':cmd.raw.hex(),'loader_status':status,'values':values,'raw_values_hex':[t.raw.hex() for t in tokens[1:]]}
        if any(t.quoted for t in tokens[1:]): entry['quoted']=[t.quoted for t in tokens[1:]]
        directives.append(entry)
        add_field(fields,canonical,values)
    return {
      'fields':fields,
      'directives':directives,
      'comments':comments,
      'unknown_tokens':dict(unknown),
      'atom_encodings':dict(codecs),
    }


def parse_spawn_semantics(parsed:dict):
    out={'max_actor_position':None,'delay':None,'max_actor':None,'actors':[],'bosses':[]}
    for d in parsed['directives']:
        k=d['key']; v=d['values']
        if k=='max_actor_position' and v: out['max_actor_position']=v[0]
        elif k=='delay' and v: out['delay']={'shift':v[0], **({'milliseconds':int(v[1])*1000} if len(v)>1 and isinstance(v[1],int) else {})}
        elif k=='max_actor' and v: out['max_actor']=v[0]
        elif k=='actor' and v:
            raw=d.get('raw_values_hex',[])
            out['actors'].append({'legacy_name':v[0], 'legacy_name_bytes_hex':raw[0] if raw else '', 'weight':v[1] if len(v)>1 else 0})
        elif k=='boss_actor' and v:
            raw=d.get('raw_values_hex',[])
            out['bosses'].append({'master_legacy_name':v[0] if len(v)>0 else '', 'master_legacy_name_bytes_hex':raw[0] if len(raw)>0 else '', 'slave_legacy_name':v[1] if len(v)>1 else '', 'slave_legacy_name_bytes_hex':raw[1] if len(raw)>1 else '', 'slave_count':v[2] if len(v)>2 else 0, 'open_hours':v[3:]})
    return out


def parse_localization(data:bytes):
    entries=[]; codecs=Counter()
    for lineno,line in enumerate(data.splitlines(),1):
        tokens=lex_bytes(line)
        if len(tokens)<2: continue
        key=tokens[0].text.lstrip('*')
        ku=key.upper()
        if ku not in ('J_NAME','J_CHAT','E_NAME','E_CHAT','T_NAME','T_CHAT'): continue
        value=' '.join(t.text for t in tokens[1:])
        entries.append({'line':lineno,'legacy_key':key,'kind':'name' if ku.endswith('_NAME') else 'chat','text':value})
        for t in tokens: codecs[t.encoding]+=1
    return {'entries':entries,'atom_encodings':dict(codecs)}


def generic_document(data:bytes):
    lines=[]; codecs=Counter()
    for i,line in enumerate(data.splitlines(),1):
        text,enc=decode_line_best(line.rstrip(b'\r\n')); codecs[enc]+=1
        lines.append(text)
    return {'lines':lines,'line_encodings':dict(codecs)}


def suggest_id(kind:str,path:Path):
    stem=path.stem
    if stem.lower().endswith('.ase'): stem=stem[:-4]
    slug=re.sub(r'[^A-Za-z0-9]+','_',stem).strip('_').lower()
    prefix={
      'stage_spawn':'spawn','monster_definition':'monster','npc_definition':'npc',
      'open_item_definition':'item','localization_resource':'text','model_config_text':'model_config'
    }.get(kind,'text')
    return f'{prefix}.{slug}' if slug else None


def output_path(path:Path,root:Path,out:Path)->Path:
    rel=path.relative_to(root)
    return out/'documents'/rel.parent/(rel.name+'.json')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--corpus',type=Path,required=True)
    ap.add_argument('--source-root',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    root=args.corpus.resolve(); src=args.source_root.resolve(); out=args.out.resolve()
    maps=load_source_token_maps(src)
    active=load_active_token_sets(src)
    if out.exists(): shutil.rmtree(out)
    (out/'documents').mkdir(parents=True)
    family_counts=Counter(); unknown_by_family=defaultdict(Counter); encoding_counts=Counter(); problems=[]; index=[]
    paths=sorted(p for p in root.rglob('*') if p.is_file())
    for seq,path in enumerate(paths,1):
        data=path.read_bytes(); kind=classify(path,root); family_counts[kind]+=1
        doc={
          'schema':'summit.text-shadow/v1','schema_version':SCHEMA_VERSION,
          'kind':kind,'id':suggest_id(kind,path),
          'source':{'path':rel_posix(path,root),'size':len(data),'sha256':sha256_bytes(data)},
        }
        if kind=='localization_resource':
            parsed=parse_localization(data); doc['content']=parsed
        elif kind in ('stage_spawn','monster_definition','npc_definition','open_item_definition'):
            active_set = active['spawn'] if kind=='stage_spawn' else (active['item'] if kind=='open_item_definition' else active['character'])
            parsed=parse_directive_document(data,family_token_map(kind,maps),active_set); doc['content']=parsed
            for tok,n in parsed['unknown_tokens'].items(): unknown_by_family[kind][tok]+=n
            if kind=='stage_spawn': doc['semantic']=parse_spawn_semantics(parsed)
        else:
            doc['content']=generic_document(data)
        for k,v in doc['content'].get('atom_encodings',doc['content'].get('line_encodings',{})).items(): encoding_counts[k]+=v
        dest=output_path(path,root,out); dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=False)+'\n',encoding='utf-8')
        index.append({'id':doc['id'],'kind':kind,'source_path':doc['source']['path'],'json_path':dest.relative_to(out).as_posix(),'sha256':doc['source']['sha256']})
    (out/'index.json').write_text(json.dumps({'schema':'summit.text-shadow-index/v1','documents':index},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={
      'schema':'summit.text-shadow-report/v1','files':len(paths),
      'families':dict(family_counts),'atom_or_line_encodings':dict(encoding_counts),
      'unknown_tokens':{k:dict(v) for k,v in unknown_by_family.items()},
      'source_token_map_sizes':{k:len(v) for k,v in maps.items()},
      'active_loader_token_sizes':{k:len(v) for k,v in active.items()},
    }
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    md=['# Summit text shadow import report','',f'- Files converted: **{len(paths)}**',f'- Output encoding: **UTF-8 JSON**','', '## Families']
    for k,v in family_counts.most_common(): md.append(f'- `{k}`: {v}')
    md += ['', '## Source-derived token maps']
    for k,v in maps.items(): md.append(f'- `{k}`: {len(v)} accepted byte tokens/aliases')
    md += ['', '## Unmapped directive tokens']
    if not any(unknown_by_family.values()): md.append('- None')
    for fam,c in unknown_by_family.items():
        md.append(f'### {fam} ({len(c)} unique)')
        for tok,n in c.most_common(80): md.append(f'- `{tok}`: {n}')
    (out/'REPORT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(paths),'out':str(out),'families':dict(family_counts),'unknown_unique':{k:len(v) for k,v in unknown_by_family.items()}},ensure_ascii=False))

if __name__=='__main__': main()
