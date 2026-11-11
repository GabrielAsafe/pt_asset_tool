#!/usr/bin/env python3
"""Read-only ASE materialless mesh inspection; no conversion or output files."""
import argparse
from collections import Counter
from pathlib import Path
import sys
from inspect_native_ase_265 import inspect, resolve_source
from inspect_ase_face_material_269 import inspect_material_faces

MAX_ASE_BYTES = 32 * 1024 * 1024


def classify(data):
    global_info = inspect(data)
    rows, _ = inspect_material_faces(data)
    material_lists = global_info['material_lists']
    for row in rows:
        if row['status'] == 'INVALID' or row['status'] == 'PARTIAL_FACE_IDS':
            row['materialless'] = 'REJECT_INVALID_FACE_IDS'
        elif material_lists:
            row['materialless'] = 'MATERIAL_TABLE_PRESENT'
        elif row['ref'] is not None:
            row['materialless'] = 'REJECT_EXPLICIT_REF'
        elif any(id_ != 0 for id_ in row['ids']):
            row['materialless'] = 'REJECT_NONZERO_FACE_ID'
        else:
            row['materialless'] = 'NEUTRAL_CANDIDATE'
    return global_info, rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client', required=True)
    p.add_argument('--source', required=True)
    a = p.parse_args(argv)
    try:
        source = resolve_source(Path(a.client), a.source)
        if source.stat().st_size > MAX_ASE_BYTES:
            raise ValueError('ASE exceeds 32 MiB limit')
        info, rows = classify(source.read_bytes())
        if not rows:
            raise ValueError('no GEOMOBJECT found')
    except (OSError, ValueError) as exc:
        print('ASE_MATERIALLESS_271=FAIL_CLOSED ' + str(exc), file=sys.stderr)
        return 2
    print(f"MATERIAL_LISTS={info['material_lists']} MATERIAL_COUNT={info['material_count']}")
    for i, r in enumerate(rows):
        print(f"GEOM[{i}] name={r['name']!r} ref={r['ref']} faces={r['faces']} "
              f"ids={r['range']} status={r['materialless']}")
    counts = Counter(r['materialless'] for r in rows)
    print('ASE_MATERIALLESS_271=INFO geometry=' + str(len(rows)) + ' ' +
          ' '.join(f'{key.lower()}={counts[key]}' for key in sorted(counts)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
