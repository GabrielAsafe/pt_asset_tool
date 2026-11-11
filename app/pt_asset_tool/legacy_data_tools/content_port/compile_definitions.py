#!/usr/bin/env python3
from __future__ import annotations
import argparse,base64,hashlib,json,struct
from pathlib import Path, PurePosixPath
from legacy_text import lex_bytes
from npc_shop_overrides import load_overrides,ops_for
from item_profile_policy import explicit_runtime_profiles,item_code,item_enabled_for_profile

MAGIC=b'SCFG'; VERSION=1
HEADER=struct.Struct('<4sHH10I32s')
RECORD=struct.Struct('<5I') # path,id,kind,directive_start,directive_count
DIRECTIVE=struct.Struct('<3I') # command bytes string, values bytes string, flags
KIND={'monster_definition':1,'npc_definition':2,'open_item_definition':3}
SHOP_KEYS={'sell_weapon','sell_defence','sell_etc'}

def norm(s:str)->str:
 p=[]
 for x in s.replace('\\','/').split('/'):
  if not x or x=='.':continue
  if x=='..':
   if p:p.pop()
  else:p.append(x)
 return '/'.join(p)

def runtime_alias(doc:dict)->str:
 candidates=doc.get('runtime_paths',[])
 for x in candidates:
  n=norm(x)
  if not n.casefold().startswith(('servidor/','cliente/')):return n
 return norm(candidates[-1] if candidates else doc['source']['legacy_path'])

def render_values(d:dict)->bytes:
 raws=d.get('raw_values_hex') or []
 quoted=d.get('quoted') or []
 out=[]
 for i,h in enumerate(raws):
  b=bytes.fromhex(h)
  q=(i<len(quoted) and quoted[i]) or any(c in b' \t\r\n' for c in b)
  if q: out.append(b'"'+b+b'"')
  else: out.append(b)
 return b' '.join(out)

def linked_lines(payload:bytes):
 result=[]
 for line in payload.splitlines():
  toks=lex_bytes(line)
  if not toks or not toks[0].raw.startswith(b'*'):continue
  vals=[]
  for t in toks[1:]: vals.append((b'"'+t.raw+b'"') if t.quoted or any(c in b' \t\r\n' for c in t.raw) else t.raw)
  result.append((toks[0].raw,b' '.join(vals),0))
 return result

def load_item_profile(path:Path|None):
 if path is None:return None,None
 doc=json.loads(path.read_text(encoding='utf-8'))
 if doc.get('schema')!='summit.item-profile/v1':raise ValueError(f'unsupported item profile: {path}')
 codes=doc.get('codes') or []
 return doc.get('profile'),{str(x).casefold() for x in codes}

def item_is_normal(d:dict)->bool:
 fields=d.get('semantic',{}).get('fields',{})
 return not bool(fields.get('unique',0))

def render_shop_values(d:dict,materializable_codes:set[str],adds:list[str]|None=None,removes:set[str]|None=None):
 raws=d.get('raw_values_hex') or []
 semantic=d.get('values') or []
 quoted=d.get('quoted') or []
 adds=adds or [];removes=removes or set()
 out=[];filtered=[];seen=set()
 for i,h in enumerate(raws):
  b=bytes.fromhex(h)
  token=str(semantic[i]).strip() if i<len(semantic) else b.decode('latin1').strip()
  key=token.casefold()
  if key in removes:
   filtered.append(token);continue
  if token=='없음' and adds:
   continue
  keep=(token=='없음' or key in materializable_codes)
  if not keep:
   filtered.append(token);continue
  if key in seen:continue
  seen.add(key)
  q=(i<len(quoted) and quoted[i]) or any(c in b' \t\r\n' for c in b)
  out.append((b'"'+b+b'"') if q else b)
 for token in adds:
  key=token.casefold()
  if key in seen:continue
  if key not in materializable_codes:
   filtered.append(token);continue
  seen.add(key);out.append(token.encode('ascii'))
 return b' '.join(out),filtered

