#!/usr/bin/env python3
"""Compile canonical skin -> equipment mappings to a deterministic, SHA-256-protected pack."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

HEADER = struct.Struct('<4sHHII32s')  # 48 bytes
PAIR = struct.Struct('<II')


def parse_mapping(source: Path):
    doc = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(doc, dict) or doc.get('schema') != 'summit.skin-reforms/v1':
        raise ValueError('wrong skin mapping schema')
    items = doc.get('mappings')
    if not isinstance(items, list) or not 1 <= len(items) <= 512:
        raise ValueError('skin mapping count must be in 1..512')
    seen_codes, seen_labels, pairs = set(), set(), []
    for n, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != {'skin', 'skin_code', 'equipment', 'equipment_code'}:
            raise ValueError(f'invalid skin mapping fields at {n}')
        label, equipment = item['skin'], item['equipment']
        if not isinstance(label, str) or not re.fullmatch(r'SK\d{3}', label):
            raise ValueError(f'invalid skin label at {n}')
        if not isinstance(equipment, str) or not re.fullmatch(r'[A-Z]{2}\d{3}', equipment):
            raise ValueError(f'invalid equipment label at {n}')
        def numeric(key):
            v = item[key]
            if not isinstance(v, str) or not re.fullmatch(r'0x[0-9A-F]{8}', v):
                raise ValueError(f'invalid {key} at {n}')
            return int(v,16)
        skin, target = numeric('skin_code'), numeric('equipment_code')
        if not skin or not target or (skin & 0xFFFF0000) not in (0x081A0000, 0x081B0000, 0x081C0000, 0x081D0000):
            raise ValueError(f'bad skin or target code at {n}')
        if skin in seen_codes or label in seen_labels:
            raise ValueError(f'duplicate skin key at {n}: {label}')
        seen_codes.add(skin);seen_labels.add(label);pairs.append((skin,target))
    pairs.sort()
    return pairs


def compile_pack(source: Path, output: Path):
    pairs = parse_mapping(source)
    body = b''.join(PAIR.pack(*row) for row in pairs)
    digest = hashlib.sha256(body).digest()
    pack = HEADER.pack(b'SSKM',1,0,len(pairs),len(body),digest) + body
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(pack)
    return pairs


def inspect_pack(path: Path):
    data=path.read_bytes()
    if len(data)<HEADER.size: raise ValueError('skin mapping pack too small')
    magic,version,flags,count,length,digest=HEADER.unpack_from(data)
    if magic!=b'SSKM' or version!=1 or flags or not 1<=count<=512 or length!=count*PAIR.size or len(data)!=HEADER.size+length:
        raise ValueError('invalid skin mapping pack layout')
    body=data[HEADER.size:]
    if hashlib.sha256(body).digest()!=digest: raise ValueError('skin mapping pack SHA mismatch')
    pairs=[PAIR.unpack_from(body,i*PAIR.size) for i in range(count)]
    if not all(pairs[i-1][0]<pairs[i][0] for i in range(1,count)):
        raise ValueError('unordered or duplicate skin codes')
    return pairs


def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args()
    pairs=compile_pack(args.source,args.output)
    if inspect_pack(args.output)!=pairs:raise RuntimeError('pack round-trip mismatch')
    print(f'SKIN_REFORM_PACK=PASS MAPS={len(pairs)} SHA256={hashlib.sha256(args.output.read_bytes()).hexdigest()}')

if __name__=='__main__':main()
