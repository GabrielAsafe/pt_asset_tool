"""V19: numerically stable stage view proxy for large absolute game coordinates.

Pure-Python/AST regression tests run without Blender; real headless Blender
coverage remains the V13 worker validation in the user's local installation.
"""
from __future__ import annotations

import ast
from pathlib import Path
from struct import pack, unpack

from pt_asset_tool.stage072_view_axes import matrix3_determinant, to_blender_view_xyz


SOURCE = Path(__file__).resolve().parents[1] / 'pt_asset_tool/blender/open_stage072_preview.py'


def _f32(value):
    return unpack('<f', pack('<f', float(value)))[0]


def _old_composed_axis_position(world, center, scale):
    """Binary32 approximation to old (axis @ scale @ translation) @ position."""
    scale = _f32(scale)
    return tuple(
        _f32(_f32(scale * _f32(world[i])) + _f32(-_f32(scale * _f32(center[i]))))
        for i in (0, 2, 1)
    )


def _stable_staged_axis_position(world, center, scale):
    """Float32 mesh operations, offset before scaling, then Y/Z swap."""
    return tuple(
        _f32(_f32(_f32(world[i]) - _f32(center[i])) * _f32(scale))
        for i in (0, 2, 1)
    )


def _ideal_axis_position(world, center, scale):
    return tuple((float(world[i]) - _f32(center[i])) * _f32(scale) for i in (0, 2, 1))


def test_darkboss_large_floating_origin_regression():
    # Center and scale are from the actual V18 dark_boss headless log.
    center = (198296.328125, 1461.146484, 241891.828125)
    scale = 0.0276040543
    world = (center[0] + 800.0, center[1] + 40.0, center[2] + 200.0)
    old = _old_composed_axis_position(world, center, scale)
    new = _stable_staged_axis_position(world, center, scale)
    ideal = _ideal_axis_position(world, center, scale)
    assert max(abs(a-b) for a, b in zip(old, ideal)) > 2e-4
    assert max(abs(a-b) for a, b in zip(new, ideal)) < 5e-6
    assert max(abs(a-b) for a, b in zip(new, old)) > 2e-4


def test_view_transform_axis_and_handedness_are_unchanged():
    assert matrix3_determinant() == -1
    assert to_blender_view_xyz((7, 8, 9)) == (7, 9, 8)
    center = (198296.328125, 1461.146484, 241891.828125)
    stable = _stable_staged_axis_position((center[0]+12, center[1]+20, center[2]+30), center, 0.05)
    assert all(abs(x-y) < 2e-5 for x, y in zip(stable, (0.6, 1.5, 1.0)))


def test_view_builder_applies_world_then_offset_then_scale_then_axes_to_copy():
    text = SOURCE.read_text(encoding='utf-8')
    tree = ast.parse(text)
    fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == '_build_stage_view_proxies')
    rendered = ast.unparse(fn)
    expressions = [
        'mesh = src.data.copy()',
        'mesh.transform(src.matrix_world)',
        'mesh.transform(center_translation)',
        'mesh.transform(normalized_scale)',
        'mesh.transform(axis_matrix)',
    ]
    locations = [rendered.index(needle) for needle in expressions]
    assert locations == sorted(locations), 'Rebasing must occur before scaling/axis swap'
    assert 'rebase @ src.matrix_world' not in rendered
    assert 'src.data.transform' not in rendered
    assert 'src.hide_set(True)' in rendered  # original stays hidden for view only
    assert 'pt_stage072_view_proxy' in rendered
