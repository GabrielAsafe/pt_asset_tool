#!/usr/bin/env python3
"""Create only file formats whose framing is sufficiently proven by current Summit source.

Currently supported for authorship:
  - SPP: exactly 200 little-endian records {int32 state, int32 x, int32 z}

This intentionally does NOT write SPC/INX/SMD Stage.
"""
from __future__ import annotations
import argparse, json, struct
from pathlib import Path

SPP_RECORDS = 200
REC = struct.Struct('<iii')
SPP_SIZE = SPP_RECORDS * REC.size


def load_points(path: Path):
    obj = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(obj, dict):
        obj = obj.get('points', [])
    if not isinstance(obj, list):
        raise SystemExit('JSON must be a list or {"points": [...]}')
    if len(obj) > SPP_RECORDS:
        raise SystemExit(f'maximum {SPP_RECORDS} SPP records')
    out = []
    for i, p in enumerate(obj):
        if not isinstance(p, dict):
            raise SystemExit(f'point {i} must be an object')
        try:
            state, x, z = int(p.get('state', 0)), int(p['x']), int(p['z'])
        except Exception as e:
            raise SystemExit(f'invalid point {i}: {e}')
        for name, value in [('state',state),('x',x),('z',z)]:
            if not -(2**31) <= value < 2**31:
                raise SystemExit(f'point {i} {name} outside int32')
        out.append((state,x,z))
    return out


def write_spp(src: Path, out: Path):
    points = load_points(src)
    buf = bytearray(SPP_SIZE)
    for i, values in enumerate(points):
        REC.pack_into(buf, i * REC.size, *values)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf)
    print(json.dumps({
        'output': str(out), 'bytes': len(buf), 'records_total': SPP_RECORDS,
        'records_authored': len(points), 'records_zero_filled': SPP_RECORDS-len(points)
    }, ensure_ascii=False, indent=2))


def inspect(path: Path):
    data = path.read_bytes()
    result = {'path': str(path), 'bytes': len(data), 'canonical_spp': len(data)==SPP_SIZE}
    if len(data) % REC.size == 0:
        rows = []
        for i in range(min(len(data)//REC.size, SPP_RECORDS)):
            v = REC.unpack_from(data, i*REC.size)
            if v != (0,0,0):
                rows.append({'index': i, 'state': v[0], 'x': v[1], 'z': v[2]})
        result['nonzero_records'] = rows
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sp=p.add_subparsers(dest='cmd', required=True)
    a=sp.add_parser('spp', help='write canonical 2,400-byte Summit SPP')
    a.add_argument('--json', required=True, type=Path)
    a.add_argument('--out', required=True, type=Path)
    b=sp.add_parser('inspect', help='inspect an SPP file')
    b.add_argument('path', type=Path)
    ns=p.parse_args()
    if ns.cmd=='spp': write_spp(ns.json, ns.out)
    else: inspect(ns.path)

if __name__=='__main__': main()
