"""V23: geometry completion and source-lock, Blender-free regression tests."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0,str(APP))
from pt_asset_tool.stage072_trees_v23 import (
    TreeFace, build_tree_plan, check_tree_plan, preserve_tree_review, tree_plan_path,
)

ASSET='Field/forest/fore-1.smd'
SRC='d'*64

def f(i,material,x=0.,y=0.,z=.4,*,lo=None,hi=None,nz=0.,verts=(),area=.2):
    return TreeFace(i,material,(x,y,z),lo or (x-.08,y-.08,z-.2),
                    hi or (x+.08,y+.08,z+.2),nz,area,verts)


def v22(foliage,*,anchor=(0.,0.,0.),width=3.,height=3.):
    return {'format':'PT_ETERVALE_STAGE072_OBJECT_PROPOSALS_V22',
            'asset':ASSET,'source_sha256':SRC,'source_vertex_count':1000,
            'source_face_count':1000,
            'candidates':[{'id':'abc','category':'ARVORE','status':'PENDING',
              'faces':foliage,'view_anchor':list(anchor), 'view_bounds_min':[-1.5,-1.5,0.],
              'view_bounds_max':[1.5,1.5,3.], 'width_view':width, 'height_view':height,
              'confidence':'LOW_REVIEW_REQUIRED','ground_status':'LOCAL_GROUND_ESTIMATE_NOT_CERTIFIED'}]}


def scene():
    leaves=[f(i,'leaf.tga',x=.15,y=.0,z=2.6,lo=(-1,-1,2),hi=(1,1,3),verts=(100+i,101+i,102+i)) for i in range(10)]
    # Four faces connecting via shared vertex indices, from ground to canopy.
    bark=[f(100+i,'bark.bmp',x=.05,y=.02,z=.75,lo=(-.12,-.12,.05),hi=(.12,.12,1.65),
            verts=(1,2+i,3+i)) for i in range(4)]
    return leaves+bark


def build(data=None,faces=None):
    return build_tree_plan(v22=data or v22(list(range(10))),faces=faces if faces is not None else scene(),
                           center_xyz=(1000.,200.,3000.),view_scale=.01)


def test_reconstruct_tree_joins_trunk_without_changing_v22():
    source=v22(list(range(10)))
    frozen=deepcopy(source)
    plan=build(source)
    assert source==frozen
    assert plan['counts']=={'trees':1,'with_trunk':1,'leaves_only':0}
    t=plan['trees'][0]
    assert t['foliage_faces']==list(range(10))
    assert t['trunk_faces']==[100,101,102,103]
    assert len(t['faces'])==14
    assert t['completion']=='TRUNK_CANDIDATE_REVIEW'
    assert t['anchor_game'][1]==pytest.approx(200)
    assert t['accepted_for_runtime'] is False


def test_leaves_without_connected_vertical_trunk_stay_unconfirmed():
    plan=build(faces=scene()[:10])
    t=plan['trees'][0]
    assert t['trunk_faces']==[]
    assert t['completion']=='LEAVES_ONLY_REVIEW'
    assert plan['counts']['leaves_only']==1


def test_wall_behind_tree_is_not_trunk():
    faces=scene()[:10]+[f(100+i,'PT_STAGE072_MAT_000_WALL.bmp',x=0,y=0,z=.7,
                              lo=(-.15,-.2,.01),hi=(.15,.2,1.8),verts=(1,4+i,5+i)) for i in range(6)]
    plan=build(faces=faces)
    assert plan['trees'][0]['trunk_faces']==[]


def test_horizontal_ground_is_not_trunk():
    faces=scene()[:10]+[f(100+i,'grass.bmp',x=0,y=0,z=.02,nz=1.,
                              lo=(-.3,-.3,0),hi=(.3,.3,.04),verts=(1,4+i,5+i)) for i in range(6)]
    assert not build(faces=faces)['trees'][0]['trunk_faces']


def test_past_proposals_are_ignored_when_rejected():
    source=v22(list(range(10)))
    source['candidates'][0]['status']='REJECTED'
    assert build(source)['counts']['trees']==0


def test_source_locked_report_rejects_publish_and_bad_face():
    doc=build()
    check_tree_plan(doc,asset=ASSET,source_sha256=SRC,vertex_count=1000,face_count=1000)
    with pytest.raises(ValueError,match='SOURCE_MISMATCH'):
        check_tree_plan(doc,asset=ASSET,source_sha256='a'*64,vertex_count=1000,face_count=1000)
    doc['publish_enabled']=True
    with pytest.raises(ValueError,match='PUBLICATION_FORBIDDEN'):
        check_tree_plan(doc,asset=ASSET,source_sha256=SRC,vertex_count=1000,face_count=1000)
    doc['publish_enabled']=False
    doc['trees'][0]['faces'].append(1000)
    with pytest.raises(ValueError,match='INVALID_TREE_FACES'):
        check_tree_plan(doc,asset=ASSET,source_sha256=SRC,vertex_count=1000,face_count=1000)


def test_approval_preserved_only_same_source_and_id():
    a=build(); b=build()
    a['trees'][0]['status']='APPROVED';a['trees'][0]['note']='Tronco correto'
    preserve_tree_review(b,a)
    assert b['trees'][0]['status']=='APPROVED'
    assert b['trees'][0]['note']=='Tronco correto'
    a['source_sha256']='a'*64
    with pytest.raises(ValueError,match='SOURCE_MISMATCH'):
        preserve_tree_review(b,a)


def test_path_does_not_overwrite_v22_json():
    p=tree_plan_path(Path('/tmp/123.v22_proposals.json'))
    assert p.name=='123.v23_trees.json'


def test_float_and_geometry_validations():
    with pytest.raises(ValueError,match='INVALID_TREE_FACE'):
        f(-1,'leaves')
    with pytest.raises(ValueError,match='INVALID_VIEW_SCALE'):
        build_tree_plan(v22=v22(list(range(10))),faces=scene(),center_xyz=(0.,0.,0.),view_scale=0.)


def test_blender_ui_wiring_is_non_destructive():
    addon=(APP/'pt_asset_tool/blender/stage072_semantic_paint.py').read_text()
    v23=(APP/'pt_asset_tool/blender/stage072_tree_v23.py').read_text()
    tree=ast.parse(v23)
    classes={n.name for n in tree.body if isinstance(n,ast.ClassDef)}
    assert {'PT_OT_V23Build','PT_OT_V23Separate','PT_OT_V23Preview','PT_PT_V23Panel'} <= classes
    assert 'tree_v23.CLASSES' in addon
    assert 'tree_v23.configure' in addon
    assert 'PT_V23_ARVORES_INSPECAO_SO_COPIA' in v23
    assert 'PT_V23_STAGE_MASCARADO_SO_PREVIEW' in v23
    assert 'bpy.ops.wm.save_as_mainfile' not in v23
    assert 'app/pt_build' not in v23  # workspace path from secure launcher
    assert 'from __future__ import annotations' not in v23  # Blender property registration


def test_real_uploaded_v22_proposals_source_locked_and_all_trees():
    path=Path('/mnt/data/6cd0d6e8c7586543.v22_proposals.json')
    if not path.exists():
        pytest.skip('User sample is not a distributed test fixture')
    doc=json.loads(path.read_text())
    assert len(doc['candidates'])==103
    assert all(p['category']=='ARVORE' and p['status']=='PENDING' for p in doc['candidates'])
    assert all(not p['accepted_for_runtime'] for p in doc['candidates'])