def main():
 ap=argparse.ArgumentParser();ap.add_argument('canonical',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--item-profile',type=Path);ap.add_argument('--npc-shop-overrides',type=Path);a=ap.parse_args()
 root=a.canonical.resolve(); idx=json.loads((root/'index.json').read_text(encoding='utf-8'))['documents']
 profile_name,profile_codes=load_item_profile(a.item_profile.resolve() if a.item_profile else None)
 vendor_overrides=load_overrides(a.npc_shop_overrides.resolve() if a.npc_shop_overrides else None)
 docs={}; alias_map={}
 for e in idx:
  d=json.loads((root/e['json_path']).read_text(encoding='utf-8')); docs[d['id']]=d
  for alias in d.get('runtime_paths',[]):alias_map[norm(alias).casefold()]=d
 strings=bytearray();soff={}
 def intern_bytes(b:bytes)->int:
  if b'\0' in b:raise ValueError('NUL in SCFG string')
  if b not in soff:soff[b]=len(strings);strings.extend(b+b'\0')
  return soff[b]
 def intern_text(s:str)->int:return intern_bytes(s.encode('utf-8'))
 directives=[];records=[];flattened_links=0;unresolved_links=[];filtered_shop_tokens=[]
 defs=[d for d in docs.values() if d['kind'] in KIND]
 filtered_open_items=[]
 canonical_profile_override_rows=[]
 if profile_codes is not None:
  if profile_name not in ('client','server'):
   raise ValueError(f'profile name must be client/server when item profile codes are active: {profile_name!r}')
  kept=[]
  for d in defs:
   if d['kind']!='open_item_definition':
    kept.append(d);continue
   code=item_code(d)
   explicit=explicit_runtime_profiles(d)
   allowed=item_enabled_for_profile(d,profile_name,profile_codes)
   if explicit is not None:
    canonical_profile_override_rows.append({
     'id':d['id'],
     'path':runtime_alias(d),
     'code':code,
     'runtime_profiles':sorted(explicit),
     'decision':'include' if allowed else 'exclude',
    })
   if allowed:
    kept.append(d)
   else:
    filtered_open_items.append({
     'id':d['id'],
     'path':runtime_alias(d),
     'code':code,
     'filter_source':'canonical_runtime_profiles' if explicit is not None else 'legacy_profile_fallback',
    })
  defs=kept
 materializable_codes={item_code(d) for d in defs if d['kind']=='open_item_definition' and item_is_normal(d) and item_code(d)}
 defs.sort(key=lambda d:runtime_alias(d).casefold())
 for d in defs:
  start=len(directives); rpath=runtime_alias(d)
  source_directives=d.get('semantic',{}).get('directives',[])
  shop_last={}
  for directive_index,directive in enumerate(source_directives):
   if directive.get('key') in SHOP_KEYS:shop_last[directive.get('key')]=directive_index
  for directive_index,directive in enumerate(source_directives):
   key=directive.get('key')
   if key=='linked_file':
    raw=directive.get('raw_values_hex') or []
    if raw:
     rel=bytes.fromhex(raw[0]).decode('latin1')
     # path bytes in this corpus are ASCII-compatible; latin1 preserves bytes.
     parent=PurePosixPath(rpath.replace('\\','/')).parent.as_posix()
     target=norm(parent+'/'+rel).casefold()
     linked=alias_map.get(target)
     if linked:
      payload=base64.b64decode(linked['compatibility']['legacy_payload_base64'])
      for command,values,flags in linked_lines(payload):
       directives.append((intern_bytes(command),intern_bytes(values),flags))
      flattened_links+=1
     else: unresolved_links.append({'id':d['id'],'path':rpath,'target':target})
    break # exact legacy behavior switches file and never returns
   command=bytes.fromhex(directive['legacy_token_hex'])
   if key in SHOP_KEYS and profile_name in ('client','server'):
    adds,removes=ops_for(vendor_overrides,d['id'],key)
    if shop_last.get(key)!=directive_index:adds=[]
    rendered,filtered=render_shop_values(directive,materializable_codes,adds,removes)
    for token in filtered:
     filtered_shop_tokens.append({'id':d['id'],'path':rpath,'key':key,'token':token})
    directives.append((intern_bytes(command),intern_bytes(rendered),0))
   else:
    directives.append((intern_bytes(command),intern_bytes(render_values(directive)),0))
  records.append((intern_text(rpath),intern_text(d['id']),KIND[d['kind']],start,len(directives)-start))
 header_size=HEADER.size;ro=header_size;rs=RECORD.size;do=ro+len(records)*rs;ds=DIRECTIVE.size;so=do+len(directives)*ds
 body=bytearray()
 for r in records:body.extend(RECORD.pack(*r))
 for r in directives:body.extend(DIRECTIVE.pack(*r))
 body.extend(strings);digest=hashlib.sha256(body).digest()
 header=HEADER.pack(MAGIC,VERSION,0,len(records),ro,rs,len(directives),do,ds,so,len(strings),0,0,digest)
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(header+body)
 report={'format':'SCFG','version':VERSION,'profile':profile_name or 'unprofiled','definitions':len(records),'directives':len(directives),'flattened_links':flattened_links,'filtered_open_items':len(filtered_open_items),'filtered_open_item_rows':filtered_open_items,'canonical_profile_overrides':len(canonical_profile_override_rows),'canonical_profile_override_rows':canonical_profile_override_rows,'filtered_shop_tokens':filtered_shop_tokens,'legacy_missing_links':unresolved_links,'bytes':a.output.stat().st_size,'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()}
 a.output.with_suffix(a.output.suffix+'.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:(len(v) if k in ('legacy_missing_links','filtered_open_item_rows','canonical_profile_override_rows','filtered_shop_tokens') else v) for k,v in report.items()},ensure_ascii=False))
if __name__=='__main__':main()
