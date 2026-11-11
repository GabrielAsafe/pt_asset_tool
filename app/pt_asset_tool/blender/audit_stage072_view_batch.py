"""Headless V12 view proxy probe; no Blender source/save mutations."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pt_asset_tool.stage072_view_axes import VIEW_AXIS_PROFILE, GAME_TO_BLENDER_VIEW_MATRIX, matrix3_determinant
from pt_asset_tool.blender import open_stage072_preview as view


def audit(report_path: pathlib.Path) -> dict:
    errors = []
    sources = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('pt_stage072_source_sha256')]
    before = []
    for o in sources:
        before.append((o.name, len(o.data.vertices), len(o.data.polygons),
                       tuple(tuple(float(c) for c in v.co) for v in list(o.data.vertices)[:16])))
    light_original = [o for o in bpy.data.objects if o.type == 'EMPTY' and o.name.startswith('PT_STAGE072_LIGHT_')]
    if len(sources) != 1:
        errors.append(f'expected_one_source_mesh_got_{len(sources)}')
    if matrix3_determinant() != -1:
        errors.append('incorrect_axis_handedness')
    if not errors:
        view.configure_stage072_view()
    proxies = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('pt_stage072_view_proxy')]
    after = []
    for o in sources:
        after.append((o.name, len(o.data.vertices), len(o.data.polygons),
                      tuple(tuple(float(c) for c in v.co) for v in list(o.data.vertices)[:16])))
    if before != after:
        errors.append('source_mesh_mutated_by_disposable_preview')
    if len(proxies) != len(sources):
        errors.append(f'proxy_mesh_count_mismatch_{len(proxies)}')
    for source, proxy in zip(sources, proxies):
        if proxy.data == source.data:
            errors.append('source_mesh_and_proxy_share_data')
        if proxy.get('pt_stage072_view_axis_profile') != VIEW_AXIS_PROFILE:
            errors.append('proxy_wrong_axis_profile')
        if not proxy.get('pt_stage072_view_only'):
            errors.append('proxy_not_marked_view_only')
        scale = float(proxy.get('pt_stage072_view_scale') or 0)
        if scale <= 0 or scale > 1:
            errors.append('invalid_view_scale')
        center = Vector(proxy['pt_stage072_source_world_center'])
        basis = Matrix(GAME_TO_BLENDER_VIEW_MATRIX).to_3x3()
        for srcv, dstv in zip(list(source.data.vertices)[:64], list(proxy.data.vertices)[:64]):
            src_world = source.matrix_world @ srcv.co
            expected = basis @ ((src_world - center) * scale)
            if max(abs(float(dstv.co[i]) - float(expected[i])) for i in range(3)) > 2e-4:
                errors.append('proxy_vertices_wrong_coordinate_basis')
                break
    lights = [o for o in bpy.data.objects if o.type == 'EMPTY' and o.name.startswith(view.VIEW_LIGHT_PREFIX)]
    if len(lights) != len(light_original):
        errors.append(f'light_proxy_mismatch_{len(lights)}_{len(light_original)}')
    report = {
        'format': 'PT_STAGE072_V13_HEADLESS_VIEW_CHECK_V1',
        'check': 'FAIL' if errors else 'PASS',
        'axis_profile': VIEW_AXIS_PROFILE,
        'determinant': matrix3_determinant(),
        'sources': len(sources), 'proxies': len(proxies),
        'source_lights': len(light_original), 'proxy_lights': len(lights),
        'source_mesh_unchanged': before == after,
        'preview_only': True, 'persisted_blend_unsaved': True,
        'not_artist_runtime_visual_certified': True,
        'errors': errors,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('PT_STAGE072_BATCH_VIEW=' + report['check'])
    return report


if __name__ == '__main__':
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', type=pathlib.Path, required=True)
    a = ap.parse_args(args)
    result = audit(a.report)
    if result['check'] != 'PASS':
        raise SystemExit(3)
