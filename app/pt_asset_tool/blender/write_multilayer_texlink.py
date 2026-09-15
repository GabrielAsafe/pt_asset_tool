#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pt_asset_tool.multilayer_texlink import parse_multilayer_semantics
from pt_asset_tool.texlink_roundtrip import strict_write_texlink_uv_witness
from pt_asset_tool.blender.apply_multilayer_texlink import _map_objects


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--smd', required=True)
    p.add_argument('--witness', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--expected-source-sha256', required=True)
    return p.parse_args(argv)


def _source_corner_for_loop(face: dict, mesh, loop_idx: int) -> int:
    vi = int(mesh.loops[loop_idx].vertex_index)
    verts = [int(x) for x in face['vertices']]
    try:
        return verts.index(vi)
    except ValueError:
        raise RuntimeError(f'cannot map Blender loop vertex {vi} to source face {verts}')


def _scan_blender_uv_changes(parsed: dict, tolerance: float = 1e-6) -> list[dict]:
    pairs = _map_objects(parsed)
    changes = []
    for src_obj, obj in pairs:
        mesh = obj.data
        uv0 = mesh.uv_layers.get('PT_TEXLINK_STAGE_0')
        uv1 = mesh.uv_layers.get('PT_TEXLINK_STAGE_1')
        depth = mesh.attributes.get('pt_texlink_depth')
        if uv0 is None or uv1 is None or depth is None:
            raise RuntimeError(f'missing TexLink UV/depth storage on {obj.name}')
        for fi, (face, poly) in enumerate(zip(src_obj['face_rows'], mesh.polygons)):
            chain = face.get('chain') or []
            if int(depth.data[fi].value) != len(chain):
                raise RuntimeError(f'TexLink depth drift in Blender: {obj.name}:{fi}')
            for loop_idx in poly.loop_indices:
                corner = _source_corner_for_loop(face, mesh, int(loop_idx))
                for stage_index in range(min(2, len(chain))):
                    layer = uv0 if stage_index == 0 else uv1
                    got = layer.data[loop_idx].uv
                    got_smd = (float(got[0]), 1.0 - float(got[1]))
                    exp = chain[stage_index]['uv'][corner]
                    for component, ci in (('u', 0), ('v', 1)):
                        if abs(float(got_smd[ci]) - float(exp[ci])) > tolerance:
                            changes.append({
                                'object_index': int(src_obj['index']),
                                'object_name': str(src_obj['name']),
                                'blender_object_name': str(obj.name),
                                'face_index': fi,
                                'material_id': int(face['material_id']),
                                'stage_index': stage_index,
                                'corner': corner,
                                'component': component,
                                'before': float(exp[ci]),
                                'after': float(got_smd[ci]),
                                'loop_index': int(loop_idx),
                                'texlink_index': int(chain[stage_index]['texlink_index']),
                                'texlink_file_offset': int(chain[stage_index]['file_offset']),
                            })
    return changes


def _key(row: dict):
    return (
        int(row['object_index']), int(row['face_index']), int(row['stage_index']),
        int(row['corner']), str(row['component']).lower(),
    )


def main():
    a = _args()
    smd = pathlib.Path(a.smd).expanduser().resolve()
    source_sha = hashlib.sha256(smd.read_bytes()).hexdigest()
    if source_sha.lower() != str(a.expected_source_sha256).lower():
        raise RuntimeError(f'source sha256 drift: expected={a.expected_source_sha256} actual={source_sha}')
    witness_path = pathlib.Path(a.witness).expanduser().resolve()
    witness = json.loads(witness_path.read_text(encoding='utf-8'))
    if str(witness.get('source_sha256') or '').lower() != source_sha.lower():
        raise RuntimeError('witness/source sha256 mismatch')

    scene = bpy.context.scene
    scene_sha = str(scene.get('pt_texlink_roundtrip_source_sha256') or '')
    if scene_sha and scene_sha.lower() != source_sha.lower():
        raise RuntimeError('edited Blend was created from a different SMD source')

    parsed = parse_multilayer_semantics(smd)
    changes = _scan_blender_uv_changes(parsed)
    expected = list(witness.get('edits') or [])
    got_by_key = {_key(x): x for x in changes}
    exp_by_key = {_key(x): x for x in expected}
    if set(got_by_key) != set(exp_by_key):
        raise RuntimeError(
            'strict TexLink writer refuses unexpected Blender UV edits: '
            f'expected={sorted(exp_by_key)} actual={sorted(got_by_key)}'
        )
    normalized = []
    for key, exp in exp_by_key.items():
        got = got_by_key[key]
        if abs(float(got['after']) - float(exp['after'])) > 1e-6:
            raise RuntimeError(f'witness edited value drift at {key}: witness={exp["after"]} blender={got["after"]}')
        row = dict(exp)
        row['after'] = float(got['after'])
        normalized.append(row)

    strict_witness = dict(witness)
    strict_witness['edits'] = normalized
    normalized_path = pathlib.Path(a.report).expanduser().resolve().with_suffix('.normalized_witness.json')
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text(json.dumps(strict_witness, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    result = strict_write_texlink_uv_witness(
        smd,
        pathlib.Path(a.out).expanduser().resolve(),
        normalized_path,
        expected_source_sha256=source_sha,
    )
    result.update({
        'blender_change_scan_count': len(changes),
        'blender_changes': changes,
        'witness_report': str(witness_path),
        'normalized_witness_report': str(normalized_path),
        'strict_blender_edit_set': 'PASS',
    })
    rp = pathlib.Path(a.report).expanduser().resolve()
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PT_MULTILAYER_TEXLINK_STRICT_WRITER_V1')
    print(f'blender_change_scan_count={len(changes)}')
    print('strict_blender_edit_set=PASS')
    print(f"output={result['output']}")
    print('client_modified=False')
    print('texlink_writer_check=PASS')


if __name__ == '__main__':
    main()
