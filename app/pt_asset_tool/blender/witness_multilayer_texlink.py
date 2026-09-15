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
from pt_asset_tool.blender.apply_multilayer_texlink import _map_objects


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--smd', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--delta-u', type=float, default=0.03125)
    return p.parse_args(argv)


def _profile_by_material(report: dict) -> dict[int, dict]:
    return {int(x['material_id']): x for x in (report.get('multilayer_materials') or [])}


def _candidate_score(src_obj: dict, obj, face: dict, profiles: dict[int, dict]):
    mid = int(face['material_id'])
    profile = profiles.get(mid) or {}
    textures = profile.get('textures') or []
    form1 = int(textures[1].get('form_state') or 0) if len(textures) > 1 else 0
    chain = face.get('chain') or []
    distinct = False
    if len(chain) > 1:
        distinct = max(
            abs(float(chain[0]['uv'][j][k]) - float(chain[1]['uv'][j][k]))
            for j in range(3) for k in range(2)
        ) > 1e-7
    selected = bool(int(obj.get('pt_inx_selected', 1)))
    # Prefer a currently selected/visible LOD object, then a stage whose
    # serialized UV is actually used (non-reflection), then distinct UVs.
    return (
        1 if selected else 0,
        1 if form1 != 5 else 0,
        1 if distinct else 0,
        int(src_obj.get('faces') or 0),
    )


def main():
    a = _args()
    if not (1e-5 <= abs(float(a.delta_u)) <= 0.25):
        raise ValueError('delta-u must have magnitude between 1e-5 and 0.25')
    smd = pathlib.Path(a.smd).expanduser().resolve()
    source_bytes = smd.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    parsed = parse_multilayer_semantics(smd)
    if parsed.get('source_semantics') != 'PASS' or int(parsed.get('max_layers') or 0) != 2:
        raise RuntimeError('witness requires a source-proven two-stage TexLink SMD')

    pairs = _map_objects(parsed)
    profiles = _profile_by_material(parsed)
    candidates = []
    for src_obj, obj in pairs:
        mesh = obj.data
        uv1 = mesh.uv_layers.get('PT_TEXLINK_STAGE_1')
        if uv1 is None:
            continue
        for fi, (face, poly) in enumerate(zip(src_obj['face_rows'], mesh.polygons)):
            if len(face.get('chain') or []) != 2:
                continue
            score = _candidate_score(src_obj, obj, face, profiles)
            candidates.append((score, int(src_obj['index']), fi, src_obj, obj, face, poly))
    if not candidates:
        raise RuntimeError('no two-stage face available for TexLink UV witness')
    candidates.sort(key=lambda row: row[0], reverse=True)
    _score, oi, fi, src_obj, obj, face, poly = candidates[0]

    source_corner = 0
    source_vertex = int(face['vertices'][source_corner])
    loop_idx = None
    for li in poly.loop_indices:
        if int(obj.data.loops[li].vertex_index) == source_vertex:
            loop_idx = int(li)
            break
    if loop_idx is None:
        raise RuntimeError(f'cannot map witness corner for {obj.name}:{fi}')

    uv1 = obj.data.uv_layers['PT_TEXLINK_STAGE_1']
    before_bl = (float(uv1.data[loop_idx].uv[0]), float(uv1.data[loop_idx].uv[1]))
    before_smd = (before_bl[0], 1.0 - before_bl[1])
    expected_source = face['chain'][1]['uv'][source_corner]
    if max(abs(before_smd[k] - float(expected_source[k])) for k in range(2)) > 1e-6:
        raise RuntimeError(
            f'witness source/Blender mismatch before edit: blender={before_smd} source={expected_source}'
        )

    after_u = before_bl[0] + float(a.delta_u)
    uv1.data[loop_idx].uv = (after_u, before_bl[1])
    obj.data.update()
    after_bl = (float(uv1.data[loop_idx].uv[0]), float(uv1.data[loop_idx].uv[1]))
    after_smd = (after_bl[0], 1.0 - after_bl[1])
    if after_smd[0] == before_smd[0]:
        raise RuntimeError('UV witness edit quantized away in Blender')

    mid = int(face['material_id'])
    profile = profiles.get(mid) or {}
    textures = profile.get('textures') or []
    stage1_meta = textures[1] if len(textures) > 1 else {}
    edit = {
        'object_index': oi,
        'object_name': str(src_obj['name']),
        'blender_object_name': str(obj.name),
        'face_index': fi,
        'material_id': mid,
        'stage_index': 1,
        'corner': source_corner,
        'source_vertex': source_vertex,
        'loop_index': loop_idx,
        'component': 'u',
        'before': float(before_smd[0]),
        'after': float(after_smd[0]),
        'before_uv': [float(before_smd[0]), float(before_smd[1])],
        'after_uv': [float(after_smd[0]), float(after_smd[1])],
        'delta_u': float(after_smd[0] - before_smd[0]),
        'profile': profile.get('profile'),
        'stage1_form_state': stage1_meta.get('form_state'),
        'stage1_form_state_name': stage1_meta.get('form_state_name'),
        'stage1_stage_state': stage1_meta.get('stage_state'),
        'stage1_stage_state_name': stage1_meta.get('stage_state_name'),
        'texlink_index': int(face['chain'][1]['texlink_index']),
        'texlink_file_offset': int(face['chain'][1]['file_offset']),
    }

    scene = bpy.context.scene
    scene['pt_texlink_roundtrip_witness'] = True
    scene['pt_texlink_roundtrip_source'] = str(smd)
    scene['pt_texlink_roundtrip_source_sha256'] = source_sha
    scene['pt_texlink_roundtrip_edit'] = json.dumps(edit, ensure_ascii=False)

    out = pathlib.Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    result = {
        'tool': 'PT_MULTILAYER_TEXLINK_UV_WITNESS_V1',
        'source': str(smd),
        'source_sha256': source_sha,
        'output_blend': str(out),
        'delta_u_requested': float(a.delta_u),
        'edits': [edit],
        'client_modified': False,
        'check': 'PASS',
    }
    rp = pathlib.Path(a.report).expanduser().resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PT_MULTILAYER_TEXLINK_UV_WITNESS_V1')
    print(f"object={edit['object_name']} blender={edit['blender_object_name']} face={fi} stage=1 corner=0")
    print(f"profile={edit.get('profile')} before_u={edit['before']:.9g} after_u={edit['after']:.9g}")
    print(f'output={out}')
    print('client_modified=False')
    print('texlink_uv_witness_check=PASS')


if __name__ == '__main__':
    main()
