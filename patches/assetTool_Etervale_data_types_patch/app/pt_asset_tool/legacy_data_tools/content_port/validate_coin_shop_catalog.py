#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sqlite3,sys
from pathlib import Path

def load_codes(path:Path):
 d=json.loads(path.read_text(encoding='utf-8'))
 return {str(x).casefold() for x in d.get('codes',[])}

def rows_from_json(path:Path):
 d=json.loads(path.read_text(encoding='utf-8'))
 if d.get('schema')!='summit.coin-shop-catalog/v1':raise ValueError('bad schema')
 out={}
 errors=[]
 for shop in ('coin','time'):
  rows=d.get('shops',{}).get(shop)
  if not isinstance(rows,list):
   errors.append(f'missing shops.{shop}');continue
  if not rows:errors.append(f'shops.{shop} must not be empty')
  seen=set();normalized=[]
  for idx,row in enumerate(rows):
   code=row.get('code');section=row.get('section');price=row.get('price')
   if not isinstance(code,str) or not code.strip():errors.append(f'{shop}[{idx}]: invalid code');continue
   key=code.casefold()
   if key in seen:errors.append(f'{shop}: duplicate code {code}')
   seen.add(key)
   if not isinstance(section,int) or not 1<=section<=7:errors.append(f'{shop}:{code}: section must be 1..7')
   if not isinstance(price,int) or price<=0:errors.append(f'{shop}:{code}: price must be >0')
   normalized.append((code,section,price))
  out[shop]=normalized
 return out,errors

def db_rows(db:Path,table:str):
 con=sqlite3.connect(f'file:{db.resolve()}?mode=ro',uri=True)
 try:return [(r[0],r[1],r[2]) for r in con.execute(f'SELECT szItemCode,ItemSection,Price FROM "{table}" ORDER BY rowid')]
 finally:con.close()

def main():
 ap=argparse.ArgumentParser(description='Validate canonical CoinShop catalog and optional DB snapshot parity')
 ap.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[2])
 ap.add_argument('--sqlite',type=Path)
 a=ap.parse_args();root=a.repo_root.resolve()
 catalog=root/'Content/canonical/commerce/coin_shop.json'
 try:
  shops,errors=rows_from_json(catalog)
  catalog_doc=json.loads(catalog.read_text(encoding='utf-8'))
  quest_only={str(x).casefold() for x in catalog_doc.get('policy',{}).get('quest_only_item_codes',[])}
 except Exception as exc:print('FAIL',exc);return 1
 client=load_codes(root/'Content/canonical/item_profiles/client.items.json')
 server=load_codes(root/'Content/canonical/item_profiles/server.items.json')
 for shop,rows in shops.items():
  for code,section,price in rows:
   if code.casefold() not in client:errors.append(f'{shop}:{code}: missing from client item profile')
   if code.casefold() not in server:errors.append(f'{shop}:{code}: missing from server item profile')
 if a.sqlite:
  expected={'coin':db_rows(a.sqlite,'CoinShopDB__ItemList'),'time':db_rows(a.sqlite,'CoinShopDB__ItemList_T')}
  for shop in ('coin','time'):
   lhs=[(c.casefold(),s,p) for c,s,p in shops.get(shop,[])]
   rhs=[(c.casefold(),s,p) for c,s,p in expected[shop] if c.casefold() not in quest_only]
   if lhs!=rhs:errors.append(f'{shop}: canonical catalog differs from DB row order/content after quest-only exclusions')

 # Runtime contract: a valid canonical pack owns catalog existence and price.
 # Legacy ItemList/ItemList_T queries may remain only behind the explicit
 # !canonicalCatalogAvailable rollback path. Wallet state remains DB-backed.
 runtime_checks=[
  ('coin',root/'SrcServer/src/systems/commerce/coin_shop/CoinShop.cpp','SummitCoinShopCatalogPrice','ItemList WHERE szItemCode=?'),
  ('time',root/'SrcServer/src/systems/commerce/coin_shop/CoinShop_T.cpp','SummitTimeShopCatalogPrice','ItemList_T WHERE szItemCode=?'),
 ]
 for shop,path,price_helper,legacy_buy_query in runtime_checks:
  text=path.read_bytes().decode('latin1')
  if 'ActiveCoinShopSource()' not in text:errors.append(f'{shop}: canonical runtime pack is not wired into LoadItems')
  if price_helper not in text:errors.append(f'{shop}: purchase path does not resolve price from compiled canonical catalog')
  if 'canonicalCatalogAvailable = false' not in text:errors.append(f'{shop}: canonical availability gate missing from purchase path')
  fallback_guard='if(!canonicalCatalogAvailable && !QuestOnlyWingCode(lpTransBuy->szItemCode))'
  if fallback_guard not in text:errors.append(f'{shop}: legacy DB fallback is not explicitly gated by canonical availability / quest-only policy')
  if legacy_buy_query not in text:errors.append(f'{shop}: rollback-only legacy catalog fallback unexpectedly missing')
  if 'Valid canonical pack is authoritative' not in text:errors.append(f'{shop}: valid empty canonical catalog is not fail-closed/authoritative')
  if 'SELECT * FROM UserInfo' not in text:errors.append(f'{shop}: mutable wallet DB read unexpectedly missing')
 print(f'coin_entries={len(shops.get("coin",[]))}')
 print(f'time_entries={len(shops.get("time",[]))}')
 print(f'client_profile_codes={len(client)} server_profile_codes={len(server)}')
 if errors:
  for e in errors:print('FAIL',e)
  return 1
 print('PASS catalog schema/sections/prices/duplicates')
 print('PASS every shop code resolves in client and server item profiles')
 print('PASS purchases authorize against loaded catalog while mutable wallet state remains DB-backed')
 if a.sqlite:print('PASS canonical catalog matches supplied DB snapshot after intentional quest-only exclusions')
 return 0
if __name__=='__main__':sys.exit(main())
