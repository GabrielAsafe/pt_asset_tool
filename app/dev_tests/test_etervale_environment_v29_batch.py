"""V29 high-detail, single shared library batch: no implicit approvals."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import pytest
from pt_asset_tool.environment_batch_v29 import plan_tree_instances, preview_record, FORMAT

SHA = 'a' * 64


def g(ident, faces, *, trunk=True, category='ARVORE', status='PENDING'):
    return {'id': ident, 'category':category, 'trunk_faces':faces[-1:] if trunk else [],
            'faces':faces, 'anchor_view':[float(len(faces)), 0., 1.], 'height_view':3.2,
            'review_status':status, 'accepted_for_runtime':False}


def plan(groups, **kwargs):
    return plan_tree_instances(groups, source_face_count=40, source_sha256=SHA,
                asset='Field/forest/fore-1.smd', **kwargs)


def test_batch_picks_only_trunk_bearing_groups_and_keeps_distinct_instances():
    doc=plan([g('z',[1,2]),g('a',[4,5,6]),g('leaf',[9],trunk=False),g('rock',[11],category='PEDRA')])
    assert doc['count']==2 and [x['id'] for x in doc['trees']]==['a','z']
    assert doc['masked_face_indices']==[1,2,4,5,6] and doc['excluded_groups']==2
    assert not doc['publish_enabled'] and not doc['runtime_certified']


def test_default_is_highest_lod_only():
    assert plan([g('a',[1])])['lod']=='LOD0'
    with pytest.raises(ValueError, match='LOD0'):
        plan([g('a',[1])],lod='LOD1')


def test_rejects_duplicate_tree_ids_and_faces():
    with pytest.raises(ValueError,match='DUPLICADO'):
        plan([g('a',[1]),g('a',[2])])
    with pytest.raises(ValueError, match='DUPLICADA'):
        plan([g('a',[1,2]),g('b',[2,3])])
    with pytest.raises(ValueError, match='DUPLICADA'):
        plan([g('a',[1,1])])


def test_bounds_nan_and_non_tree_rejection():
    with pytest.raises(ValueError,match='FORA'):
        plan([g('a',[40])])
    a=g('a',[1]);a['anchor_view'][0]=float('nan')
    with pytest.raises(ValueError,match='ANCHOR'):
        plan([a])
    with pytest.raises(ValueError,match='SEM_ARVORES'):
        plan([g('a',[1],trunk=False)])
    with pytest.raises(ValueError,match='TRONCO'):
        a=g('a',[1]);a['trunk_faces']=[2];plan([a])


def test_explicitly_rejected_trees_are_excluded():
    doc=plan([g('a',[1]),g('b',[2],status='REJECTED')])
    assert doc['count']==1 and doc['excluded_groups']==1


def test_cannot_treat_nonapproved_preview_as_runtime_certified():
    a=g('a',[1]);a['accepted_for_runtime']=True
    with pytest.raises(ValueError,match='PUBLICACAO'):
        plan([a])


def test_preview_record_cannot_approve_or_publish():
    doc=plan([g('a',[1,2])]); cache={'source_sha256':'b'*64,
        'publish_enabled':False, 'levels':{'LOD0':{'faces':102933}}}
    report=preview_record(doc, model_name='island_tree_01_1k.blend.zip',
        model_sha256='b'*64,mask_originals=True,cache_manifest=cache)
    assert report['instance_count']==1 and report['masked_face_count']==2
    assert report['approval_status']=='NOT_APPROVED'
    assert report['source_lod0_faces']==102933
    assert report['publish_enabled'] is False and report['game_assets_modified'] is False
    assert report['runtime_certified'] is False
    cache['source_sha256']='c'*64
    with pytest.raises(ValueError,match='CACHE_INCOMPATIVEL'):
        preview_record(doc, model_name='tree',model_sha256='b'*64,
            mask_originals=False,cache_manifest=cache)


def test_input_groups_unmodified_and_100_instance_cap():
    inp=[g('a',[1]),g('leaf',[2],trunk=False)]
    before=deepcopy(inp)
    plan(inp)
    assert inp==before
    many=[g(f't{i}',[i]) for i in range(101)]
    with pytest.raises(ValueError,match='ACIMA_DO_LIMITE'):
        plan_tree_instances(many,source_face_count=200,source_sha256=SHA,
            asset='Field/forest/fore-1.smd')


def test_real_99_v24_groups_yield_56_tree_instances_if_fixture_present():
    fixture=Path('/mnt/data/6cd0d6e8c7586543.v24_groups.json')
    if not fixture.exists():
        pytest.skip('Conjunto local da V24 não incluído no pacote de testes')
    v24=json.loads(fixture.read_text())
    result=plan_tree_instances(v24['groups'],source_face_count=v24['source_face_count'],
        source_sha256=v24['source_sha256'], asset=v24['asset'])
    assert result['count']==56 and result['excluded_groups']==43
    assert len(result['masked_face_indices'])==3711


def test_blender_integration_does_not_duplicate_entire_stage_or_autoapprove():
    source=Path(__file__).parents[1]/'pt_asset_tool/blender/stage072_environment_v26.py'
    code=source.read_text()
    assert 'GeometryNodeDeleteGeometry' in code and "delete.domain = 'FACE'" in code
    assert 'V29_BATCH_COLLECTION' in code and 'already_prepared=True' in code
    assert 'pt_env.v29_preview_all_lod0' in code
    assert 'PT_V29_NOVA' not in code
    # The V29 path never touches SESSION['approvals'] or writes SMD.
    operation=code.split('class PT_OT_V29PreviewAllLOD0')[1].split('class PT_OT_V29Clear')[0]
    assert "SESSION['approvals']" not in operation
    assert 'PT_V29_BATCH=PASS' in operation
