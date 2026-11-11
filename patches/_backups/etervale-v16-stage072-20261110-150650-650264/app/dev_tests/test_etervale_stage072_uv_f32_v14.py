"""V14: strict binary32 UV transport, physical source unchanged, residual triage."""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from pt_asset_tool.stage072_uv_float32 import binary32, expected_blender_uv, uv_transport_error

ROOT=Path(__file__).resolve().parents[1]


def test_uv_binary32_quantization_replaces_false_positive_not_tolerance():
    # UV tiling coordinates are float32. The intermediate 1 - V in Python's
    # float64 can differ from the Blender Float2 value by one binary32 ULP.
    uv=(binary32(205.125), binary32(-1023.99994))
    expected=expected_blender_uv(*uv)
    stored_err, naive_err=uv_transport_error(expected, *uv)
    assert stored_err == 0.0
    assert naive_err >= 1e-5, naive_err


def test_uv_binary32_rejects_a_single_bit_step_in_a_real_transport_value():
    uv=(binary32(-3.75),binary32(72.2381))
    expected=expected_blender_uv(*uv)
    # nextafter above is float64; next representable *binary32* value follows.
    bits=struct.unpack('<I',struct.pack('<f',expected[1]))[0]
    # Expected V is negative in this case, so decreasing the bits increases it.
    alternate=struct.unpack('<f',struct.pack('<I',bits-1))[0]
    assert alternate != expected[1]
    error, _ = uv_transport_error((expected[0],alternate),*uv)
    assert error > 0.0


def test_uv_rejects_nan_inf_and_out_of_range():
    for value in (math.nan,math.inf,-math.inf,1e100):
        with pytest.raises(ValueError):
            binary32(value)


def test_checker_applies_exact_f32_policy_and_exposes_python64_diagnostic():
    checker=(ROOT/'pt_asset_tool/blender/check_stage072_transport.py').read_text()
    assert 'from pt_asset_tool.stage072_uv_float32 import uv_transport_error' in checker
    assert 'if err != 0.0' in checker
    assert 'EXACT_BINARY32_AFTER_V_FLIP' in checker
    assert 'max_uv_python64_intermediate_delta' in checker
    assert 'corner {corner} UV mismatch' not in checker


def test_original_stage072_fidelity_not_modified_by_v14():
    root=ROOT/'pt_asset_tool'
    parser=(root/'stage072_corpus.py').read_bytes()
    importer=(root/'blender/import_stage072.py').read_bytes()
    existing=Path('/mnt/data/stage_v12/project/app/pt_asset_tool')
    if existing.is_dir():
        assert parser==(existing/'stage072_corpus.py').read_bytes()
        assert importer==(existing/'blender/import_stage072.py').read_bytes()
    validator=(root/'validation.py').read_text()
    assert "failure_details" in validator
    assert "Stage0.72 texture preparation hard-failed for existing client files:" in validator
    assert 'raise RuntimeError' in validator


def test_triage_reads_one_exact_texture_failure_and_source_parser_without_writes(tmp_path, monkeypatch):
    import importlib.util
    script=ROOT/'pt_stage072_v14_residual_triage.py'
    spec=importlib.util.spec_from_file_location('v14_stage_triage',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app=tmp_path/'project/app'; app.mkdir(parents=True)
    client=tmp_path/'assets'; client.mkdir()
    import hashlib
    digest=hashlib.sha256(module.PILAI.encode('utf-8')).hexdigest()[:16].upper()
    overlay_dir=app/'pt_build/etervale/stage072_all_maps/preview_work'/f'STG-BATCH-{digest}'/'stage072_preview'
    overlay_dir.mkdir(parents=True)
    (overlay_dir/'texture_overlay_report.json').write_text(json.dumps({'entries':[
        {'logical':'field/forever-fall/','status':'MISSING','affects_ready':True},
        {'logical':'field/forever-fall/tex.tga','status':'TGA_DECODE_FAIL',
         'physical':'/fake/path','affects_ready':True,'log':'fake.log'},
        {'logical':'field/forever-fall/good.tga','status':'TGA_READY','affects_ready':True},
    ]}))
    monkeypatch.setattr(module,'_read_dark',lambda root: {'status':'TEST_NONPASS'})
    result=module.run(app,client)
    assert result['pilai']['hard_failure_count']==1
    assert result['pilai']['hard_failures'][0]['status']=='TGA_DECODE_FAIL'
    assert result['pilai']['missing_or_invalid_count']==1
    assert result['client_modified'] is False
    assert result['dark_boss']['status']=='TEST_NONPASS'
    with pytest.raises(ValueError):
        module.run(app,client,client/'triage.json')
