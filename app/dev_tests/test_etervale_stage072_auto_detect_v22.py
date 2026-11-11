"""V22 behavior tests: geometry, terrain, source-lock, labels, review safety."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0,str(APP))
from pt_asset_tool.stage072_semantic_detect_v22 import (
    Face, build_candidates, check_proposals, manual_material_evidence,
    preserve_review_decisions, proposals_path,
)

SRC='a'*64
ASSET='Field/forest/fore-1.smd'


def face(i, material, x, y, z, w=.25, h=.5, normal_z=0., area=.15):
    return Face(i, material, (x,y,z), (x-w/2,y-w/2,z-h/2),
                (x+w/2,y+w/2,z+h/2), normal_z, area)


def _scene():
    faces=[]
    i=0
    # Ground extending through 10x10 in view space.
    for x in range(-5,9):
        for y in range(-5,9):
            faces.append(face(i,'ground_rock.bmp',float(x),float(y),0.,w=1.,h=.01,normal_z=1.,area=.48)); i+=1
    # Tree canopy separate textured leaf cards, height 2..5, narrow base.
    for j in range(32):
        x=(j%8 -3.5)*.24
        y=(j//8-1.5)*.30
        z=2.3 + ((j*7)%10)*.26
        faces.append(face(i,'leaf_foliage_01.tga',x,y,z,w=.55,h=.9)); i+=1
    # A different tree 5.6 units away; should not fuse into first.
    for j in range(23):
        x=5.7+(j%6-2.5)*.22
        y=(j//6-1.5)*.27
        z=2.2 + ((j*7)%9)*.3
        faces.append(face(i,'leaf_foliage_01.tga',x,y,z,w=.52,h=.75)); i+=1
    # Massive tall wall next to tree (must not be called tree or rock).
    for j in range(35):
        faces.append(face(i,'WALL_test.bmp',8,j*.14,1.4+j*.06,w=.6,h=.7)); i+=1
    # Bush crosses texture cards close to soil, low height
    for j in range(9):
        faces.append(face(i,'bush_shrub.tga',-4+(j%3)*.25,3+(j//3)*.25,.65,w=.35,h=.5)); i+=1
    return faces


def detect(faces=None,manual=None):
    faces = faces if faces is not None else _scene()
    return build_candidates(asset=ASSET,source_sha256=SRC,faces=faces,
                            manual_regions=manual or [], center_xyz=(100,200,300),
                            view_scale=.01, radius=1.0, max_candidates=120)


def test_detect_two_trees_and_one_bush_but_no_wall():
    doc=detect()
    trees=[p for p in doc['candidates'] if p['category']=='ARVORE']
    shrubs=[p for p in doc['candidates'] if p['category']=='ARBUSTO']
    assert len(trees)==2, [(c['face_count'],c['view_bounds_min'],c['view_bounds_max']) for c in trees]
    assert shrubs
    assert sum(len(x['faces']) for x in trees) == 55
    assert not any('WALL' in ' '.join(p['materials']) for p in doc['candidates'])
    assert all(p['status']=='PENDING' and p['accepted_for_runtime'] is False for p in doc['candidates'])
    assert all(p['ground_status'] for p in doc['candidates'])
    assert doc['publish_enabled'] is False


def test_vegetation_height_vs_width_and_ground_and_no_guessed_rock():
    faces=[face(i,'generic.bmp',i*.1,0,10+i*.01) for i in range(20)]
    assert not detect(faces)['candidates']
    # A height-less carpet of leaf triangles is not a tree.
    faces=[face(i,'leaf.tga',i*.08,0,2,h=.01) for i in range(15)]
    assert not any(p['category']=='ARVORE' for p in detect(faces)['candidates'])


def test_manual_examples_are_weak_and_ignore_tiny_wrong_labels():
    regs=[{'category':'ARVORE','materials':['MAT_tree_01.tga'],'faces':list(range(30))} for _ in range(4)]
    regs += [{'category':'ARVORE','materials':['PT_STAGE072_MAT_0462_t_city-hall.bmp'],'faces':list(range(300))} for _ in range(10)]
    regs += [{'category':'PEDRA','materials':['unknown.bmp'],'faces':[1]} for _ in range(25)]
    e=manual_material_evidence(regs)
    assert 'MAT_tree_01.tga' in e
    assert 'PT_STAGE072_MAT_0462_t_city-hall.bmp' not in e
    assert 'unknown.bmp' not in e
    faces=[face(i, 'MAT_tree_01.tga', (i%5)*.18,(i//5)*.18,2+(i%4)*.5) for i in range(25)]
    doc=detect(faces,regs)
    assert doc['candidates']
    assert all(p['confidence'].startswith('LOW_') for p in doc['candidates'])


def test_cannot_convert_approval_to_runtime_publish():
    doc=detect()
    doc['source_vertex_count']=777
    check_proposals(doc,asset=ASSET,source_sha256=SRC,vertex_count=777,face_count=len(_scene()))
    doc['candidates'][0]['status']='APPROVED'
    check_proposals(doc,asset=ASSET,source_sha256=SRC,vertex_count=777,face_count=len(_scene()))
    doc['candidates'][0]['accepted_for_runtime']=True
    with pytest.raises(ValueError,match='FORBIDDEN'):
        check_proposals(doc,asset=ASSET,source_sha256=SRC,vertex_count=777,face_count=len(_scene()))


def test_cannot_open_foreign_or_stale_proposal_document():
    doc=detect();doc['source_vertex_count']=777
    with pytest.raises(ValueError,match='SOURCE_MISMATCH'):
        check_proposals(doc,asset=ASSET,source_sha256='b'*64,vertex_count=777,face_count=len(_scene()))
    with pytest.raises(ValueError,match='TOPOLOGY_MISMATCH'):
        check_proposals(doc,asset=ASSET,source_sha256=SRC,vertex_count=888,face_count=len(_scene()))
    doc['candidates'][0]['faces']=[0,len(_scene())]
    with pytest.raises(ValueError,match='OUT_OF_RANGE'):
        check_proposals(doc,asset=ASSET,source_sha256=SRC,vertex_count=777,face_count=len(_scene()))


def test_rerun_preserves_review_decision_when_same_faces():
    old=detect(); new=detect()
    old['candidates'][0]['status']='REJECTED'
    old['candidates'][0]['note']='confundiu uma árvore com uma estrutura'
    old['candidates'][0]['replacement_asset']='test.glb'
    merged=preserve_review_decisions(new,old)
    assert merged['candidates'][0]['status']=='REJECTED'
    assert merged['candidates'][0]['note'].startswith('confundiu')


def test_proposal_names_are_separate_from_manual_labels():
    p=proposals_path(Path('/tmp/abcaabbccd.json'))
    assert p.name=='abcaabbccd.v22_proposals.json'


def test_works_with_real_v21_annotated_material_samples():
    # This test works on the V21 examples if supplied, but does not require
    # shipping any personal classification JSON with the installer.
    example=Path('/mnt/data/6cd0d6e8c7586543.json')
    if not example.is_file():
        pytest.skip('No provided example data in environment')
    d=json.loads(example.read_text(encoding='utf-8'))
    evidence=manual_material_evidence(d['regions'])
    assert len(d['regions'])>=100
    assert evidence.get('PT_STAGE072_MAT_0036_na03_04.tga',{}).get('category')=='ARVORE'
    assert 'PT_STAGE072_MAT_0462_t_city-hall.bmp' not in evidence


def test_blender_wiring_is_source_locked_and_preview_only():
    source=(APP/'pt_asset_tool/blender/stage072_semantic_paint.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    classes={x.name for x in tree.body if isinstance(x,ast.ClassDef)}
    assert {'PT_OT_V22Detect','PT_OT_V22Decide','PT_PT_V22Panel','PT_V22Proposal'}<=classes
    assert "bl_parent_id = 'PT_PT_ETERVALE_SEMANTIC_V21'" in source
    assert 'PT_STAGE072_V22_HIGHLIGHT_VIEW_ONLY' in source
    assert "atomic_write_json(_v22_path(), PROPOSALS)" in source
    assert 'bpy.ops.wm.save_as_mainfile' not in source
