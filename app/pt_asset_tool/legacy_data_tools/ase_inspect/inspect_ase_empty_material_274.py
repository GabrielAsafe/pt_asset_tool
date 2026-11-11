#!/usr/bin/env python3
"""Inspect zero-count ASE material tables and unbound per-face IDs (read only)."""
import argparse
from pathlib import Path
import sys
from inspect_native_ase_265 import inspect, resolve_source
from inspect_ase_face_material_269 import inspect_material_faces

MAX_ASE_BYTES = 32 * 1024 * 1024


def classify(data):
    info = inspect(data)
    rows, _ = inspect_material_faces(data)
    empty = info['material_lists'] == 1 and info['material_count'] == 0
    for row in rows:
        if row['status'] in ('INVALID', 'PARTIAL_FACE_IDS'):
            row['empty_table_274'] = 'INVALID_FACES'
        elif not empty:
            row['empty_table_274'] = 'NOT_EXPLICIT_EMPTY_TABLE'
        elif row['ref'] is not None:
            row['empty_table_274'] = 'EXPLICIT_MATERIAL_REF'
        elif any(x < 0 or x > 65535 for x in row['ids']):
            row['empty_table_274'] = 'INVALID_UNBOUND_ID'
        else:
            row['empty_table_274'] = 'EMPTY_TABLE_CANDIDATE'
    return info, rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client', required=True)
    p.add_argument('--source', required=True)
    a = p.parse_args(argv)
    try:
        path = resolve_source(Path(a.client), a.source)
        if path.stat().st_size > MAX_ASE_BYTES:
            raise ValueError('ASE exceeds 32 MiB')
        info, rows = classify(path.read_bytes())
        if not rows:
            raise ValueError('no GEOMOBJECT found')
    except (OSError, ValueError) as exc:
        print('ASE_EMPTY_MATERIAL_274=FAIL_CLOSED '+str(exc), file=sys.stderr)
        return 2
    print(f"MATERIAL_LISTS={info['material_lists']} MATERIAL_COUNT={info['material_count']}")
    for i, row in enumerate(rows):
        print(f"GEOM[{i}] name={row['name']!r} faces={row['faces']} "
              f"ref={row['ref']} ids={row['range']} status={row['empty_table_274']}")
    good = sum(row['empty_table_274'] == 'EMPTY_TABLE_CANDIDATE' for row in rows)
    print(f'ASE_EMPTY_MATERIAL_274=INFO candidates={good} total={len(rows)} read_only=1')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
