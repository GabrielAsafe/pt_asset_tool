"""V32: compact UI and per-selection hide-vs-replace (Blender-independent tests)."""
import ast
import json
from pathlib import Path
import pytest
from pt_asset_tool.environment_residual_v31 import blank, accept, check_state
from pt_asset_tool.residual_actions_v32 import (
    placement_from_bounds, validate_replacements, with_replacement, undo_last, MAX_EXTRA_TREES,
)

SHA = 'df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62'
MODEL_SHA = '39f47d9a69b20d28556d0ad74590cddd5dbe1004f9d9a366b67b35df8c90e30a'
MODEL='island_tree_01_1k.blend.zip'


def test_old_v31_json_remains_valid_and_migration_free():
    path=Path('/mnt/data/6cd0d6e8c7586543.v24_groups.v31_residuais.json')
    if path.exists():
        doc=json.loads(path.read_text())
    else:
        doc=blank('Field/forest/fore-1.smd',SHA,35519)
    check_state(doc,asset='Field/forest/fore-1.smd',sha=SHA,face_count=35519)
    assert validate_replacements(doc,face_count=35519)==[]
    assert doc.get('publish_enabled') is False


def test_tree_choice_is_extra_instance_while_leaf_choice_is_hide_only():
    d=blank('Field/forest/fore-1.smd',SHA,35519)
    hidden=accept(d,[15,16,17],seed=15,mode='ARVORE_LOCAL',
                  material_key='tex:na03_04.tga',asset=d['asset'],sha=SHA,face_count=35519)
    hidden['selections'][-1]['v32_action']='HIDE_LEAVES'
    assert hidden['extra_faces']==[15,16,17]
    assert validate_replacements(hidden,face_count=35519)==[]
    d2=accept(hidden,[25,26],seed=25,mode='ARVORE_LOCAL',material_key='tex:na03_04.tga',
              asset=d['asset'],sha=SHA,face_count=35519)
    record=placement_from_bounds([(1,2,3),(3,4,7)],seed=25,face_count=35519,
                                 model=MODEL,model_sha=MODEL_SHA,scale=1.3)
    d3=with_replacement(d2,record,face_count=35519)
    d3['selections'][-1]['v32_action']='REPLACE_TREE'
    assert len(validate_replacements(d3,face_count=35519))==1
    assert d3['extra_faces']==[15,16,17,25,26]
    assert d3['v32_replacements'][0]['anchor_view']==[2.,3.,3]
    assert d3['v32_replacements'][0]['height_view']==4.
    check_state(d3,asset=d['asset'],sha=SHA,face_count=35519)
    assert d['extra_faces']==[]
    assert 'v32_replacements' not in hidden


def test_invalid_placement_rejected_before_mutation():
    for bad in ('../tree.blend.zip', 'tree.glb', 'x/tree.blend.zip'):
        with pytest.raises(ValueError,match='MODELO_INVALIDO'):
            placement_from_bounds([(0,0,0)],seed=0,face_count=5,model=bad,model_sha=MODEL_SHA,scale=1)
    for points in ([],[(0,0,float('nan'))],[(0,0)]):
        with pytest.raises(ValueError,match='POSICAO_INVALIDA'):
            placement_from_bounds(points,seed=0,face_count=5,model=MODEL,model_sha=MODEL_SHA,scale=1)
    for scale in (0,20,float('inf'), True):
        with pytest.raises(ValueError,match='ESCALA_INVALIDA'):
            placement_from_bounds([(0,0,0)],seed=0,face_count=5,model=MODEL,model_sha=MODEL_SHA,scale=scale)


