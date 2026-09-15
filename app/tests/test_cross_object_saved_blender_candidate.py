from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
sys.path.insert(0, str(PAYLOAD))

from pt_asset_tool import rare_rigid_cross_object_saved_blender_candidate as s
from pt_asset_tool.rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _discovery():
    return {
        'representatives': {
            'objects_2': {
                'object_indices': [0, 5],
                'per_object_plans': [
                    {'object_index': 0, 'changed_vertex_indices': [33, 155]},
                    {'object_index': 5, 'changed_vertex_indices': [6, 7]},
                ],
            },
            'objects_3': {
                'object_indices': [0, 5, 1],
                'per_object_plans': [
                    {'object_index': 0, 'changed_vertex_indices': [33, 155]},
                    {'object_index': 5, 'changed_vertex_indices': [6, 7]},
                    {'object_index': 1, 'changed_vertex_indices': [23, 36]},
                ],
            },
        }
    }


def _prior():
    return {
        'rows': [
            {
                'object_count': 2,
                'object_indices': [0, 5],
                'per_object_changed_vertex_indices': {'0': [33, 155], '5': [6, 7]},
                'output_sha256': 'a',
            },
            {
                'object_count': 3,
                'object_indices': [0, 5, 1],
                'per_object_changed_vertex_indices': {'0': [33, 155], '5': [6, 7], '1': [23, 36]},
                'output_sha256': 'b',
            },
        ]
    }


def test_release_scope():
    assert s.RELEASE_VERSION == '0.8.25'
    assert s.CANDIDATE_MAX_CHANGED == 8
    assert 'SAVED_BLENDER' in s.FORMAT


def test_representatives_match_prior_accepts_physical_shape():
    s._assert_representatives_match_prior(_discovery(), _prior())


def test_representatives_match_prior_rejects_drift():
    d = _discovery()
    d['representatives']['objects_2']['per_object_plans'][1]['changed_vertex_indices'] = [6, 8]
    try:
        s._assert_representatives_match_prior(d, _prior())
    except RuntimeError as exc:
        assert 'REPRESENTATIVE_VERTICES_DRIFT_2' in str(exc)
    else:
        raise AssertionError('expected fail-closed on representative drift')


def test_certified_writers_remain_byte_identical():
    for rel, expected in EXPECTED_WRITER_HASHES.items():
        assert sha(PAYLOAD / rel) == expected, rel


def test_candidate_blender_helpers_present():
    assert (PAYLOAD / 'pt_asset_tool/blender/apply_rare_rigid_cross_object_transaction.py').is_file()
    assert (PAYLOAD / 'pt_asset_tool/blender/extract_rare_rigid_cross_object_candidate.py').is_file()


def test_extractor_bootstraps_project_root_before_package_import():
    text = (PAYLOAD / 'pt_asset_tool/blender/extract_rare_rigid_cross_object_candidate.py').read_text(encoding='utf-8')
    bootstrap = "ROOT = pathlib.Path(__file__).resolve().parents[2]"
    insertion = "sys.path.insert(0, str(ROOT))"
    import_line = "from pt_asset_tool.blender import extract_rare_rigid_edit as base"
    assert bootstrap in text
    assert insertion in text
    # Import is deliberately inside main, after args/report are available, so a failure can be reported.
    assert text.index(insertion) < text.index(import_line)
    assert "fatal_stage" in text and "traceback_tail" in text


def test_prior_v0824_failure_gate_accepts_exact_physical_failure(tmp_path):
    p = tmp_path / s.PRIOR_FAILED_REPORT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(__import__('json').dumps({
        'format': 'PT_RARE_RIGID_CROSS_OBJECT_SAVED_BLENDER_CANDIDATE_AUDIT_V2',
        'status': 'FAIL',
        'release_version': '0.8.24',
        'error': 'RuntimeError:command failed: fixed quantization mismatch object=5 vertex=6: [268436160, 86, 7031]!=[268436149, 86, 7031]',
        'production_single_object_max_vertices': 8,
        'cross_object_live_write_authorized': False,
    }), encoding='utf-8')
    r = s._prior_v0824_failure(tmp_path)
    assert r['status'] == 'FAIL'


def test_float32_exact_out_of_bounds_helper_avoids_huge_transport_quantization(tmp_path, monkeypatch):
    # Test the float32 fixed-point property directly; physical bounds parsing is
    # exercised on Fedora, while this regression prevents a return to +2^28.
    for q in (8192, 65536, 1048576, -1048576):
        assert s._float32_fixed_roundtrip(q) == q
    huge = 268436149
    assert s._float32_fixed_roundtrip(huge) != huge


def test_negative_no_longer_uses_2pow28_literal():
    text = (PAYLOAD / 'pt_asset_tool/rare_rigid_cross_object_saved_blender_candidate.py').read_text(encoding='utf-8')
    assert '(1 << 28)' not in text
    assert '_exact_out_of_bounds_x' in text
    assert 'float32' in text
