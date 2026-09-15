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


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--smd', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--vertex-index', type=int, required=True)
    p.add_argument('--delta-x-world', type=float, required=True)
    return p.parse_args(argv)


def main():
    a = _args()
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
    vi = int(a.vertex_index)
    if not 0 <= vi < len(mesh.vertices):
        raise ValueError('vertex index out of range')
    src = parsed['payload']['vertices'][vi]
    before_raw = [int(src['x']), int(src['y']), int(src['z'])]
    before_world = [q / 256.0 for q in before_raw]
    got = mesh.vertices[vi].co
    if max(abs(float(got[j]) - before_world[j]) for j in range(3)) > 1e-6:
        raise RuntimeError('pristine Blender/source vertex mismatch')

    mesh.vertices[vi].co.x = float(mesh.vertices[vi].co.x) + float(a.delta_x_world)
    mesh.update()
    after_world = [float(mesh.vertices[vi].co[j]) for j in range(3)]
    after_raw = [int(round(q * 256.0)) for q in after_world]
    if after_raw[1:] != before_raw[1:] or after_raw[0] == before_raw[0]:
        raise RuntimeError('geometry witness did not produce an x-only fixed-point change')
    # The Blend value must map back exactly enough to the intended fixed point.
    if abs(after_world[0] - after_raw[0] / 256.0) > 1e-6:
        raise RuntimeError('geometry witness is not exactly representable on Stage0.72 fixed grid')

    incident = []
    for fi, face in enumerate(parsed['payload']['faces']):
        if vi in [int(x) for x in face['vertices']]:
            incident.append(fi)
    edit = {
        'vertex_index': vi,
        'component': 'x',
        'before_raw': before_raw,
        'after_raw': after_raw,
        'before_world': before_world,
        'after_world': [q / 256.0 for q in after_raw],
        'delta_raw': after_raw[0] - before_raw[0],
        'delta_world': (after_raw[0] - before_raw[0]) / 256.0,
        'incident_faces': incident,
        'incident_face_count': len(incident),
    }
    bpy.context.scene['pt_stage072_geometry_roundtrip_witness'] = True
    bpy.context.scene['pt_stage072_roundtrip_source_sha256'] = source_sha
    bpy.context.scene['pt_stage072_roundtrip_policy'] = 'GEOMETRY_PROVENANCE_BRIDGE_CHANGED_FACES_CURRENT_SETNORMAL'
    bpy.context.scene['pt_stage072_geometry_roundtrip_edit'] = json.dumps(edit, ensure_ascii=False)

    out = pathlib.Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    result = {
        'tool': 'PT_STAGE072_GEOMETRY_WITNESS_V2',
        'source': str(smd),
        'source_sha256': source_sha,
        'output_blend': str(out),
        'geometry_edits': [edit],
        'client_modified': False,
        'check': 'PASS',
    }
    rp = pathlib.Path(a.report).expanduser().resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PT_STAGE072_GEOMETRY_WITNESS_V2')
    print(f'vertex={vi} before_raw={before_raw} after_raw={after_raw} incident_faces={len(incident)}')
    print('stage072_geometry_witness_check=PASS')


if __name__ == '__main__':
    main()
