#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from npc_shop_overrides import SHOP_KEYS,load_overrides,ops_for,effective_values
from item_profile_policy import load_open_item_documents,effective_profile_codes

def codes(path:Path)->set[str]:
 return {str(x).casefold() for x in json.loads(path.read_text(encoding='utf-8')).get('codes',[])}

def main()->int:
 ap=argparse.ArgumentParser(description='Validate effective canonical NPC shop inventory across client/server item profiles')
 ap.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[2])
 a=ap.parse_args();root=a.repo_root.resolve()
 text=root/'Content/canonical/text'; commerce=root/'Content/canonical/commerce'
 vendors=load_overrides(commerce/'npc_shop_overrides.json')
 open_items=load_open_item_documents(text)
 client=effective_profile_codes(open_items,'client',codes(root/'Content/canonical/item_profiles/client.items.json'))
 server=effective_profile_codes(open_items,'server',codes(root/'Content/canonical/item_profiles/server.items.json'))
 docs={};errors=[];suppressed=[];effective_count=0
 idx=json.loads((text/'index.json').read_text(encoding='utf-8'))['documents']
 for e in idx:
  p=text/e['json_path'];d=json.loads(p.read_text(encoding='utf-8'))
  if d.get('kind')=='npc_definition': docs[d.get('id','')]=d
 for npc_id in vendors:
  if npc_id not in docs: errors.append(f'override references unknown NPC id: {npc_id}')
 for npc_id,d in docs.items():
  directives=d.get('semantic',{}).get('directives',[])
  bykey={k:[] for k in SHOP_KEYS}
  for directive in directives:
   key=directive.get('key')
   if key in bykey: bykey[key].append([str(x).strip() for x in directive.get('values',[])])
  for key in SHOP_KEYS:
   adds,removes=ops_for(vendors,npc_id,key)
   base=[]
   for row in bykey[key]: base.extend(row)
   for token in base:
    if token and token!='없음' and token.casefold() in removes: suppressed.append((npc_id,key,token))
   values=effective_values([x for x in base if x!='없음'],adds,removes)
   for token in values:
    effective_count+=1;c=token.casefold();missing=[]
    if c not in client: missing.append('client')
    if c not in server: missing.append('server')
    if missing: errors.append(f'{npc_id}:{key}:{token}: missing from {"+".join(missing)} item profile')
   for token in adds:
    c=token.casefold()
    if c not in client or c not in server: errors.append(f'{npc_id}:{key}: override add {token} is not executable in both profiles')
 print(f'npc_documents={len(docs)}')
 print(f'effective_shop_refs={effective_count}')
 print(f'suppressed_legacy_refs={len(suppressed)}')
 for row in suppressed: print('SUPPRESSED',*row,sep=' | ')
 if errors:
  for e in errors: print('FAIL',e)
  return 1
 print('PASS every effective NPC shop item exists in client and server item profiles')
 print('PASS invalid legacy shop references remain preserved in NPC canonical documents but are explicitly suppressed by commerce overrides')
 return 0
if __name__=='__main__':sys.exit(main())
