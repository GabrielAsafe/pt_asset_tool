from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
sys.path.insert(0, str(PAYLOAD))

from pt_asset_tool import rare_rigid_cross_object_production as p
from pt_asset_tool import rare_rigid_cross_object_production_promotion as g
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


def test_release_scope_exact_shapes_only():
    assert p.RELEASE_VERSION == '0.8.30'
    assert p.ALLOWED_OBJECT_COUNTS == (2, 3)
    assert p.VERTICES_PER_OBJECT == 2
    assert p.MAX_TOTAL_CHANGED == 8
    assert g.RELEASE_VERSION == '0.8.30'
    assert 'PRODUCTION_PROMOTION' in g.FORMAT


def test_proxy_promotes_only_exact_2x2_or_3x2():
    backing=DummyCert(); proxy=p._CrossObjectProductionCertificationProxy(backing)
    row=proxy.add(test='RARE_RIGID_ARTIST_GUARDED_CROSS_OBJECT_TRANSACTION_WRITE_CANDIDATE', metadata={
        'object_count':2,'artist_changed_vertices':4,
        'per_object_changed_vertex_indices':{'0':[1,2],'5':[3,4]},'write_scope':'candidate'
    })
    assert row['test'] == p.PROMOTED_TEST
    assert row['metadata']['production_authorized'] is True
    assert row['metadata']['candidate_only'] is False
    for bad in [
        {'object_count':2,'artist_changed_vertices':4,'per_object_changed_vertex_indices':{'0':[1,2,3],'5':[4]}},
        {'object_count':4,'artist_changed_vertices':8,'per_object_changed_vertex_indices':{'0':[1,2],'1':[3,4],'5':[5,6],'8':[7,8]}},
    ]:
        try:
            proxy.add(test='RARE_RIGID_ARTIST_GUARDED_CROSS_OBJECT_TRANSACTION_WRITE_CANDIDATE', metadata=bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError('unsupported production certification shape passed')


def test_policy_validation_hash_bound(tmp_path):
    # Build the minimum self-consistent single-object policy expected by the retained V0.8.21 validator.
    for rel in EXPECTED_WRITER_HASHES:
        dst=tmp_path/rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(PAYLOAD/rel,dst)
    manual_single=tmp_path/'pt_build/rare_rigid_large_manual_candidate_v0819/at_dragon.smd/manual_write_result.json'
    manual_single.parent.mkdir(parents=True, exist_ok=True); manual_single.write_text('{"status":"PASS"}\n')
    single={
      'format':'PT_RARE_RIGID_LARGE_PRODUCTION_POLICY_V1','status':'PASS','production_authorized':True,
      'production_max_vertices':8,'logical':'char/tmABCD/at_dragon.smd','writer_hashes':EXPECTED_WRITER_HASHES,
      'cross_object_blocked':True,'nine_vertex_blocked':True,'bounds_negative_blocked':True,'manual_artist_proof':True,
      'manual_report_sha256':sha(manual_single),'single_object_only':True,
    }
    sp=tmp_path/'pt_build/rare_rigid_large_production_policy_v0821.json'; sp.write_text(json.dumps(single))
    manual=tmp_path/p.MANUAL_REL; manual.parent.mkdir(parents=True,exist_ok=True); manual.write_text('{"status":"PASS"}\n')
    live=tmp_path/p.LIVE_REL; live.parent.mkdir(parents=True,exist_ok=True); live.write_text('{"status":"PASS"}\n')
    cross={
      'format':p.POLICY_FORMAT,'status':'PASS','release_version':'0.8.30','cross_object_production_authorized':True,'logical':'char/tmABCD/at_dragon.smd',
      'allowed_object_counts':[2,3],'vertices_per_object':2,'max_total_changed_vertices':8,'interior_only':True,
      'extent_bounds_changes_authorized':False,'topology_authorized':False,'more_than_3_objects_authorized':False,
      'other_vertices_per_object_shapes_authorized':False,'more_than_8_total_vertices_authorized':False,
      'manual_artist_proof':True,'live_writer_candidate_proof':True,'writer_hashes':EXPECTED_WRITER_HASHES,
      'manual_report_sha256':sha(manual),'live_report_sha256':sha(live),'single_object_policy_sha256':sha(sp),
    }
    cp=tmp_path/p.POLICY_REL; cp.parent.mkdir(parents=True,exist_ok=True); cp.write_text(json.dumps(cross))
    assert p.load_and_validate_cross_policy(tmp_path)['cross_object_production_authorized'] is True
    manual.write_text('{"status":"FAIL"}\n')
    try: p.load_and_validate_cross_policy(tmp_path)
    except RuntimeError: pass
    else: raise AssertionError('tampered manual evidence accepted')


def test_negative_transport_shape_constructor():
    safe={0:[{'vertex_index':1,'before_world_fixed':[0,0,0],'requested_after_world_fixed':[1,0,0]},
             {'vertex_index':2,'before_world_fixed':[0,0,0],'requested_after_world_fixed':[1,0,0]},
             {'vertex_index':3,'before_world_fixed':[0,0,0],'requested_after_world_fixed':[1,0,0]}],
          5:[{'vertex_index':4,'before_world_fixed':[0,0,0],'requested_after_world_fixed':[1,0,0]}]}
    tx=g._transport_only_shape(safe,{0:3,5:1})
    assert tx['object_count']==2 and tx['total_changed_vertices']==4
    assert [len(x['changed_vertices']) for x in tx['per_object_plans']]==[3,1]


def test_wrapper_routes_v0830_and_production_dispatch():
    text=(PAYLOAD/'pt_asset.py').read_text(encoding='utf-8')
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'rare-rigid-cross-object-production-promotion-workflow' in text
    assert 'rare_rigid_cross_object_production_promotion' in text
    assert 'write_production_dispatch' in text


def test_certified_writers_unchanged():
    for rel, expected in EXPECTED_WRITER_HASHES.items():
        assert sha(PAYLOAD/rel)==expected, rel


def test_v0829_failure_classifier_accepts_only_physical_missing_regression_report(tmp_path):
    report = {
        'format': 'PT_RARE_RIGID_CROSS_OBJECT_PRODUCTION_PROMOTION_AUDIT_V1',
        'status': 'FAIL', 'release_version': '0.8.29',
        'logical': 'char/tmABCD/at_dragon.smd',
        'error': "FileNotFoundError:[Errno 2] No such file or directory: '/tmp/work/v0826_live_regression.json'",
        'cross_object_live_write_authorized': False,
        'production_single_object_max_vertices': 8,
    }
    path = tmp_path / g.PRIOR_FAIL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding='utf-8')
    assert g._strict_v0829_failure(tmp_path)['status'] == 'FAIL'
    report['error'] = 'RuntimeError:DIFFERENT_FAILURE'
    path.write_text(json.dumps(report), encoding='utf-8')
    try:
        g._strict_v0829_failure(tmp_path)
    except RuntimeError as exc:
        assert 'V0829_FAILURE_NOT_EXPECTED_REGRESSION_REPORT_BUG' in str(exc)
    else:
        raise AssertionError('unexpected V0.8.29 failure accepted')


def test_live_regression_report_is_atomically_persistable(tmp_path):
    out = tmp_path / 'workspace' / 'v0826_live_regression.json'
    report = {'format':'TEST','status':'PASS','candidate_object_counts':[2,3]}
    g._write_json_atomic(out, report)
    assert out.is_file()
    assert json.loads(out.read_text(encoding='utf-8')) == report
    assert not out.with_suffix(out.suffix + '.staging').exists()
    source = (PAYLOAD/'pt_asset_tool/rare_rigid_cross_object_production_promotion.py').read_text(encoding='utf-8')
    assert '_write_json_atomic(rerun_path, rerun)' in source
    assert '_sha256(rerun_path)' in source
