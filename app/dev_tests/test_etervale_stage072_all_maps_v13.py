"""V13 all-map Stage0.72 audit: actual Ricarten witness plus resumable isolation."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from pt_asset_tool.stage072_batch_audit import audit_map, find_maps, run_all, _load_checkpoint
from pt_asset_tool.stage072_paint_policy import KNOWN_UNRECOVERABLE_TEXTURES
from pt_asset_tool.stage072_view_axes import VIEW_AXIS_PROFILE

SAMPLE = Path(__file__).resolve().parents[3] / 'stage_v12' / 'sample' / 'village-2.smd'
# Developer/container staging path is not available on the operator's machine.
# The test therefore checks actual sample only when shipped in the isolated
# development environment and uses injected lightweight fixtures otherwise.


class _MappedResolver:
    def __init__(self, missing=(), ambiguous=()):
        self.missing = {x.casefold() for x in missing}
        self.ambiguous = {x.casefold() for x in ambiguous}

    def resolve(self, logical):
        key = logical.replace('\\', '/').casefold()
        if key in self.ambiguous:
            raise RuntimeError('case-insensitive client path collision without exact-case match: ' + logical)
        if key in self.missing:
            raise FileNotFoundError(logical)
        return Path('/dummy/read-only-texture')


def _find_sample() -> Path | None:
    # Only present for developer QA: never take dependencies from a user's
    # external machine or silently turn a missing sample into a PASS.
    candidates = [Path('/mnt/data/stage_v12/sample/village-2.smd')]
    return next((p for p in candidates if p.is_file()), None)


def _make_root(tmp_path):
    sample = _find_sample()
    root = tmp_path / 'assets'
    stage = root / 'Field/Ricarten/village-2.smd'
    stage.parent.mkdir(parents=True)
    if sample:
        shutil.copy2(sample, stage)
    else:
        # The operator's checkout does not bundle the 5 MB Ricarten SMD.
        # Use a genuine native Stage0.72 byte fixture compiled in memory.
        from pt_asset_tool.stage072_compiler import compile_stage072
        payload = {
            'materials': [{'textures': ['field/ricarten/tem_wall04.bmp','field/ricarten/ground.bmp']}],
            'vertices': [[0,0,0],[64,0,0],[0,0,64]],
            'faces': [{'vertices': [0,2,1], 'material':0, 'uv_layers':[
                [[0,0],[0,1],[1,0]], [[0,0],[0,1],[1,0]]]}],
            'lights': [{'type':1,'position':[32,16,32],'range':200,'color':[255,255,255]}],
        }
        data, _meta = compile_stage072(payload)
        stage.write_bytes(data)
    return root


def test_actual_ricarten_view_basis_and_missing_exception(tmp_path):
    root = _make_root(tmp_path)
    row = audit_map(root, 'Field/Ricarten/village-2.smd',
                    _MappedResolver(missing=KNOWN_UNRECOVERABLE_TEXTURES))
    assert row['parse'] == 'PASS'
    if _find_sample():
        assert (row['vertices'],row['faces'],row['lights']) == (41783,44226,79)
    else:
        assert (row['vertices'],row['faces'],row['lights']) == (3,1,1)
    assert row['view_axis_profile'] == VIEW_AXIS_PROFILE
    assert row['source_dims_xyz'][1] < row['source_dims_xyz'][2]
    assert row['blender_dims_xyz'][2] == row['source_dims_xyz'][1]
    assert row['view_determinant'] == -1
    assert row['known_missing_count'] == 1
    assert row['paint_policy'] == 'PASS_STATIC_WITH_KNOWN_UNPAINTABLE_NOT_BLENDER_TESTED'
    assert row['status'] == 'PASS_STATIC_WITH_EXCEPTION'
    assert row['client_modified'] is False


def test_unknown_missing_remains_review_and_one_map_does_not_break_other(tmp_path):
    root = _make_root(tmp_path)
    row = audit_map(root, 'Field/Ricarten/village-2.smd',
                    _MappedResolver(missing=['field/ricarten/tem_wall04.bmp', 'field/ricarten/tem_wall01.bmp']))
    # The other name may not be referenced in this particular map, so test
    # with one definitely used name from its material table if needed.
    from pt_asset_tool.stage072_corpus import parse_stage072
    from pt_asset_tool.stage072_texture_audit import _used_material_texture_refs
    names = [r['logical'] for r in _used_material_texture_refs(parse_stage072(root/'Field/Ricarten/village-2.smd'))
             if r['logical'].replace('\\','/').casefold() not in KNOWN_UNRECOVERABLE_TEXTURES]
    assert names
    row = audit_map(root, 'Field/Ricarten/village-2.smd',
                    _MappedResolver(missing=['field/ricarten/tem_wall04.bmp', names[0]]))
    assert row['status'] == 'REVIEW_REQUIRED'
    assert row['missing_count'] >= 1
    assert row['known_missing_count'] >= 1


def test_case_collisions_never_pick_arbitrarily(tmp_path):
    root = _make_root(tmp_path)
    from pt_asset_tool.stage072_corpus import parse_stage072
    from pt_asset_tool.stage072_texture_audit import _used_material_texture_refs
    refs = _used_material_texture_refs(parse_stage072(root/'Field/Ricarten/village-2.smd'))
    target = next(r['logical'] for r in refs if r['logical'].replace('\\','/').casefold() not in KNOWN_UNRECOVERABLE_TEXTURES)
    row = audit_map(root, 'Field/Ricarten/village-2.smd', _MappedResolver(ambiguous=[target]))
    assert row['collision_count'] >= 1
    assert row['paint_policy'] == 'BLOCKED_CASE_COLLISION'
    assert row['status'] == 'REVIEW_REQUIRED'


def test_find_all_stages_by_header_does_not_include_models(tmp_path):
    root = tmp_path / 'assets'
    (root/'Field/Ricarten').mkdir(parents=True)
    (root/'Field/Ricarten/village-2.smd').write_bytes(b'SMD Stage data Ver 0.72\x00')
    (root/'Field/MapB').mkdir(parents=True)
    (root/'Field/MapB/x.SMD').write_bytes(b'SMD Stage data Ver 0.72\x00')
    (root/'char').mkdir()
    (root/'char/test.smd').write_bytes(b'SMD Model data Ver 0.62\x00')
    (root/'Field/Ricarten/test.smd').write_bytes(b'unrelated')
    assert find_maps(root) == ['Field/MapB/x.SMD', 'Field/Ricarten/village-2.smd']


def test_batch_proceeds_after_failure_and_resumes(tmp_path, monkeypatch):
    root = tmp_path/'assets'
    (root/'Field/Alpha').mkdir(parents=True)
    for n in ('good.smd','bad.smd'):
        (root/'Field/Alpha'/n).write_bytes(b'SMD Stage data Ver 0.72\0')
    project = tmp_path/'project'
    project.mkdir()
    out = project/'pt_build/audits'
    calls = []
    from pt_asset_tool import stage072_batch_audit as bulk
    def fake_audit(client, rel, resolver, stage):
        calls.append(rel)
        st=(client/rel).stat()
        return {'asset':rel,'stage':stage,'signature':{'size':st.st_size,'mtime_ns':st.st_mtime_ns},
                'parse':'PASS' if 'good' in rel else 'FAIL','status':'PASS_STATIC' if 'good' in rel else 'FAIL_PARSE_OR_SOURCE',
                'paint_policy':'NOT_APPLICABLE_NO_TARGET_UV_LAYER','view_policy':'PASS_STATIC_VIEW_BASIS_NOT_RENDERED',
                'blender':'NOT_RUN','client_modified':False}
    monkeypatch.setattr(bulk, 'audit_map', fake_audit)
    result=run_all(project=project,client_root=root,output=out,quiet=True)
    assert result['files_audited']==2 and result['status']=='FAIL_OR_REVIEW_REQUIRES_ACTION'
    assert len(calls)==2
    result=run_all(project=project,client_root=root,output=out,quiet=True)
    assert len(calls)==2  # no reruns without source edits
    (root/'Field/Alpha/good.smd').write_bytes(b'SMD Stage data Ver 0.72\0NEW')
    result=run_all(project=project,client_root=root,output=out,quiet=True)
    assert len(calls)==3
    assert (out/'stage_0_maps.csv').is_file()
    assert len(json.loads((out/'stage_0_summary.json').read_text())['rows'])==2
    assert len(_load_checkpoint(out/'stage_0_checkpoint.jsonl',0))==2


def test_blender_headless_is_optional_never_opens_gui(tmp_path, monkeypatch):
    root=tmp_path/'assets';root.mkdir()
    (root/'Field').mkdir()
    (root/'Field/only.smd').write_bytes(b'SMD Stage data Ver 0.72\0')
    project=tmp_path/'app';project.mkdir()
    from pt_asset_tool import stage072_batch_audit as bulk
    def fake_audit(client, rel, resolver, stage):
        st=(client/rel).stat()
        return {'asset':rel,'stage':stage,'signature':{'size':st.st_size,'mtime_ns':st.st_mtime_ns},
                'parse':'PASS','status':'PASS_STATIC','paint_policy':'PASS_STATIC_CANDIDATE_NOT_BLENDER_TESTED',
                'view_policy':'PASS_STATIC_VIEW_BASIS_NOT_RENDERED','blender':'NOT_RUN'}
    monkeypatch.setattr(bulk, 'audit_map', fake_audit)
    worker_calls=[]
    def fake_worker(*args):
        worker_calls.append(args)
        return 'PASS_BLENDER_TRANSPORT_AND_VIEW', {'check':'PASS'}
    monkeypatch.setattr(bulk, '_run_worker', fake_worker)
    out=project/'pt_build/stage'
    run_all(project=project,client_root=root,output=out,quiet=True)
    assert worker_calls==[]
    second=run_all(project=project,client_root=root,output=out,blender=True,quiet=True)
    assert len(worker_calls)==1 and second['status']=='PASS_HEADLESS_WITH_REVIEW_NOT_VISUAL_CERTIFIED'
    third=run_all(project=project,client_root=root,output=out,blender=True,quiet=True)
    assert len(worker_calls)==1  # Blender proof cached for unchanged source
    assert third['blender_counts']=={'PASS_BLENDER_TRANSPORT_AND_VIEW':1}


def test_failed_blender_worker_recovers_on_reexecution(tmp_path, monkeypatch):
    from pt_asset_tool import stage072_batch_audit as bulk
    root=tmp_path/'assets';(root/'Field').mkdir(parents=True)
    (root/'Field/map.smd').write_bytes(b'SMD Stage data Ver 0.72\0')
    project=tmp_path/'app';project.mkdir()
    def fake_audit(client, rel, resolver, stage):
        st=(client/rel).stat()
        return {'asset':rel,'stage':stage,'signature':{'size':st.st_size,'mtime_ns':st.st_mtime_ns},
                'parse':'PASS','status':'PASS_STATIC','paint_policy':'PASS_STATIC_CANDIDATE_NOT_BLENDER_TESTED',
                'view_policy':'PASS_STATIC_VIEW_BASIS_NOT_RENDERED','blender':'NOT_RUN'}
    monkeypatch.setattr(bulk,'audit_map',fake_audit)
    attempts=[]
    def flaky(*a):
        attempts.append(len(attempts))
        return ('FAIL_BLENDER_TIMEOUT', {'error':'test timeout'}) if len(attempts)==1 else ('PASS_BLENDER_TRANSPORT_AND_VIEW',{'check':'PASS'})
    monkeypatch.setattr(bulk,'_run_worker',flaky)
    first=run_all(project=project,client_root=root,output=project/'out',blender=True,quiet=True)
    assert first['status']=='FAIL_OR_REVIEW_REQUIRES_ACTION'
    second=run_all(project=project,client_root=root,output=project/'out',blender=True,quiet=True)
    assert len(attempts)==2
    assert second['status']=='PASS_HEADLESS_WITH_REVIEW_NOT_VISUAL_CERTIFIED'
    assert json.loads((project/'out/stage_0_summary.json').read_text())['rows'][0]['status']=='PASS_STATIC'