def test_replacement_limit_and_duplicate_seed_protection():
    doc=blank('test',SHA,5000)
    doc['extra_faces']=list(range(MAX_EXTRA_TREES+1))
    for i in range(MAX_EXTRA_TREES):
        rec=placement_from_bounds([(i,0,0),(i,0,2)],seed=i,face_count=5000,
                                  model=MODEL,model_sha=MODEL_SHA,scale=1)
        doc=with_replacement(doc,rec,face_count=5000)
    assert len(validate_replacements(doc,face_count=5000))==MAX_EXTRA_TREES
    with pytest.raises(ValueError,match='MAXIMO'):
        with_replacement(doc,placement_from_bounds([(0,0,0)],seed=50,face_count=5000,
                 model=MODEL,model_sha=MODEL_SHA,scale=1),face_count=5000)
    del doc['v32_replacements'][-1]
    with pytest.raises(ValueError,match='JA_GUARDADA'):
        with_replacement(doc,doc['v32_replacements'][0],face_count=5000)


def test_blender_integration_has_one_click_two_decisions_and_restore():
    base=Path(__file__).resolve().parents[1]/'pt_asset_tool/blender'
    env=(base/'stage072_environment_v26.py').read_text()
    res=(base/'environment_residual_v31.py').read_text()
    semantic=(base/'stage072_semantic_paint.py').read_text()
    textures=(base/'stage072_textures_v27.py').read_text()
    for x in (env,res,semantic,textures):
        ast.parse(x)
    assert "pt_env.v32_hide_leaves" in env
    assert "pt_env.v32_replace_tree" in env
    assert "pt_env.v31_pick_remaining" in env
    assert 'restore_v32_replacements()' in env
    assert '_v32_commit(context, replace_tree=False)' in res
    assert '_v32_commit(context, replace_tree=True)' in res
    assert "v32_replacements" in res
    assert 'atomic_write_json(_path(), updated)' in res
    assert 'PT_V32_ACTION=PASS' in res
    for source in (semantic,textures,res):
        assert "pt_v32_advanced" in source
    # The regular panel should not expose the long V26/V29/V30 walkthrough.
    ui=env.split('class PT_PT_EnvironmentV26(bpy.types.Panel):')[1].split('\n\nCLASSES = ')[0]
    assert "template_list" not in ui
    assert "pt_env.v32_hide_leaves" in ui
    assert "pt_env.v32_replace_tree" in ui


def test_saved_v32_records_reject_bad_source_and_malformed_records():
    d=blank('x',SHA,100)
    d['v32_replacements']=[{'seed':0}]
    with pytest.raises(ValueError):
        validate_replacements(d,face_count=100)
    assert validate_replacements(blank('x',SHA,100),face_count=100)==[]


def test_undo_last_choice_without_touching_legacy_selections():
    doc=blank('x',SHA,100)
    legacy=accept(doc,[1],seed=1,mode='ILHA_MATERIAL',material_key='t',asset='x',sha=SHA,face_count=100)
    tree=accept(legacy,[3,4],seed=3,mode='ARVORE_LOCAL',material_key='t',asset='x',sha=SHA,face_count=100)
    tree['selections'][-1]['v32_action']='REPLACE_TREE'
    tree['selections'][-1]['v32_faces']=[3,4]
    tree=with_replacement(tree,placement_from_bounds([(0,0,0),(0,0,2)],seed=3,
       face_count=100,model=MODEL,model_sha=MODEL_SHA,scale=1),face_count=100)
    out,faces,action,seed=undo_last(tree,face_count=100)
    assert (faces,action,seed)==([3,4],'REPLACE_TREE',3)
    assert out['extra_faces']==[1]
    assert len(out['selections'])==1
    assert out.get('v32_replacements')==[]
    with pytest.raises(ValueError,match='SEM_ACAO'):
        undo_last(out,face_count=100)

    leaves=accept(legacy,[5],seed=5,mode='ARVORE_LOCAL',material_key='t',asset='x',sha=SHA,face_count=100)
    leaves['selections'][-1]['v32_action']='HIDE_LEAVES'
    leaves['selections'][-1]['v32_faces']=[5]
    revised, faces, action,seed=undo_last(leaves,face_count=100)
    assert revised['extra_faces']==[1] and action=='HIDE_LEAVES'
    assert not revised.get('v32_replacements')
