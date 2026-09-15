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
from pt_asset_tool.stage072_roundtrip import strict_write_stage072_uv_witness

UV_PREFIX = 'PT_STAGE072_TEXLINK_STAGE_'
COLOR_NAME = 'PT_STAGE072_VERTEX_COLOR'


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--smd', required=True)
    p.add_argument('--witness', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--expected-source-sha256', required=True)
    return p.parse_args(argv)


def _key(x: dict):
    return (int(x['face_index']), int(x['stage_index']), int(x['corner']), str(x['component']).lower())


def _scan(parsed: dict, tolerance: float = 2e-6) -> tuple[list[dict], list[str]]:
    payload = parsed['payload']
    errors = []
    objs = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('pt_stage072_source_sha256')]
    if len(objs) != 1:
        return [], [f'expected one Stage0.72 mesh, got {len(objs)}']
    obj = objs[0]
    mesh = obj.data
    if str(obj.get('pt_stage072_source_sha256') or '').lower() != str(parsed['sha256']).lower():
        errors.append('source sha metadata mismatch')
    if len(mesh.vertices) != len(payload['vertices']): errors.append('vertex count drift')
    if len(mesh.polygons) != len(payload['faces']): errors.append('face count drift')

    # Geometry must remain source-exact in V1. Moving vertices without rebuilding
    # StageArea can stale the runtime spatial partition, so this writer refuses it.
    for i, (v, src) in enumerate(zip(mesh.vertices, payload['vertices'])):
        exp = (src['x']/256.0, src['y']/256.0, src['z']/256.0)
        if max(abs(float(v.co[j])-exp[j]) for j in range(3)) > 1e-6:
            errors.append(f'geometry edit forbidden: vertex {i}')
            if len(errors) >= 20: break

    depth_attr = mesh.attributes.get('PT_STAGE072_TEXLINK_DEPTH')
    mid_attr = mesh.attributes.get('PT_STAGE072_MATERIAL_ID')
    if depth_attr is None or mid_attr is None:
        errors.append('missing Stage0.72 face attributes')
    changes = []
    for fi, (poly, srcf) in enumerate(zip(mesh.polygons, payload['faces'])):
        if tuple(poly.vertices) != tuple(srcf['vertices']) and len(errors) < 20:
            errors.append(f'face topology drift {fi}')
        if depth_attr is not None and int(depth_attr.data[fi].value) != len(srcf.get('texlink_chain') or []) and len(errors) < 20:
            errors.append(f'face depth drift {fi}')
        if mid_attr is not None and int(mid_attr.data[fi].value) != int(srcf['material']) and len(errors) < 20:
            errors.append(f'face material drift {fi}')
        for stage, ti in enumerate(srcf.get('texlink_chain') or []):
            layer = mesh.uv_layers.get(f'{UV_PREFIX}{stage}')
            if layer is None:
                errors.append(f'missing UV stage {stage}')
                continue
            tl = payload['texlinks'][ti]
            for corner, li in enumerate(poly.loop_indices):
                got = layer.data[li].uv
                got_smd = (float(got[0]), 1.0-float(got[1]))
                exp = (float(tl['u'][corner]), float(tl['v'][corner]))
                for component, ci in (('u',0),('v',1)):
                    if abs(got_smd[ci]-exp[ci]) > tolerance:
                        changes.append({
                            'face_index': fi, 'material_id': int(srcf['material']),
                            'stage_index': stage, 'corner': corner, 'component': component,
                            'before': exp[ci], 'after': got_smd[ci],
                            'texlink_index': int(ti), 'loop_index': int(li),
                        })

    colors = mesh.color_attributes.get(COLOR_NAME)
    if colors is None:
        errors.append('missing vertex color attribute')
    else:
        for i, src in enumerate(payload['vertices']):
            exp = tuple(max(0.0, min(1.0, float(x)/255.0)) for x in src['color'])
            got = colors.data[i].color
            if max(abs(float(got[j])-exp[j]) for j in range(4)) > tolerance:
                errors.append(f'vertex color edit forbidden: vertex {i}')
                if len(errors) >= 20: break

    lights = sorted([o for o in bpy.data.objects if o.name.startswith('PT_STAGE072_LIGHT_')], key=lambda x:x.name)
    if len(lights) != len(payload['lights']):
        errors.append('light count drift')
    for i, (lo, src) in enumerate(zip(lights, payload['lights'])):
        exp_pos = (src['x']/256.0, src['y']/256.0, src['z']/256.0)
        if max(abs(float(lo.location[j])-exp_pos[j]) for j in range(3)) > 1e-6:
            errors.append(f'light position drift {i}')
        for k in ('type','x','y','z','range','r','g','b'):
            if int(lo.get(f'pt_stage072_{k}', -999999999)) != int(src[k]):
                errors.append(f'light metadata drift {i}:{k}')
                break

    expected_depth = {}
    for f in payload['faces']:
        mid = int(f['material'])
        expected_depth[mid] = max(expected_depth.get(mid, 0), len(f.get('texlink_chain') or []))
    mats_by_id = {int(m.get('pt_stage072_material_id', -1)):m for m in mesh.materials if m is not None}
    src_by_id = {int(m['id']):m for m in parsed['materials']}
    for mid, depth in expected_depth.items():
        mat = mats_by_id.get(mid)
        if mat is None:
            errors.append(f'missing used material {mid}')
            continue
        src = src_by_id[mid]
        for stage in range(depth):
            logical = (src.get('textures') or [])[stage].get('Name') if stage < len(src.get('textures') or []) else ''
            op = int((src.get('TextureStageState') or [0]*8)[stage])
            form = int((src.get('TextureFormState') or [0]*8)[stage])
            if str(mat.get(f'pt_stage072_stage{stage}_texture','')) != str(logical or ''):
                errors.append(f'material texture metadata drift {mid}:{stage}')
            if int(mat.get(f'pt_stage072_stage{stage}_op',-1)) != op:
                errors.append(f'material op metadata drift {mid}:{stage}')
            if int(mat.get(f'pt_stage072_stage{stage}_form',-1)) != form:
                errors.append(f'material form metadata drift {mid}:{stage}')

    scene = bpy.context.scene
    if int(scene.get('pt_stage072_contrast', -999999999)) != int(parsed['lighting']['Contrast']): errors.append('scene contrast drift')
    if int(scene.get('pt_stage072_bright', -999999999)) != int(parsed['lighting']['Bright']): errors.append('scene bright drift')
    if list(scene.get('pt_stage072_vectlight', [])) != list(parsed['lighting']['VectLight']): errors.append('scene VectLight drift')
    return changes, errors


