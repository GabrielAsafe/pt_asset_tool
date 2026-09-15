from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
sys.path.insert(0, str(PAYLOAD))

from pt_asset_tool import rare_rigid_multibone_extent_production as p
from pt_asset_tool import rare_rigid_multibone_extent_production_promotion as g
from pt_asset_tool.rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DummyCert:
    directory = pathlib.Path('.')
    path = pathlib.Path('certifications.jsonl')
    def __init__(self): self.rows=[]
    def records(self): return list(self.rows)
    def add(self, **kwargs):
        row={'test':kwargs.get('test'),'metadata':kwargs.get('metadata') or {},'notes':kwargs.get('notes',''),'certification_id':'CERT-TEST'}
        self.rows.append(row); return row


def _write_base_policies(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    for rel in EXPECTED_WRITER_HASHES:
        dst=tmp_path/rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(PAYLOAD/rel,dst)
    single_manual=tmp_path/'pt_build/rare_rigid_large_manual_candidate_v0819/at_dragon.smd/manual_write_result.json'
    single_manual.parent.mkdir(parents=True, exist_ok=True); single_manual.write_text('{"status":"PASS"}\n')
    single={
      'format':'PT_RARE_RIGID_LARGE_PRODUCTION_POLICY_V1','status':'PASS','production_authorized':True,
      'production_max_vertices':8,'logical':'char/tmABCD/at_dragon.smd','writer_hashes':EXPECTED_WRITER_HASHES,
      'cross_object_blocked':True,'nine_vertex_blocked':True,'bounds_negative_blocked':True,'manual_artist_proof':True,
      'manual_report_sha256':sha(single_manual),'single_object_only':True,
    }
    sp=tmp_path/'pt_build/rare_rigid_large_production_policy_v0821.json'; sp.write_text(json.dumps(single))

    cross_manual=tmp_path/'pt_build/rare_rigid_cross_object_manual_candidate_v0828/at_dragon.smd/manual_write_result.json'
    cross_manual.parent.mkdir(parents=True,exist_ok=True); cross_manual.write_text('{"status":"PASS"}\n')
    cross_live=tmp_path/'pt_build/rare_rigid_cross_object_live_writer_candidate_workflow_v0826.json'
    cross_live.parent.mkdir(parents=True,exist_ok=True); cross_live.write_text('{"status":"PASS"}\n')
    cross={
      'format':'PT_RARE_RIGID_CROSS_OBJECT_PRODUCTION_POLICY_V1','status':'PASS','release_version':'0.8.30',
      'cross_object_production_authorized':True,'logical':'char/tmABCD/at_dragon.smd',
      'allowed_object_counts':[2,3],'vertices_per_object':2,'max_total_changed_vertices':8,'interior_only':True,
      'extent_bounds_changes_authorized':False,'topology_authorized':False,'more_than_3_objects_authorized':False,
      'other_vertices_per_object_shapes_authorized':False,'more_than_8_total_vertices_authorized':False,
      'manual_artist_proof':True,'live_writer_candidate_proof':True,'writer_hashes':EXPECTED_WRITER_HASHES,
      'manual_report_sha256':sha(cross_manual),'live_report_sha256':sha(cross_live),'single_object_policy_sha256':sha(sp),
    }
    cp=tmp_path/'pt_build/rare_rigid_cross_object_production_policy_v0830.json'; cp.write_text(json.dumps(cross))
    return sp, cp


def test_release_scope_exact_one_vertex_field_shapes_only():
    assert p.RELEASE_VERSION == '0.8.36'
    assert g.RELEASE_VERSION == '0.8.36'
    assert p.ALLOWED_TARGET_KINDS == ('maxX','maxZ','maxY','dBound','Bound')
    assert p.ALLOWED_FIELD_SHAPES['Bound'] == frozenset({'maxY','dBound','Bound'})
    assert 'PRODUCTION_PROMOTION' in g.FORMAT
    assert g.EXPECTED_MANUAL_SHA256 == '00ac502551c9f5eca95a294605a478d76f3d026a2afaf176813269b35c712297'


def test_proxy_promotes_only_exact_proven_shape():
    backing=DummyCert(); proxy=p._MultiboneExtentProductionCertificationProxy(backing)
    row=proxy.add(
        test='RARE_RIGID_ARTIST_GUARDED_MULTIBONE_OUTWARD_EXTENT_WRITE_CANDIDATE',
        metadata={
            'target_bound_kind':'Bound','changed_bound_fields':['maxY','dBound','Bound'],
            'affected_bone_count':2,'all_non_authorized_bytes_byte_identical':True,
            'bound_window_non_field_bytes_byte_identical':True,'atomic_output_replace':True,'write_scope':'candidate',
        },
    )
    assert row['test'] == p.PROMOTED_TEST
    assert row['metadata']['production_authorized'] is True
    assert row['metadata']['candidate_only'] is False
    for bad in [
        {'target_bound_kind':'Bound','changed_bound_fields':['Bound'],'affected_bone_count':2},
        {'target_bound_kind':'maxX','changed_bound_fields':['maxX'],'affected_bone_count':1},
        {'target_bound_kind':'unknown','changed_bound_fields':['maxX'],'affected_bone_count':2},
    ]:
        bad.update({'all_non_authorized_bytes_byte_identical':True,'bound_window_non_field_bytes_byte_identical':True,'atomic_output_replace':True})
        with pytest.raises(RuntimeError):
            proxy.add(test='RARE_RIGID_ARTIST_GUARDED_MULTIBONE_OUTWARD_EXTENT_WRITE_CANDIDATE', metadata=bad)


def test_extent_policy_validation_is_hash_bound(tmp_path):
    sp, cp = _write_base_policies(tmp_path)
    manual=tmp_path/p.MANUAL_REL; manual.parent.mkdir(parents=True,exist_ok=True); manual.write_text('{"status":"PASS"}\n')
    live=tmp_path/p.LIVE_REL; live.parent.mkdir(parents=True,exist_ok=True); live.write_text('{"status":"PASS"}\n')
    saved=tmp_path/p.SAVED_REL; saved.parent.mkdir(parents=True,exist_ok=True); saved.write_text('{"status":"PASS"}\n')
    policy={
        'format':p.POLICY_FORMAT,'status':'PASS','release_version':'0.8.36','logical':'char/tmABCD/at_dragon.smd',
        'multibone_outward_extent_production_authorized':True,'one_object_only':True,'exactly_one_changed_vertex':True,
        'allowed_target_kinds':list(p.ALLOWED_TARGET_KINDS),
        'allowed_bound_field_shapes':{k:sorted(v) for k,v in p.ALLOWED_FIELD_SHAPES.items()},
        'monotonic_expansion_only':True,'multibone_affected_normals_required':True,
        'extent_contraction_authorized':False,'multi_vertex_extent_authorized':False,'cross_object_extent_authorized':False,
        'topology_authorized':False,'manual_artist_proof':True,'live_writer_candidate_proof':True,'saved_blender_candidate_proof':True,
        'writer_hashes':EXPECTED_WRITER_HASHES,'manual_report_sha256':sha(manual),'live_report_sha256':sha(live),
        'saved_report_sha256':sha(saved),'single_object_policy_sha256':sha(sp),'cross_object_policy_sha256':sha(cp),
    }
    pp=tmp_path/p.POLICY_REL; pp.parent.mkdir(parents=True,exist_ok=True); pp.write_text(json.dumps(policy))
    assert p.load_and_validate_extent_policy(tmp_path)['multibone_outward_extent_production_authorized'] is True
    saved.write_text('{"status":"FAIL"}\n')
    with pytest.raises(RuntimeError):
        p.load_and_validate_extent_policy(tmp_path)


def test_dispatch_only_falls_through_on_exact_extent_rejection(monkeypatch, tmp_path):
    monkeypatch.setattr(p, 'load_and_validate_extent_policy', lambda root: {'status':'PASS'})
    monkeypatch.setattr(p, 'write_extent_promoted', lambda root, logical, output=None: {'status':'PASS','route':'extent'})
    monkeypatch.setattr(p, 'write_pre_extent_dispatch', lambda root, logical, output=None: {'status':'PASS','route':'old'})
    assert p.write_production_dispatch(tmp_path,'at_dragon.smd')['route']=='old'

    def extent_fail(root, logical, output=None):
        raise ValueError('EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED')
    monkeypatch.setattr(p, 'write_pre_extent_dispatch', extent_fail)
    assert p.write_production_dispatch(tmp_path,'at_dragon.smd')['route']=='extent'

    def other_fail(root, logical, output=None):
        raise RuntimeError('TOPOLOGY_CHANGE_DEFERRED')
    monkeypatch.setattr(p, 'write_pre_extent_dispatch', other_fail)
    with pytest.raises(RuntimeError, match='TOPOLOGY_CHANGE_DEFERRED'):
        p.write_production_dispatch(tmp_path,'at_dragon.smd')


def test_wrapper_routes_v0836_promotion_and_extent_dispatch():
    text=(PAYLOAD/'pt_asset.py').read_text(encoding='utf-8')
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'rare-rigid-multibone-outward-extent-production-promotion-workflow' in text
    assert 'rare_rigid_multibone_extent_production_promotion' in text
    assert 'EXTENT_POLICY_REL' in text and 'write_extent_dispatch' in text
    assert 'extent_authorized=' in text


def test_promotion_source_starts_deauthorized_and_hash_binds_regression():
    text=(PAYLOAD/'pt_asset_tool/rare_rigid_multibone_extent_production_promotion.py').read_text(encoding='utf-8')
    assert 'policy_path.unlink(missing_ok=True)' in text
    assert "rerun_path = work / 'v0833_live_regression.json'" in text
    assert '_write_json_atomic(rerun_path, rerun)' in text
    assert "'live_regression_report_sha256': _sha256(rerun_path)" in text
    assert 'manual_v0835_reproduced_promoted_core.smd' in text
    assert 'validated_policy = load_and_validate_extent_policy(root)' in text
    assert 'policy_path.unlink(missing_ok=True)' in text


def test_certified_writers_unchanged():
    for rel, expected in EXPECTED_WRITER_HASHES.items():
        assert sha(PAYLOAD/rel)==expected, rel
