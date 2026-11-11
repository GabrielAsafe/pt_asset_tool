"""V12 Stage0.72 Blender view/paint safety gates (Blender-runtime separate)."""
from __future__ import annotations

from pathlib import Path
import math

from pt_asset_tool.stage072_view_axes import (
    GAME_TO_BLENDER_VIEW_MATRIX, VIEW_AXIS_PROFILE, matrix3_determinant, to_blender_view_xyz,
)
from pt_asset_tool.stage072_paint_policy import canonical_reference, partition_target_failures

ROOT = Path(__file__).resolve().parents[1] / 'pt_asset_tool'


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def minus(a, b):
    return tuple(x-y for x,y in zip(a,b))


def test_y_up_to_blender_z_up_is_a_reflection_and_reverses_floor_visibility():
    assert VIEW_AXIS_PROFILE == 'GAME_Y_UP_LEFT_HANDED_TO_BLENDER_Z_UP_RIGHT_HANDED'
    assert math.isclose(matrix3_determinant(), -1.0)
    assert to_blender_view_xyz((13, 48, -27)) == (13, -27, 48)
    # Representative legacy stage triangle with a -Y winding normal.
    face = ((0, 0, 0), (0, 0, 4), (4, 0, 0))
    old_cross = cross(minus(face[1], face[0]), minus(face[2], face[0]))
    assert old_cross[1] > 0 or old_cross[1] < 0
    face = ((0, 0, 0), (4, 0, 0), (0, 0, 4))
    old_cross = cross(minus(face[1], face[0]), minus(face[2], face[0]))
    assert old_cross[1] < 0
    bl = [to_blender_view_xyz(v) for v in face]
    new_cross = cross(minus(bl[1], bl[0]), minus(bl[2], bl[0]))
    assert new_cross[2] > 0  # ground faces up toward the Blender camera
    assert (GAME_TO_BLENDER_VIEW_MATRIX[1][2], GAME_TO_BLENDER_VIEW_MATRIX[2][1]) == (1,1)


def test_only_unrecoverable_ricarten_texture_can_be_skipped():
    raw = [
        {'slot': 141, 'material': 'PT_STAGE072_MAT_0173_tem_wall04.bmp__PT_PAINT', 'stage':0,
         'reason':'target_image_none', 'logical':r'field\ricarten\tem_wall04.bmp'},
    ]
    blockers, known=partition_target_failures(raw)
    assert blockers == [] and len(known)==1
    assert known[0]['resolution'] == 'KNOWN_MISSING_UNPAINTABLE_NO_SUBSTITUTE'
    assert canonical_reference(raw[0]['logical'])=='field/ricarten/tem_wall04.bmp'
    for bad in [
        dict(raw[0], logical='field/ricarten/tem_wall03.bmp'),
        dict(raw[0], reason='texture_unreadable'),
        dict(raw[0], stage=1),
        dict(raw[0], stage=None),
        dict(raw[0], logical='other/tem_wall04.bmp'),
    ]:
        blocked, accepted=partition_target_failures([bad])
        assert blocked==[bad] and accepted==[]


def test_blender_scripts_only_transform_disposable_proxy_and_report_partial():
    preview=(ROOT/'blender/open_stage072_preview.py').read_text()
    paint=(ROOT/'blender/open_stage072_paint.py').read_text()
    original_import=(ROOT/'blender/import_stage072.py').read_text()
    assert 'Matrix(GAME_TO_BLENDER_VIEW_MATRIX) @ Matrix.Scale' in preview
    assert 'mesh.transform(rebase @ src.matrix_world)' in preview
    assert 'axis @ ((source_world - center) * float(view_scale))' in preview
    assert 'set_stage_view_rotation(r3d)' in preview
    assert 'source_coordinates_unchanged=true persisted_blend_unsaved=true' in preview
    assert 'verts = [(v["x"] / 256.0, v["y"] / 256.0, v["z"] / 256.0)' in original_import
    assert 'blocking_errors, known_unpaintable = partition_target_failures(private_hard)' in paint
    assert 'polygon.hide = True' in paint
    assert 'known_unpaintable_texture_references' in paint
    assert 'PASS_WITH_KNOWN_MISSING_UNPAINTABLE' in paint
    assert 'source_texture_dependencies_complete' in paint
    assert 'view.set_stage_view_rotation(r3d)' in paint
