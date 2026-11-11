#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from npc_shop_overrides import SHOP_KEYS

def load_codes(path:Path)->set[str]:
 return {str(x).casefold() for x in json.loads(path.read_text(encoding='utf-8')).get('codes',[])}

def main()->int:
 ap=argparse.ArgumentParser(description='Add/remove an item association for a canonical NPC vendor override')
 ap.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[2])
 ap.add_argument('--npc',required=True,help='canonical NPC id, e.g. npc.toolsric')
 ap.add_argument('--channel',required=True,choices=SHOP_KEYS)
 g=ap.add_mutually_exclusive_group(required=True);g.add_argument('--add');g.add_argument('--remove')
 ap.add_argument('--dry-run',action='store_true')
 a=ap.parse_args();root=a.repo_root.resolve();commerce=root/'Content/canonical/commerce';path=commerce/'npc_shop_overrides.json'
 doc=json.loads(path.read_text(encoding='utf-8'))
 # prove NPC id exists
 idx=json.loads((root/'Content/canonical/text/index.json').read_text(encoding='utf-8'))['documents'];npc_doc=None
 for e in idx:
  d=json.loads((root/'Content/canonical/text'/e['json_path']).read_text(encoding='utf-8'))
  if d.get('kind')=='npc_definition' and d.get('id')==a.npc:npc_doc=d;break
 if npc_doc is None: raise SystemExit(f'unknown NPC id: {a.npc}')
 channels={x.get('key') for x in npc_doc.get('semantic',{}).get('directives',[]) if x.get('key') in SHOP_KEYS}
 if a.channel not in channels: raise SystemExit(f'{a.npc} has no legacy {a.channel} directive to override')
 token=(a.add or a.remove).strip();key=token.casefold()
 if a.add:
  client=load_codes(root/'Content/canonical/item_profiles/client.items.json');server=load_codes(root/'Content/canonical/item_profiles/server.items.json')
  missing=[]
  if key not in client:missing.append('client')
  if key not in server:missing.append('server')
  if missing:raise SystemExit(f'cannot add {token}: missing from {"+".join(missing)} item profile')
 vendors=doc.setdefault('vendors',{});vendor=vendors.setdefault(a.npc,{});op=vendor.setdefault(a.channel,{'add':[],'remove':[]})
 op.setdefault('add',[]);op.setdefault('remove',[])
 def drop(seq): return [x for x in seq if str(x).casefold()!=key]
 if a.add:
  op['remove']=drop(op['remove'])
  if key not in {str(x).casefold() for x in op['add']}:op['add'].append(token)
  action='ADD'
 else:
  op['add']=drop(op['add'])
  if key not in {str(x).casefold() for x in op['remove']}:op['remove'].append(token)
  action='REMOVE'
 print(f'{action} npc={a.npc} channel={a.channel} code={token}')
 if a.dry_run:print('DRY_RUN=1');return 0
 path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(path)
 return 0
if __name__=='__main__':sys.exit(main())
