from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
sys.path.insert(0, str(PAYLOAD))

from pt_asset_tool import rare_rigid_multibone_extent_live_writer_candidate as m


def _prior():
    rows = []
    field_shapes = {
        'maxX': ['maxX'],
        'maxZ': ['maxZ'],
        'maxY': ['maxY'],
        'dBound': ['dBound'],
        'Bound': ['maxY', 'dBound', 'Bound'],
    }
    for i, kind in enumerate(m.TARGET_KINDS):
        rows.append({
            'status': 'PASS',
            'target_bound_kind': kind,
            'object_index': i,
            'vertex_index': 10 + i,
            'affected_bone_count': 2,
            'affected_bones': ['a', 'b'],
            'saved_blender_apply_pass': True,
            'saved_blender_saved_mode': 'EDIT_MESH',
            'saved_blender_input_mode_before': 'EDIT_MESH',
            'saved_blender_input_mode_after': 'OBJECT',
            'writer_input_object_mode_canonicalized': True,
            'non_position_semantic_state_pass': True,
            'max_uv_state_delta': 0.0,
            'max_physique_weight_delta': 0.0,
            'changed_bound_fields': field_shapes[kind],
            'all_non_authorized_bytes_byte_identical': True,
            'bound_window_non_field_bytes_byte_identical': True,
            'witness_check': 'PASS',
            'atomic_candidate_publish': True,
            'candidate_only': True,
            'certification_written': False,
            'output_sha256': str(i + 1) * 64,
            'matches_v0831_output_sha256': True,
        })
    return {
        'format': 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_SAVED_BLENDER_CANDIDATE_AUDIT_V1',
        'status': 'PASS',
        'release_version': '0.8.32',
        'logical': m.TARGET,
        'prior_v0831_strict_pass': True,
        'prior_v0831_witness_count': 5,
        'candidate_target_kinds': list(m.TARGET_KINDS),
        'candidate_witness_count': 5,
        'all_candidate_rows_pass': True,
        'rows': rows,
        'all_saved_blender_outputs_match_v0831': True,
        'production_extent_still_blocked': True,
        'production_extent_output_created': False,
        'candidate_certification_written': False,
        'real_certification_registry_modified': False,
        'single_object_production_policy_modified': False,
        'cross_object_production_policy_modified': False,
        'writer_modules_modified': False,
        'client_modified': False,
        'multibone_outward_extent_live_write_authorized': False,
        'extent_contraction_write_authorized': False,
        'topology_write_authorized': False,
        'writer_hashes': m.EXPECTED_WRITER_HASHES,
    }


def test_release_contract_and_scope():
    assert m.RELEASE_VERSION == '0.8.33'
    assert m.FORMAT.endswith('AUDIT_V1')
    assert m.WRITE_FORMAT.endswith('WRITE_V1')
    assert m.CANDIDATE_TEST.endswith('OUTWARD_EXTENT_WRITE_CANDIDATE')
    assert m.TARGET_KINDS == ('maxX', 'maxZ', 'maxY', 'dBound', 'Bound')


def test_strict_prior_accepts_exact_v0832_pass(tmp_path):
    p = tmp_path / m.PRIOR_REL
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_prior()))
    d = m._strict_prior_v0832(tmp_path)
    assert set(d['_rows_by_kind']) == set(m.TARGET_KINDS)


def test_strict_prior_rejects_authorized_extent(tmp_path):
    d = _prior()
    d['multibone_outward_extent_live_write_authorized'] = True
    p = tmp_path / m.PRIOR_REL
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError, match='NOT_STRICT_PASS'):
        m._strict_prior_v0832(tmp_path)


def test_exact_bound_field_shape_classifier():
    assert m._classify_target_kind(['maxX']) == 'maxX'
    assert m._classify_target_kind(['maxZ']) == 'maxZ'
    assert m._classify_target_kind(['maxY']) == 'maxY'
    assert m._classify_target_kind(['dBound']) == 'dBound'
    assert m._classify_target_kind(['maxY', 'dBound', 'Bound']) == 'Bound'


def test_classifier_rejects_no_expansion_and_unproven_shape():
    with pytest.raises(RuntimeError, match='REQUIRES_OUTWARD_BOUND_EXPANSION'):
        m._classify_target_kind([])
    with pytest.raises(RuntimeError, match='BOUND_FIELD_SHAPE_NOT_PROVEN'):
        m._classify_target_kind(['maxX', 'dBound'])


def test_wrapper_routes_v0833_live_candidate():
    text = (PAYLOAD / 'pt_asset.py').read_text(encoding='utf-8')
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'rare-rigid-multibone-outward-extent-live-writer-candidate-workflow' in text
    assert 'rare_rigid_multibone_extent_live_writer_candidate' in text
    assert 'rare_rigid_multibone_outward_extent_live_writer_candidate_workflow_v0833.json' in text


def test_candidate_writer_contains_immediate_binding_and_atomic_cleanup():
    text = (PAYLOAD / 'pt_asset_tool/rare_rigid_multibone_extent_live_writer_candidate.py').read_text(encoding='utf-8')
    assert 'audit_rare_rigid_binding(' in text
    assert '_at_dragon_binding(binding)' in text
    assert "staging.unlink(missing_ok=True)" in text
    assert "final_output.unlink(missing_ok=True)" in text
    assert 'certifications.add(' in text
    assert 'production_authorized' in text


def test_certified_writers_unchanged():
    import hashlib
    for rel, expected in m.EXPECTED_WRITER_HASHES.items():
        got = hashlib.sha256((PAYLOAD / rel).read_bytes()).hexdigest()
        assert got == expected, rel


def test_cross_object_negative_builds_complete_saved_blender_transaction(tmp_path, monkeypatch):
    captured = {}
    def fake_apply(**kwargs):
        captured.update(kwargs['transaction'])
        return {'check': 'PASS'}
    monkeypatch.setattr(m, '_apply_saved_blender', fake_apply)
    a = {'object_index': 8, 'vertex_index': 30, 'before_world_fixed': [1,2,3], 'requested_after_world_fixed': [4,2,3]}
    b = {'object_index': 9, 'vertex_index': 136, 'before_world_fixed': [5,6,7], 'requested_after_world_fixed': [5,8,7]}
    m._apply_cross_object_extent_negative(
        settings=None, root=tmp_path, pristine_blend=tmp_path/'p.blend', out_blend=tmp_path/'o.blend',
        a=a, b=b, work=tmp_path/'w',
    )
    assert captured['object_count'] == 2
    assert captured['object_indices'] == [8, 9]
    assert captured['total_changed_vertices'] == 2
    assert len(captured['per_object_plans']) == 2


def test_run_uses_strict_v0830_cross_object_policy_authorization_key():
    text = (PAYLOAD / 'pt_asset_tool/rare_rigid_multibone_extent_live_writer_candidate.py').read_text(encoding='utf-8')
    assert "cross_policy.get('cross_object_production_authorized') is not True" in text
    assert "cross_object_live_write_authorized') is not True" not in text