def main():
    a = _args()
    smd = pathlib.Path(a.smd).expanduser().resolve()
    source_sha = hashlib.sha256(smd.read_bytes()).hexdigest()
    if source_sha.lower() != str(a.expected_source_sha256).lower():
        raise RuntimeError('source sha256 drift')
    witness_path = pathlib.Path(a.witness).expanduser().resolve()
    witness = json.loads(witness_path.read_text(encoding='utf-8'))
    if str(witness.get('source_sha256') or '').lower() != source_sha.lower():
        raise RuntimeError('witness/source sha256 mismatch')
    scene_sha = str(bpy.context.scene.get('pt_stage072_roundtrip_source_sha256') or '')
    if scene_sha and scene_sha.lower() != source_sha.lower():
        raise RuntimeError('edited Blend was created from a different Stage0.72 source')

    parsed = parse_stage072(smd, include_payload=True)
    changes, invariant_errors = _scan(parsed)
    if invariant_errors:
        raise RuntimeError(f'strict Stage0.72 writer refuses non-UV edits: {invariant_errors[:8]}')
    expected = list(witness.get('uv_edits') or witness.get('edits') or [])
    got_by_key = {_key(x):x for x in changes}
    exp_by_key = {_key(x):x for x in expected}
    if set(got_by_key) != set(exp_by_key):
        raise RuntimeError(f'strict Stage0.72 writer refuses unexpected UV edits: expected={sorted(exp_by_key)} actual={sorted(got_by_key)}')
    normalized = []
    for key, exp in exp_by_key.items():
        got = got_by_key[key]
        if abs(float(got['after'])-float(exp['after'])) > 2e-6:
            raise RuntimeError(f'witness edited value drift at {key}')
        row = dict(exp)
        row['after'] = float(got['after'])
        normalized.append(row)
    strict_witness = dict(witness)
    strict_witness['uv_edits'] = normalized
    normalized_path = pathlib.Path(a.report).expanduser().resolve().with_suffix('.normalized_witness.json')
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text(json.dumps(strict_witness, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    result = strict_write_stage072_uv_witness(
        smd, pathlib.Path(a.out).expanduser().resolve(), normalized_path,
        expected_source_sha256=source_sha,
    )
    result.update({
        'blender_uv_change_scan_count': len(changes),
        'blender_uv_changes': changes,
        'strict_blender_edit_set': 'PASS',
        'geometry_edit_policy': 'FORBIDDEN_UNTIL_STAGEAREA_REBUILD_IS_PROVEN',
        'witness_report': str(witness_path),
        'normalized_witness_report': str(normalized_path),
    })
    rp = pathlib.Path(a.report).expanduser().resolve()
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('PT_STAGE072_STRICT_UV_WRITER_V1')
    print(f'blender_uv_change_scan_count={len(changes)}')
    print('strict_blender_edit_set=PASS')
    print('geometry_edit_policy=FORBIDDEN_UNTIL_STAGEAREA_REBUILD_IS_PROVEN')
    print(f"output={result['output']}")
    print('stage072_uv_writer_check=PASS')


if __name__ == '__main__':
    main()
