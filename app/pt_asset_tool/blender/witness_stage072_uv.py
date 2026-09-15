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
from pt_asset_tool.stage072_corpus import parse_stage072

UV_PREFIX = 'PT_STAGE072_TEXLINK_STAGE_'


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--smd', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--delta-u', type=float, default=0.03125)
    return p.parse_args(argv)


def main():
    a = _args()
    if not (1e-5 <= abs(float(a.delta_u)) <= 0.25):
        raise ValueError('delta-u magnitude must be between 1e-5 and 0.25')
    smd = pathlib.Path(a.smd).expanduser().resolve()
    source_sha = hashlib.sha256(smd.read_bytes()).hexdigest()
    parsed = parse_stage072(smd, include_payload=True)
    if parsed.get('full_parse') != 'PASS':
        raise RuntimeError('Stage0.72 source parser is not PASS')

    objs = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('pt_stage072_source_sha256')]
    if len(objs) != 1:
        raise RuntimeError(f'expected one Stage0.72 mesh, got {len(objs)}')
    obj = objs[0]
    mesh = obj.data
    if str(obj.get('pt_stage072_source_sha256') or '').lower() != source_sha.lower():
        raise RuntimeError('Blend/source sha256 mismatch')
    payload = parsed['payload']
    if len(mesh.polygons) != len(payload['faces']):
        raise RuntimeError('face count drift before witness')

    mats = {int(m['id']): m for m in parsed['materials']}
    candidates = []
    for fi, face in enumerate(payload['faces']):
        chain = face.get('texlink_chain') or []
        if not chain:
            continue
        mat = mats.get(int(face['material']))
        if mat is None or int(mat.get('TextureCounter') or 0) < len(chain):
            continue
        candidates.append((len(chain), fi))
    if not candidates:
        raise RuntimeError('no renderable Stage0.72 TexLink face available for UV witness')
    depth, fi = max(candidates, key=lambda x: (x[0], -x[1]))
    stage = depth - 1
    face = payload['faces'][fi]
    poly = mesh.polygons[fi]
    layer = mesh.uv_layers.get(f'{UV_PREFIX}{stage}')
    if layer is None:
        raise RuntimeError(f'missing UV stage layer {stage}')
    if len(poly.loop_indices) != 3:
        raise RuntimeError(f'expected triangle at face {fi}')
    loop_idx = int(poly.loop_indices[0])
    corner = 0
    ti = int(face['texlink_chain'][stage])
    tl = payload['texlinks'][ti]
    before_bl = layer.data[loop_idx].uv.copy()
    before_smd = (float(before_bl[0]), 1.0 - float(before_bl[1]))
    expected = (float(tl['u'][corner]), float(tl['v'][corner]))
    if max(abs(before_smd[j] - expected[j]) for j in range(2)) > 2e-6:
        raise RuntimeError(f'pristine Blender/source UV mismatch at face={fi} stage={stage}')

    layer.data[loop_idx].uv = (float(before_bl[0]) + float(a.delta_u), float(before_bl[1]))
    mesh.update()
    after_bl = layer.data[loop_idx].uv
    after_smd = (float(after_bl[0]), 1.0 - float(after_bl[1]))
    if after_smd[0] == before_smd[0]:
        raise RuntimeError('UV witness edit quantized away')

    edit = {
        'face_index': fi,
        'material_id': int(face['material']),
        'stage_index': stage,
        'corner': corner,
        'component': 'u',
        'before': float(before_smd[0]),
        'after': float(after_smd[0]),
        'before_uv': [float(before_smd[0]), float(before_smd[1])],
        'after_uv': [float(after_smd[0]), float(after_smd[1])],
        'delta_u': float(after_smd[0] - before_smd[0]),
        'texlink_index': ti,
        'source_vertex': int(face['vertices'][corner]),
        'loop_index': loop_idx,
    }
    bpy.context.scene['pt_stage072_roundtrip_witness'] = True
    bpy.context.scene['pt_stage072_roundtrip_source_sha256'] = source_sha
    bpy.context.scene['pt_stage072_roundtrip_policy'] = 'UV_ONLY_STAGEAREA_PRESERVED'
    bpy.context.scene['pt_stage072_roundtrip_edit'] = json.dumps(edit, ensure_ascii=False)

    out = pathlib.Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    result = {
        'tool': 'PT_STAGE072_UV_WITNESS_V1',
        'source': str(smd), 'source_sha256': source_sha,
        'output_blend': str(out), 'delta_u_requested': float(a.delta_u),
        'uv_edits': [edit],
        'geometry_edit_policy': 'FORBIDDEN_UNTIL_STAGEAREA_REBUILD_IS_PROVEN',
        'client_modified': False, 'check': 'PASS',
    }
    rp = pathlib.Path(a.report).expanduser().resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PT_STAGE072_UV_WITNESS_V1')
    print(f'face={fi} stage={stage} corner=0 before_u={edit["before"]:.9g} after_u={edit["after"]:.9g}')
    print(f'max_source_depth={parsed.get("max_texlink_depth")} witness_depth={depth}')
    print('geometry_edit_policy=FORBIDDEN_UNTIL_STAGEAREA_REBUILD_IS_PROVEN')
    print('stage072_uv_witness_check=PASS')


if __name__ == '__main__':
    main()
