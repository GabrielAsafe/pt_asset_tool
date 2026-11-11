#!/usr/bin/env python3
"""Read-only ASE face material inspection (does not cook, write files or run Wine)."""
import argparse
from collections import Counter
from pathlib import Path
import re
import sys
from inspect_native_ase_265 import resolve_source, TOKEN, INTEGER
from inspect_ase_geometry_uv_266 import brace_delta, STRING

FACE_ID = re.compile(r'\*MESH_MTLID\s*:?\s*(-?\d+)\b')


def inspect_material_faces(data: bytes):
    depth = 0
    material_depth = None
    material_parent = None
    material_top_depth = None
    counts = {}
    geom_start = None
    row = None
    rows = []
    for line in data.decode('latin1').splitlines():
        m = TOKEN.match(line)
        tag, rest = m.groups() if m else (None, '')
        if tag == 'MATERIAL_LIST':
            material_depth = depth
        elif tag == 'MATERIAL' and material_depth is not None and depth == material_depth + 1:
            found = INTEGER.match(rest)
            material_parent = int(found.group(1)) if found else None
            material_top_depth = depth
        elif tag == 'NUMSUBMTLS' and material_parent is not None and depth == material_top_depth + 1:
            found = INTEGER.match(rest)
            counts[material_parent] = int(found.group(1)) if found else -1
        if tag == 'GEOMOBJECT':
            row = {'name': '', 'ref': None, 'faces': 0, 'ids': [], 'bad_ids': 0,
                   'scope': depth, 'incomplete': False}
            rows.append(row)
            geom_start = depth
        elif row is not None:
            if tag == 'NODE_NAME' and not row['name']:
                name = STRING.search(rest)
                if name: row['name'] = name.group(1)[:64]
            elif tag == 'MATERIAL_REF':
                ref = INTEGER.match(rest)
                if ref: row['ref'] = int(ref.group(1))
                else: row['incomplete'] = True
            elif tag == 'MESH_FACE':
                row['faces'] += 1
            if tag == 'MESH_FACE' or tag == 'MESH_MTLID':
                ids = FACE_ID.findall(line)
                row['ids'].extend(int(x) for x in ids)
                if tag == 'MESH_MTLID' and not ids: row['bad_ids'] += 1
        depth += brace_delta(line)
        if material_depth is not None and depth <= material_depth:
            material_depth = None
            material_parent = None
            material_top_depth = None
        elif material_parent is not None and depth <= material_top_depth:
            material_parent = None
            material_top_depth = None
        if row is not None and depth <= geom_start:
            row = None
            geom_start = None
    if row is not None:
        row['incomplete'] = True
    for r in rows:
        sub = counts.get(r['ref'], 0)
        r['sub'] = sub
        r['range'] = (min(r['ids']), max(r['ids'])) if r['ids'] else None
        r['wrapped'] = sum(x >= sub for x in r['ids']) if sub > 0 else 0
        if r['incomplete'] or r['bad_ids'] or any(x < 0 for x in r['ids']):
            r['status'] = 'INVALID'
        elif r['ref'] is None:
            r['status'] = 'MISSING_REF'
        elif sub < 0:
            r['status'] = 'INVALID_SUBCOUNT'
        elif r['faces'] and len(r['ids']) not in (0, r['faces']):
            r['status'] = 'PARTIAL_FACE_IDS'
        elif sub > 0 and r['wrapped']:
            r['status'] = 'MULTISUB_WRAP'
        elif sub > 0:
            r['status'] = 'MULTISUB_IN_RANGE'
        else:
            r['status'] = 'SINGLE_OR_UNDECLARED'
    return rows, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--client', required=True)
    ap.add_argument('--source', required=True)
    args = ap.parse_args(argv)
    try:
        source = resolve_source(Path(args.client), args.source)
        if source.stat().st_size > 32*1024*1024:
            raise ValueError('ASE exceeds inspection limit')
        rows, counts = inspect_material_faces(source.read_bytes())
        if not rows:
            raise ValueError('no GEOMOBJECT found')
    except (OSError, ValueError) as exc:
        print('ASE_MATERIAL_269=FAIL_CLOSED ' + str(exc), file=sys.stderr)
        return 2
    for i, row in enumerate(rows):
        ids = f"{row['range'][0]}..{row['range'][1]}" if row['range'] else 'none'
        print(f"GEOM[{i}] name={row['name']!r} ref={row['ref']} "
              f"faces={row['faces']} ids={ids} subs={row['sub']} "
              f"wrapped={row['wrapped']} status={row['status']}")
    tally = Counter(r['status'] for r in rows)
    print('ASE_MATERIAL_269=INFO geom=' + str(len(rows)) +
          ' declared_multisubs=' + str(len(counts)) + ' ' +
          ' '.join(f'{name.lower()}={tally[name]}' for name in sorted(tally)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
