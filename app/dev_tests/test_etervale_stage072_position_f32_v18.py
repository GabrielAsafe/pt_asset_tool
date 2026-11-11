"""V18: binary32 Stage 0.72 vertex/light persistence; no game file changes."""
from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from pt_asset_tool.stage072_position_float32 import (
    binary32_position, expected_blender_position, position_transport_error,
)

ROOT = Path(__file__).resolve().parents[1]


def test_dark_boss_exact_reported_delta_is_float32_quantization_not_edit():
    # 16,777,217 raw fixed-point units -> 65,536.00390625 in Python64,
    # midway between representable float32 coordinates near this magnitude.
    raw = (16_777_217, -16_777_217, 0)
    expected = expected_blender_position(raw)
    assert expected == (65_536.0, -65_536.0, 0.0)
    stored_err, old_error = position_transport_error(expected, raw)
    assert stored_err == 0.0
    assert old_error == 0.00390625
    assert old_error > 1e-6  # the V16 checker rejected it incorrectly


def test_single_float32_ulp_of_actual_vertex_corruption_is_never_ignored():
    raw = (16_777_217, 4096, -256)
    correct = list(expected_blender_position(raw))
    bits = struct.unpack('<I', struct.pack('<f', correct[0]))[0]
    altered = list(correct)
    altered[0] = struct.unpack('<f', struct.pack('<I', bits + 1))[0]
    assert altered[0] - correct[0] == 0.0078125
    assert position_transport_error(tuple(altered), raw)[0] == 0.0078125
    assert position_transport_error(tuple(correct), raw)[0] == 0.0


def test_large_negative_and_fractional_lights_use_same_exact_boundary():
    for raw in ((0, 0, 0), (-20_000_013, 1025, 33), (2**31-1, -2**31, 8192)):
        expected = expected_blender_position(raw)
        assert position_transport_error(expected, raw)[0] == 0.0
        changed = (expected[0], expected[1], expected[2] + 0.5)
        assert position_transport_error(changed, raw)[0] > 0.0


def test_nonfinite_out_of_bounds_and_wrong_dimensions_fail_closed():
    for x in (math.nan, math.inf, -math.inf, 1e100):
        with pytest.raises(ValueError):
            binary32_position(x)
    with pytest.raises(ValueError):
        expected_blender_position((1, 2))
    with pytest.raises(ValueError):
        position_transport_error((0, 0), (0, 0, 0))


def test_blender_checker_uses_exact_binary32_for_vertices_and_lights():
    source = (ROOT/'pt_asset_tool/blender/check_stage072_transport.py').read_text()
    assert 'from pt_asset_tool.stage072_position_float32 import position_transport_error' in source
    assert source.count('position_transport_error(') == 2
    assert 'if err != 0.0 and len(errors) < 20:' in source
    assert 'if light_err != 0.0 and len(errors) < 20:' in source
    assert 'EXACT_BINARY32_AFTER_FIXEDPOINT_DIV256' in source
    assert 'vertex {i} binary32 position mismatch' in source
    assert 'light {i} binary32 position mismatch' in source
    assert 'max_position_python64_intermediate_delta' in source
    assert 'max_light_position_abs_error' in source
    # Importer remains unchanged: this patch applies only to the checker.
    importer=(ROOT/'pt_asset_tool/blender/import_stage072.py').read_text()
    assert 'mesh.from_pydata(verts, [], faces)' in importer
    assert 'v["x"] / 256.0' in importer


def test_source_fixture_ricarten_positions_exact_after_blender_f32(tmp_path):
    # Use the original Ricarten file if bundled as a QA fixture; no need to
    # assume access to the operator's Etervale checkout in our test process.
    sample=Path('/mnt/data/stage_v12/sample/village-2.smd')
    if not sample.exists():
        pytest.skip('physical Ricarten QA sample not bundled')
    from pt_asset_tool.stage072_corpus import parse_stage072
    parsed=parse_stage072(sample, include_payload=True)
    assert parsed['full_parse']=='PASS'
    verts=parsed['payload']['vertices']
    assert len(verts)==41783
    for vert in verts:
        raw=tuple(vert[key] for key in ('x','y','z'))
        got=tuple(binary32_position(r/256.0) for r in raw)
        assert position_transport_error(got, raw)[0] == 0.0
