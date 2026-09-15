from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
sys.path.insert(0, str(PAYLOAD))

from pt_asset_tool import rare_rigid_cross_object_live_writer_candidate as c
from pt_asset_tool.rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_release_scope_and_limits():
    assert c.RELEASE_VERSION == '0.8.26'
    assert c.CANDIDATE_MAX_CHANGED == 8
    assert c.CANDIDATE_MIN_OBJECTS == 2
    assert c.CANDIDATE_MAX_OBJECTS == 3
    assert c.CANDIDATE_VERTICES_PER_OBJECT == 2
    assert 'CROSS_OBJECT_LIVE_WRITER_CANDIDATE' in c.FORMAT
    assert 'CANDIDATE' in c.CANDIDATE_TEST


def test_prior_v0825_gate_accepts_strict_pass(tmp_path):
    p = tmp_path / c.PRIOR_REPORT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        'format': 'PT_RARE_RIGID_CROSS_OBJECT_SAVED_BLENDER_CANDIDATE_AUDIT_V3',
        'status': 'PASS',
        'release_version': '0.8.25',
        'prior_v0822_gate_pass': True,
        'representatives_match_v0822': True,
        'candidate_object_counts': [2, 3],
        'candidate_max_total_changed_vertices': 8,
        'rows': [
            {'status': 'PASS', 'matches_v0822_output_sha256': True},
            {'status': 'PASS', 'matches_v0822_output_sha256': True},
        ],
        'production_cross_object_still_blocked': True,
        'production_cross_object_output_created': False,
        'negative_saved_blender_partial_failure_blocked': True,
        'negative_output_created': False,
        'candidate_certification_written': False,
        'real_certification_registry_modified': False,
        'production_policy_modified': False,
        'writer_modules_modified': False,
        'client_modified': False,
        'production_single_object_max_vertices': 8,
        'cross_object_live_write_authorized': False,
    }), encoding='utf-8')
    assert c._prior_gate(tmp_path)['status'] == 'PASS'


def _extract_rows(per_object=2, objects=(0, 5)):
    changed=[]
    for oi in objects:
        for j in range(per_object):
            vi=10*oi+j
            changed.append({
                'object_index': oi,
                'vertex_index': vi,
                'before_world_fixed': [vi, 1, 2],
                'after_world_fixed': [vi+1, 1, 2],
            })
    return {'changed_vertices': changed}


def test_transaction_from_extraction_rebuilds_two_objects(monkeypatch):
    def fake_plan(prepared, skeleton, changes):
        oi=int(changes[0]['object_index'])
        return {
            'object_index': oi,
            'changed_vertex_count': len(changes),
            'changed_vertex_indices': [int(x['vertex_index']) for x in changes],
            'changed_vertices': [
                {'vertex_index': int(x['vertex_index']), 'before_world_fixed': list(x['before_world_fixed'])}
                for x in changes
            ],
        }
    monkeypatch.setattr(c.mv, 'plan_requested_at_dragon_transaction', fake_plan)
    tx=c._transaction_from_extraction(pathlib.Path('a'), pathlib.Path('b'), _extract_rows())
    assert tx['object_count'] == 2
    assert tx['total_changed_vertices'] == 4
    assert tx['object_indices'] == [0, 5]


def test_transaction_rejects_wrong_vertices_per_object_before_planning(monkeypatch):
    monkeypatch.setattr(c.mv, 'plan_requested_at_dragon_transaction', lambda *a, **k: (_ for _ in ()).throw(AssertionError('should not plan')))
    try:
        c._transaction_from_extraction(pathlib.Path('a'), pathlib.Path('b'), _extract_rows(per_object=1))
    except RuntimeError as exc:
        assert 'EXACTLY_TWO_VERTICES_PER_OBJECT' in str(exc)
    else:
        raise AssertionError('expected fail-closed')


def test_transaction_rejects_four_objects_before_planning(monkeypatch):
    monkeypatch.setattr(c.mv, 'plan_requested_at_dragon_transaction', lambda *a, **k: (_ for _ in ()).throw(AssertionError('should not plan')))
    try:
        c._transaction_from_extraction(pathlib.Path('a'), pathlib.Path('b'), _extract_rows(objects=(0,1,5,8)))
    except RuntimeError as exc:
        assert 'OBJECT_COUNT_OUTSIDE_2_3' in str(exc)
    else:
        raise AssertionError('expected fail-closed')


def test_transaction_rejects_nine_total_before_planning(monkeypatch):
    changed=[]
    for oi in (0,1,5):
        for j in range(3):
            changed.append({'object_index':oi,'vertex_index':oi*10+j,'before_world_fixed':[0,0,0],'after_world_fixed':[1,0,0]})
    monkeypatch.setattr(c.mv, 'plan_requested_at_dragon_transaction', lambda *a, **k: (_ for _ in ()).throw(AssertionError('should not plan')))
    try:
        c._transaction_from_extraction(pathlib.Path('a'), pathlib.Path('b'), {'changed_vertices':changed})
    except RuntimeError as exc:
        assert 'OUTSIDE_1_8:9' in str(exc)
    else:
        raise AssertionError('expected fail-closed')


def test_certified_writers_still_byte_identical():
    for rel, expected in EXPECTED_WRITER_HASHES.items():
        assert sha(PAYLOAD / rel) == expected, rel


def test_wrapper_routes_v0826_command():
    text=(PAYLOAD/'pt_asset.py').read_text(encoding='utf-8')
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'rare-rigid-cross-object-live-writer-candidate-workflow' in text
    assert 'rare_rigid_cross_object_live_writer_candidate' in text


def test_live_writer_rechecks_binding_and_uses_candidate_extractor():
    text=(PAYLOAD/'pt_asset_tool/rare_rigid_cross_object_live_writer_candidate.py').read_text(encoding='utf-8')
    assert 'audit_rare_rigid_binding' in text
    assert '_at_dragon_binding(binding)' in text
    assert '_extract_candidate(' in text
    assert 'expected' not in text[text.index('def write_at_dragon_cross_object_candidate_workspace'):text.index('def _install_transaction_into_workspace')]


def test_candidate_scope_never_changes_production_policy():
    text=(PAYLOAD/'pt_asset_tool/rare_rigid_cross_object_live_writer_candidate.py').read_text(encoding='utf-8')
    assert 'cross_object_live_write_authorized\': False' in text
    assert 'production_policy_modified\': False' in text
    assert 'manual_artist_proof_required_before_cross_object_authorization' in text
