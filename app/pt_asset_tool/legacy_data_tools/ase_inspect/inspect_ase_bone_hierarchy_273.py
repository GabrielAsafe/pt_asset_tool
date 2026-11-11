#!/usr/bin/env python3
"""Read-only ASE bone hierarchy inventory. Mirrors the offline native reader's Bip* selection."""
import argparse
from pathlib import Path
import re
import sys

from inspect_native_ase_265 import resolve_source, TOKEN
from inspect_ase_geometry_uv_266 import brace_delta

QUOTED = re.compile(r'"([^"\r\n]*)"')


def bone_hierarchy(data: bytes):
    rows = []
    depth = 0
    active = None
    opened = 0
    for line in data.decode('latin1').splitlines():
        match = TOKEN.match(line)
        tag, rest = match.groups() if match else (None, '')
        if tag == 'GEOMOBJECT':
            if active is not None:
                active['unterminated'] = True
            active = dict(name='', parent='', unterminated=False)
            rows.append(active)
            opened = depth
        elif active is not None and tag in ('NODE_NAME', 'NODE_PARENT'):
            quoted = QUOTED.search(rest)
            if quoted:
                active['name' if tag == 'NODE_NAME' else 'parent'] = quoted.group(1)[:31]
            else:
                active['unterminated'] = True
        depth += brace_delta(line)
        if active is not None and depth <= opened:
            active = None
    if active is not None:
        active['unterminated'] = True
    bones = [r for r in rows if r['name'].startswith('Bip')]
    problems = []
    if not bones:
        problems.append('bone_none')
    if len(bones) > 128:
        # The native pattern has 128 fixed slots: do not spend quadratic work
        # resolving a larger, already-rejected graph.
        return dict(geometry=len(rows), bones=len(bones), missing=[], roots=0,
                    order=[], problems=['bone_object_limit'], names=[])
    if any(r['unterminated'] for r in rows):
        problems.append('geometry_unterminated')
    parent = [-1] * len(bones)
    missing = []
    for index, node in enumerate(bones):
        if node['parent']:
            for previous, maybe in enumerate(bones):
                if maybe['name'].lower() == node['parent'].lower():
                    parent[index] = previous
                    break
            if parent[index] < 0:
                missing.append((node['name'], node['parent']))
    used = [i for i, p in enumerate(parent) if p < 0]
    for index in used:
        used.extend(i for i, p in enumerate(parent) if p == index)
    if len(used) != len(bones):
        problems.append('bone_hierarchy_invalid')
    return dict(geometry=len(rows), bones=len(bones), missing=missing,
                roots=sum(p < 0 for p in parent), order=used,
                problems=problems, names=[x['name'] for x in bones])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client', required=True)
    p.add_argument('--source', required=True)
    args = p.parse_args(argv)
    try:
        source = resolve_source(Path(args.client), args.source)
        if source.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('ASE exceeds inspection size limit')
        result = bone_hierarchy(source.read_bytes())
    except (OSError, ValueError) as err:
        print('ASE_BONES_273=FAIL_CLOSED ' + str(err), file=sys.stderr)
        return 2
    print(f"ASE_BONES_273=INFO geometry={result['geometry']} bones={result['bones']} "
          f"roots={result['roots']} missing_parents={len(result['missing'])} "
          f"topology={'VALID' if not result['problems'] else ','.join(result['problems'])}")
    for node, parent in result['missing'][:5]:
        print(f"MISSING_PARENT bone={node!r} reference={parent!r} (treated as root by legacy)")
    if result['problems']:
        print('ASE_BONES_273=FAIL_CLOSED invalid_bone_structure', file=sys.stderr)
        return 2
    print('ASE_BONES_273=PASS read_only=1')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
