import json
from copy import deepcopy
from pathlib import Path
import pytest

from pt_asset_tool.stage072_trees_v23 import TreeFace, FORMAT as V23_FORMAT
from pt_asset_tool.stage072_tree_groups_v24 import (
    FORMAT, build_v24_groups, check_v24_groups, accept_manual_attachment, group_plan_path,
)


def face(i,x,y,z,mat='leaf'):
    return TreeFace(i,mat,(x,y,z),(x-.1,y-.1,z-.2),(x+.1,y+.1,z+.2),.1,.05, (i*3,i*3+1,i*3+2))


def tree(tid, leaf_ids, trunk_ids, xyz, height=4, width=4):
    return {'id':tid,'foliage_faces':leaf_ids,'trunk_faces':trunk_ids,
            'faces':sorted(leaf_ids+trunk_ids),'anchor_view':list(xyz),
            'anchor_game':list(xyz),'height_view':height,'width_view':width,
            'status':'PENDING'}


def make():
    # Two established trunks, one clearly tiny foliage fragment, one large
    # orphan canopy near the second trunk, another material, and an ambiguity.
    trees=[
        tree('a', [0,1,2,3],[4,5],(0,0,0)),
        tree('b', [6,7,8,9],[10,11],(7,0,0)),
        tree('fragment',[12,13],[],(.35,0,0),height=.5),
        tree('large_orphan',list(range(14,29)),[],(7.65,0,0),height=3.5),
        tree('other_mat',[29],[],(.3,0,0),height=.4),
        tree('between',[30],[],(3.4,0,0),height=.4),
    ]
    fs=[]
    for i in range(31):
        if i in (4,5):
            fs.append(face(i,0,0,.8,mat='bark'))
        elif i in (10,11):
            fs.append(face(i,7,0,.8,mat='bark'))
        elif i in (12,13):
            fs.append(face(i,.35,0,2.2))
        elif 14<=i<29:
            fs.append(face(i,7.65,0,2.2))
        elif i==29:
            fs.append(face(i,.3,0,2.2,mat='wall'))
        elif i==30:
            fs.append(face(i,3.4,0,2.2))
        elif i<=3:
            fs.append(face(i,0,0,2.2))
        else:
            fs.append(face(i,7,0,2.2))
    v23={
       'format':V23_FORMAT,'asset':'Field/forest/fore-1.smd',
       'source_sha256':'x'*64,'source_vertex_count':93,'source_face_count':31,
       'trees':trees,
    }
    return v23, fs


def test_one_small_fragment_attached_but_large_stays_review():
    v,fs=make()
    plan=build_v24_groups(v23=v,faces=fs)
    assert plan['format']==FORMAT
    assert plan['counts']['source_proposals']==6
    assert plan['counts']['groups']==5
    assert plan['counts']['auto_attached']==1
    g={t['id']:t for t in plan['groups']}
    assert 'fragment' not in g
    assert 'fragment' in g['a']['source_tree_ids']
    assert set([12,13]) <= set(g['a']['foliage_faces'])
    assert g['large_orphan']['suggested_trunk_id']=='b'
    assert g['large_orphan']['completion']=='FOLIAGE_ONLY_REVIEW_SUGGESTED_STEM'
    assert g['other_mat']['suggested_trunk_id'] is None
    assert check_v24_groups(plan,v23=v)
    assert plan['publish_enabled'] is False


def test_manual_attachment_is_explicit_and_preserves_all_faces():
    v,fs=make()
    p=build_v24_groups(v23=v,faces=fs)
    dest=accept_manual_attachment(p,orphan_id='large_orphan',v23=v)
    assert dest=='b'
    assert 'large_orphan' in next(x for x in p['groups'] if x['id']=='b')['source_tree_ids']
    assert not any(x['id']=='large_orphan' for x in p['groups'])
    assert p['counts']['groups']==4
    assert check_v24_groups(p,v23=v)
    with pytest.raises(ValueError,match='V24_ORPHAN_NOT_FOUND'):
        accept_manual_attachment(p,orphan_id='large_orphan',v23=v)


def test_no_accidental_merge_of_distinct_stems():
    v,fs=make()
    v['trees'][1]['anchor_view']=[.8,0,0]
    p=build_v24_groups(v23=v,faces=fs)
    assert any(g['id']=='a' for g in p['groups'])
    assert any(g['id']=='b' for g in p['groups'])
    with pytest.raises(ValueError,match='V24_NO_VALID_SUGGESTED_STEM'):
        accept_manual_attachment(p,orphan_id='b',v23=v)


def test_rejects_overlap_and_missing_faces():
    v,fs=make()
    p=build_v24_groups(v23=v,faces=fs)
    p['groups'][1]['faces'].append(p['groups'][0]['faces'][0])
    with pytest.raises(ValueError,match='V24_DUPLICATE_OR_MISSING_FACES'):
        check_v24_groups(p,v23=v)


def test_source_fingerprint_and_runtime_publish_guard():
    v,fs=make()
    p=build_v24_groups(v23=v,faces=fs)
    other=deepcopy(v)
    other['trees'][0]['faces']=[0,1,2,3,4]  # provenance changed
    with pytest.raises(ValueError,match='V24_V23_FACE_PLAN_CHANGED'):
        check_v24_groups(p,v23=other)
    p['publish_enabled']=True
    with pytest.raises(ValueError,match='V24_PUBLICATION_FORBIDDEN'):
        check_v24_groups(p,v23=v)


def test_bad_v23_and_paths():
    v,fs=make()
    v['format']='UNKNOWN'
    with pytest.raises(ValueError,match='V24_REQUIRES_VALID_V23'):
        build_v24_groups(v23=v,faces=fs)
    assert str(group_plan_path(Path('abc.v23_trees.json'))) == 'abc.v24_groups.json'
    with pytest.raises(ValueError,match='V24_EXPECTS_V23_PATH'):
        group_plan_path(Path('v22.json'))


def test_blender_script_has_registration_and_separate_output():
    p=Path(__file__).resolve().parents[1]/'pt_asset_tool/blender/stage072_semantic_paint.py'
    s=p.read_text()
    assert 'tree_v24.CLASSES' in s and 'tree_v24.configure()' in s
    addon=Path(__file__).resolve().parents[1]/'pt_asset_tool/blender/stage072_tree_group_v24.py'
    s=addon.read_text()
    assert "PT_V24_ARVORES_AGRUPADAS_INSPECAO" in s
    assert "PT_V24_GROUP=PASS" in s
    assert "PT_V24_SEPARATE=PASS" in s
    assert 'from __future__ import annotations' not in s


def test_real_forest_v22_proposal_snapshot_remains_supported():
    sample=Path('/mnt/data/6cd0d6e8c7586543.v22_proposals.json')
    if not sample.is_file():
        pytest.skip('snapshot externo indisponível')
    data=json.loads(sample.read_text())
    assert len(data['candidates'])==103
    assert len({x for c in data['candidates'] for x in c['faces']})==3859
