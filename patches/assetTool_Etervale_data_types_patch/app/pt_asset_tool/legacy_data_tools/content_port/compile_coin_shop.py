#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

MAGIC=b'SCSP'; VERSION=1
HEADER=struct.Struct('<4sHH6I32s')
ENTRY=struct.Struct('<32sIHBBI')
SHOP_KIND={'coin':1,'time':2}

def load_catalog(path: Path):
    doc=json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema')!='summit.coin-shop-catalog/v1':
        raise ValueError('unsupported coin shop schema')
    rows=[]
    for shop_name in ('coin','time'):
        entries=doc.get('shops',{}).get(shop_name)
        if not isinstance(entries,list):
            raise ValueError(f'missing shops.{shop_name}')
        if not entries:
            raise ValueError(f'shops.{shop_name} must not be empty')
        for item in entries:
            code=item.get('code')
            section=item.get('section')
            price=item.get('price')
            if not isinstance(code,str) or not code or len(code.encode('ascii','strict'))>=32:
                raise ValueError(f'invalid item code: {code!r}')
            if not isinstance(section,int) or section<1 or section>7:
                raise ValueError(f'{shop_name}:{code}: invalid section {section!r}')
            if not isinstance(price,int) or price<=0 or price>0x7fffffff:
                raise ValueError(f'{shop_name}:{code}: invalid price {price!r}')
            rows.append((code,price,section,SHOP_KIND[shop_name],0,0))
    return rows

def main():
    ap=argparse.ArgumentParser(description='Compile canonical CoinShop catalog into a runtime pack')
    ap.add_argument('canonical',type=Path,help='Content/canonical/commerce/coin_shop.json')
    ap.add_argument('output',type=Path)
    a=ap.parse_args()
    rows=load_catalog(a.canonical)
    body=bytearray()
    for code,price,section,kind,flags,reserved in rows:
        raw=code.encode('ascii')
        body.extend(ENTRY.pack(raw+b'\0'*(32-len(raw)),price,section,kind,flags,reserved))
    digest=hashlib.sha256(body).digest()
    header=HEADER.pack(MAGIC,VERSION,0,len(rows),HEADER.size,ENTRY.size,0,0,0,digest)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_bytes(header+body)
    report={
        'format':'SCSP','version':VERSION,'entries':len(rows),
        'coin_entries':sum(1 for x in rows if x[3]==1),
        'time_entries':sum(1 for x in rows if x[3]==2),
        'bytes':a.output.stat().st_size,
        'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),
    }
    a.output.with_suffix(a.output.suffix+'.report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__': main()
