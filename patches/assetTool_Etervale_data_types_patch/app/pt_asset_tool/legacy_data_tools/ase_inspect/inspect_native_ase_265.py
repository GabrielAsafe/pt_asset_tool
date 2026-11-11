#!/usr/bin/env python3
"""Read-only structural ASE inspection for the native SUMMIT model cook.

Does not convert files, run Wine, create logs, or modify content. Results are
hints, not a substitute for a successful native parser + SMD/SMB readback.
"""
import argparse
from collections import Counter
from pathlib import Path
import re
import sys

TOKEN = re.compile(r'^\s*\*([A-Z][A-Z_0-9]*)\b(.*)$')
INTEGER = re.compile(r'^\s*:?\s*(-?\d+)')
MAPS = {'MAP_DIFFUSE', 'MAP_AMBIENT', 'MAP_OPACITY'}
UV_FIELDS = {'UVW_U_OFFSET', 'UVW_V_OFFSET', 'UVW_U_TILING', 'UVW_V_TILING', 'UVW_ANGLE'}


def resolve_source(client: Path, name: str) -> Path:
    if not name or '\\' in name or '\x00' in name or name.startswith('/'):
        raise ValueError('source must be a relative ASE path')
    parts = name.split('/')
    if any(part in ('', '.', '..') for part in parts) or not name.lower().endswith('.ase'):
        raise ValueError('unsafe ASE source path')
    root = client.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('client path is not a directory')
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError('symlink refused')
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError('source is not a regular file inside client')
    return resolved


def inspect(data: bytes) -> dict:
    # A text ASE can be ISO-8859-1/Windows-1252; tokens are ASCII.
    counts = Counter()
    values = {}
    issues = []
    current_map = None
    diffuse_bitmap = False
    ignored_uv = 0
    diffuse_uv_before_bitmap = 0
    geom_names = []
    invalid_numeric = 0
    for raw in data.decode('latin1').splitlines():
        match = TOKEN.match(raw)
        if not match:
            continue
        name, rest = match.groups()
        counts[name] += 1
        if name in MAPS:
            current_map = name
            if name == 'MAP_DIFFUSE':
                diffuse_bitmap = False
        elif name == 'MATERIAL':
            current_map = None
        elif name == 'SUBMATERIAL':
            current_map = None
        elif name == 'BITMAP' and current_map == 'MAP_DIFFUSE':
            diffuse_bitmap = True
        elif name in UV_FIELDS:
            if current_map != 'MAP_DIFFUSE':
                ignored_uv += 1
            elif not diffuse_bitmap:
                diffuse_uv_before_bitmap += 1
        if name in ('MATERIAL_COUNT', 'MESH_NUMVERTEX', 'MESH_NUMFACES',
                    'MESH_NUMTVERTEX', 'MESH_NUMTVFACES', 'MATERIAL_REF', 'NUMSUBMTLS'):
            numeric = INTEGER.match(rest)
            if numeric:
                values.setdefault(name, []).append(int(numeric.group(1)))
            else:
                invalid_numeric += 1
        if name == 'NODE_NAME' and len(geom_names) < 6:
            m = re.search(r'"([^"\r\n]*)"', rest)
            if m:
                geom_names.append(m.group(1)[:48])
    if not counts['GEOMOBJECT']:
        issues.append('no_geomobject')
    if counts['MESH_FACE'] and not counts['MATERIAL_LIST']:
        issues.append('faces_without_material_list')
    if counts['MESH_FACE'] and not counts['MATERIAL_REF']:
        issues.append('faces_without_material_ref')
    if diffuse_uv_before_bitmap:
        issues.append('diffuse_uv_before_bitmap')
    if invalid_numeric:
        issues.append('invalid_declared_integer')
    if any(v < 0 for vs in values.values() for v in vs):
        issues.append('negative_declared_value')
    return {
        'geometry': counts['GEOMOBJECT'],
        'declared_faces': sum(values.get('MESH_NUMFACES', [])),
        'actual_faces': counts['MESH_FACE'],
        'material_lists': counts['MATERIAL_LIST'],
        'material_count': sum(values.get('MATERIAL_COUNT', [])),
        'diffuse_maps': counts['MAP_DIFFUSE'],
        'opacity_maps': counts['MAP_OPACITY'],
        'ambient_maps': counts['MAP_AMBIENT'],
        'ignored_uv_fields': ignored_uv,
        'diffuse_uv_before_bitmap': diffuse_uv_before_bitmap,
        'nodes': geom_names,
        'issues': issues,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client', required=True)
    p.add_argument('--source', required=True, help='ASE path relative to client')
    a = p.parse_args(argv)
    try:
        src = resolve_source(Path(a.client), a.source)
        if src.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('ASE exceeds inspection size limit')
        result = inspect(src.read_bytes())
    except (OSError, ValueError) as exc:
        print('ASE_INSPECT_265=FAIL_CLOSED ' + str(exc), file=sys.stderr)
        return 2
    print('ASE_INSPECT_265=INFO ' + ' '.join(f'{k}={v}' for k, v in result.items()
        if k not in ('issues', 'nodes')))
    print('NODES=' + repr(result['nodes']))
    print('POTENTIAL_ISSUES=' + (','.join(result['issues']) or 'none'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
