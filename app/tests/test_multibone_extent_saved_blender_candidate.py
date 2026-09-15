from __future__ import annotations
import json, pathlib
import pytest
from pt_asset_tool import rare_rigid_multibone_extent_saved_blender_candidate as m


def _prior():
    rows=[]
    for i,k in enumerate(m.TARGET_KINDS):
        rows.append({'status':'PASS','target_bound_kind':k,'object_index':i,'vertex_index':10+i,'all_non_authorized_bytes_byte_identical':True,'bound_window_non_field_bytes_byte_identical':True,'witness_check':'PASS','output_sha256':str(i+1)*64})
    return {'format':'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_PROBE_AUDIT_V1','status':'PASS','release_version':'0.8.31','logical':m.TARGET,'probe_witness_count':5,'discovered_target_kinds':list(m.TARGET_KINDS),'rows':rows,'production_extent_still_blocked':True,'multibone_outward_extent_write_authorized':False,'extent_contraction_write_authorized':False,'topology_write_authorized':False,'real_certification_registry_modified':False,'cross_object_production_policy_modified':False,'writer_modules_modified':False,'client_modified':False,'writer_hashes':m.EXPECTED_WRITER_HASHES}


def test_strict_prior_accepts_exact_pass(tmp_path):
    p=tmp_path/m.PRIOR_REL; p.parent.mkdir(parents=True); p.write_text(json.dumps(_prior()))
    d=m._strict_prior_v0831(tmp_path)
    assert set(d['_rows_by_kind'])==set(m.TARGET_KINDS)


def test_strict_prior_rejects_missing_kind(tmp_path):
    d=_prior(); d['rows']=d['rows'][:-1]
    p=tmp_path/m.PRIOR_REL; p.parent.mkdir(parents=True); p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError, match='NOT_STRICT_PASS'):
        m._strict_prior_v0831(tmp_path)


def test_strict_prior_rejects_authorized_extent(tmp_path):
    d=_prior(); d['multibone_outward_extent_write_authorized']=True
    p=tmp_path/m.PRIOR_REL; p.parent.mkdir(parents=True); p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError, match='NOT_STRICT_PASS'):
        m._strict_prior_v0831(tmp_path)


def test_saved_blender_candidate_release_contract():
    assert m.RELEASE_VERSION=='0.8.32'
    assert m.FORMAT.endswith('AUDIT_V1')
    assert m.TARGET_KINDS==('maxX','maxZ','maxY','dBound','Bound')


def test_production_negative_requires_extent_guard_and_zero_output(tmp_path, monkeypatch):
    workspace=tmp_path/'ws'; workspace.mkdir(); mp=workspace/'workspace_manifest.json'; mp.write_text(json.dumps({'edit_blend':'old.blend'}))
    out=tmp_path/'out.smd'
    def fake(*args, **kwargs):
        raise ValueError('EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED')
    monkeypatch.setattr(m,'write_at_dragon_edit_workspace',fake)
    blocked, err=m._production_extent_negative(reg=None,resolver=None,certifications=None,settings=None,root=tmp_path,workspace=workspace,edit_blend=tmp_path/'x.blend',output=out)
    assert blocked and 'EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED' in err and not out.exists()
    assert json.loads(mp.read_text())['edit_blend']=='old.blend'
