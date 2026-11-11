#!/usr/bin/env python3
"""Read-only, node-by-node native ASE UV inventory. Does not invoke Wine/cook."""
import argparse
from pathlib import Path
import re
import sys
from inspect_native_ase_265 import resolve_source, TOKEN, INTEGER

STRING = re.compile(r'"([^"\r\n]*)"')


def brace_delta(line: str) -> int:
    quoted = False
    delta = 0
    escaped = False
    for c in line:
        if escaped:
            escaped = False
            continue
        if c == '\\' and quoted:
            escaped = True
        elif c == '"':
            quoted = not quoted
        elif not quoted:
            if c == '{': delta += 1
            elif c == '}': delta -= 1
    return delta


def inspect_geometry(data: bytes) -> list[dict]:
    rows = []
    depth = 0
    row = None
    opened = 0
    for line in data.decode('latin1').splitlines():
        found = TOKEN.match(line)
        tag, rest = found.groups() if found else (None, '')
        if tag == 'GEOMOBJECT':
            if row is not None:
                row['invalid_scope'] = True
            row = dict(index=len(rows), name='', declared_faces=None, actual_faces=0,
                       declared_tverts=None, actual_tverts=0, actual_tfaces=0,
                       material_ref=None, mapping_channels=0, invalid_scope=False)
            rows.append(row)
            opened = depth
        elif row is not None:
            if tag == 'NODE_NAME' and not row['name']:
                m = STRING.search(rest)
                if m: row['name'] = m.group(1)[:48]
            elif tag in ('MESH_NUMFACES', 'MESH_NUMTVERTEX', 'MATERIAL_REF'):
                m = INTEGER.match(rest)
                key = {'MESH_NUMFACES': 'declared_faces',
                       'MESH_NUMTVERTEX': 'declared_tverts',
                       'MATERIAL_REF': 'material_ref'}[tag]
                if not m:
                    row['invalid_scope'] = True
                elif tag != 'MESH_NUMTVERTEX' or not row['mapping_channels']:
                    row[key] = int(m.group(1))
            elif tag == 'MESH_FACE': row['actual_faces'] += 1
            elif tag == 'MESH_TVERT' and not row['mapping_channels']:
                row['actual_tverts'] += 1
            elif tag == 'MESH_TFACE' and not row['mapping_channels']:
                row['actual_tfaces'] += 1
            elif tag == 'MESH_MAPPINGCHANNEL': row['mapping_channels'] += 1
        depth += brace_delta(line)
        if row is not None and depth <= opened:
            row = None
    if row is not None:
        row['invalid_scope'] = True
    for r in rows:
        nt = r['declared_tverts']
        nf = r['declared_faces']
        tv = r['actual_tverts']
        tf = r['actual_tfaces']
        if r['invalid_scope'] or nf is None or nf < 0 or r['actual_faces'] != nf:
            r['uv'] = 'INVALID_GEOMETRY'
        elif nf == 0:
            r['uv'] = 'NO_FACES'
        elif (nt is None or nt == 0) and tv == 0 and tf == 0 and not r['mapping_channels']:
            r['uv'] = 'ABSENT'
        elif nt is not None and nt > 0 and tv == nt and tf == nf:
            r['uv'] = 'MAPPED'
        else:
            r['uv'] = 'PARTIAL'
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--client', required=True)
    ap.add_argument('--source', required=True)
    a = ap.parse_args(argv)
    try:
        path = resolve_source(Path(a.client), a.source)
        if path.stat().st_size > 32*1024*1024:
            raise ValueError('ASE exceeds inspection size limit')
        rows = inspect_geometry(path.read_bytes())
    except (OSError, ValueError) as exc:
        print('ASE_GEOMETRY_266=FAIL_CLOSED '+str(exc), file=sys.stderr)
        return 2
    if not rows:
        print('ASE_GEOMETRY_266=FAIL_CLOSED no GEOMOBJECT', file=sys.stderr)
        return 2
    for r in rows:
        print(f"GEOM[{r['index']}] name={r['name']!r} faces={r['actual_faces']}/{r['declared_faces']} "
              f"tverts={r['actual_tverts']}/{r['declared_tverts']} tfaces={r['actual_tfaces']} "
              f"map_channels={r['mapping_channels']} uv={r['uv']}")
    from collections import Counter
    types = Counter(r['uv'] for r in rows)
    print('ASE_GEOMETRY_266=INFO geometry='+str(len(rows))+' '+
          ' '.join(f'{k.lower()}={v}' for k, v in sorted(types.items())))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
