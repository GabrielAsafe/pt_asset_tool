from __future__ import annotations
import json
from pathlib import Path

SHOP_KEYS=('sell_weapon','sell_defence','sell_etc')
SHOP_COMMANDS={
 'sell_weapon': bytes.fromhex('2ab9abb1e2c6c7b8c5'),
 'sell_defence': bytes.fromhex('2ab9e6beeeb1b8c6c7b8c5'),
 'sell_etc': bytes.fromhex('2ac0e2c8adc6c7b8c5'),
}

def load_overrides(path:Path|None)->dict:
 if path is None or not path.is_file(): return {}
 doc=json.loads(path.read_text(encoding='utf-8'))
 if doc.get('schema')!='summit.npc-shop-overrides/v1': raise ValueError(f'unsupported NPC shop override schema: {path}')
 vendors=doc.get('vendors',{})
 if not isinstance(vendors,dict): raise ValueError('npc shop vendors must be an object')
 return vendors

def ops_for(vendors:dict,npc_id:str,key:str)->tuple[list[str],set[str]]:
 row=vendors.get(npc_id,{}) if isinstance(vendors,dict) else {}
 op=row.get(key,{}) if isinstance(row,dict) else {}
 adds=[str(x).strip() for x in op.get('add',[]) if str(x).strip()]
 removes={str(x).strip().casefold() for x in op.get('remove',[]) if str(x).strip()}
 return adds,removes

def effective_values(base:list[str],adds:list[str],removes:set[str])->list[str]:
 out=[];seen=set()
 for value in list(base)+list(adds):
  token=str(value).strip()
  if not token or token.casefold() in removes: continue
  key=token.casefold()
  if key in seen: continue
  seen.add(key);out.append(token)
 return out
