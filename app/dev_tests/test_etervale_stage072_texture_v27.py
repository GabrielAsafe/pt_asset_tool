"""Pure Python tests for V27 map-scoped material/classification grouping."""
import json
from pathlib import Path
import sys
import pytest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from pt_asset_tool.stage072_texture_semantics_v27 import (
    build_catalog, check_catalog, texture_identity, assign_rule, remove_rule,
)
from pt_asset_tool.environment_library_v26 import classify_name, scan_library
from pt_asset_tool.environment_lod_v27 import lod_plan

SHA='df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62'
ASSET='Field/forest/fore-1.smd'


def synthetic():
    slots=[{'index':0,'name':'PT_STAGE072_MAT_0034_na03_07.tga'},
           {'index':1,'name':'PT_STAGE072_MAT_0577_na03_07.tga'},
           {'index':2,'name':'PT_STAGE072_MAT_0500_firesheet.tga'},
           {'index':3,'name':'PT_STAGE072_MAT_0020_NO_TEXTURE'}]
    faces=[
        # same texture across two different material slots, connected via edge 1-2
        {'index':0,'vertices':[0,1,2], 'material_index':0,'area':4.,'normal_z':0.},
        {'index':1,'vertices':[2,1,3], 'material_index':1,'area':4.,'normal_z':0.},
        # same texture but disconnected: new object
        {'index':2,'vertices':[20,21,22], 'material_index':0,'area':1.,'normal_z':0.},
        {'index':3,'vertices':[4,5,6], 'material_index':2,'area':2.,'normal_z':0.},
        {'index':4,'vertices':[7,8,9], 'material_index':3,'area':2.,'normal_z':1.},
    ]
    return slots, faces


def catalog():
    slots, faces=synthetic()
    return build_catalog(asset=ASSET,source_sha256=SHA,source_face_count=len(faces),
                         slots=slots,faces=faces,
                         v22_material_names={'PT_STAGE072_MAT_0034_na03_07.tga'})


def test_texture_id_real_stage_name_and_no_texture_slot():
    assert texture_identity('PT_STAGE072_MAT_0034_na03_07.tga',slot_index=9)=='tex:na03_07.tga'
    assert texture_identity('PT_STAGE072_MAT_0577_na03_07.tga',slot_index=2)=='tex:na03_07.tga'
    assert texture_identity('PT_STAGE072_MAT_0031_NO_TEXTURE',slot_index=7).startswith('slot:0007:')
    assert texture_identity('PT_STAGE072_MAT_0031_NO_TEXTURE','//folder/my.jpg',7)=='tex:my.jpg'


def test_connected_components_cross_slots_and_integrity():
    doc=catalog()
    assert doc['counts']['textures']==3
    assert doc['counts']['components']==4
    assert doc['publish_enabled'] is False
    leaf=next(t for t in doc['textures'] if t['key']=='tex:na03_07.tga')
    assert [c['faces'] for c in leaf['components']]==[[0,1],[2]]
    assert leaf['slots']==[0,1]
    assert leaf['suggestion']=='FOLHAGEM'
    assert leaf['reason'].startswith('V22_')
    assert not doc['rules']
    all_faces=[i for t in doc['textures'] for c in t['components'] for i in c['faces']]
    assert sorted(all_faces)==list(range(5))


def test_confirm_rule_only_stage_sha_and_preserve_on_rescan():
    doc=catalog()
    nxt=assign_rule(doc,'tex:na03_07.tga','ARBUSTO','test')
    assert doc['rules']=={}
    assert nxt['rules']['tex:na03_07.tga']['confirmed'] is True
    slots,faces=synthetic()
    rescan=build_catalog(asset=ASSET,source_sha256=SHA,source_face_count=5,
                         slots=slots,faces=faces, previous=nxt)
    assert rescan['rules']['tex:na03_07.tga']['category']=='ARBUSTO'
    assert rescan['counts']['classified']==1
    without=remove_rule(rescan,'tex:na03_07.tga')
    assert not without['rules']
    with pytest.raises(ValueError,match='INCOMPATIVEL'):
        check_catalog(rescan,asset='Field/forest/fore-2.smd',sha=SHA,face_count=5)
    with pytest.raises(ValueError,match='INCOMPATIVEL'):
        build_catalog(asset=ASSET,source_sha256='1'*64,source_face_count=5,
                      slots=slots,faces=faces, previous=rescan)


def test_texture_not_equal_physical_tree_splitting_is_required():
    doc=catalog()
    leaf=next(t for t in doc['textures'] if t['key']=='tex:na03_07.tga')
    assert leaf['faces']==3 and leaf['component_count']==2
    assert len(doc['rules'])==0  # heuristic not committed


def test_collision_or_missing_polygon_blocked():
    slots,faces=synthetic()
    faces[-1]['index']=2
    with pytest.raises(ValueError,match='INDICES_FACES_INVALIDOS'):
        build_catalog(asset=ASSET,source_sha256=SHA,source_face_count=5,slots=slots,faces=faces)
    doc=catalog()
    doc['textures'][0]['components'][0]['faces'].append(0)
    with pytest.raises(ValueError):
        check_catalog(doc,asset=ASSET,sha=SHA,face_count=5)


def test_real_uploaded_data_matches_valid_stage_anchor():
    path=Path('/mnt/data/6cd0d6e8c7586543.materials.json')
    if not path.exists():
        pytest.skip('Amostra do utilizador não está presente no ambiente de testes local')
    materials=json.loads(path.read_text())
    assert materials['source_sha256']==SHA
    source={m['material_name'] for m in materials['candidates']}
    assert 'PT_STAGE072_MAT_0034_na03_07.tga' in source
    assert len(source)>100


def test_library_bark_is_material_and_tree_is_geometry(tmp_path):
    assert classify_name('tree_bark_03_1k.blend.zip')=='MATERIAL'
    assert classify_name('island_tree_01_1k.blend.zip')=='ARVORE'
    assert classify_name('pine_sapling_medium_1k.blend.zip')=='ARVORE'
    root=tmp_path/'AssetsForAutomaticSubstitution';root.mkdir()
    for f in ('tree_bark_03_1k.blend.zip','island_tree_01_1k.blend.zip'):
        (root/f).write_bytes(b'dummy')
    rows=scan_library(root)
    assert [(r.name,r.ready) for r in rows]==[
        ('island_tree_01_1k.blend.zip',True),('tree_bark_03_1k.blend.zip',False)]


def test_lod_budget_over_previous_750k_vertex_limit():
    p=lod_plan(1_050_000,850_000)
    assert p['simplify'] and .1 < p['ratio'] < .36
    assert lod_plan(10000,8000)['simplify'] is False
    with pytest.raises(ValueError,match='PESADO_DEMAIS'):
        lod_plan(4_000_000,2_000_000)


def test_blender_integration_source_has_no_game_export():
    addon=(APP/'pt_asset_tool/blender/stage072_textures_v27.py').read_text()
    glue=(APP/'pt_asset_tool/blender/stage072_semantic_paint.py').read_text()
    environment=(APP/'pt_asset_tool/blender/stage072_environment_v26.py').read_text()
    assert 'tex_v27.configure()' in glue
    assert ' + tex_v27.CLASSES' in glue
    assert 'PT_PT_ETERVALE_ENVIRONMENT_V26' in addon
    assert 'PT_V27_TEXTURA_COMPONENTES_SO_PREVIEW' in addon
    assert 'v23._create_inspection_mesh' in addon
    assert 'lod_plan(vertices, faces)' in environment
    assert 'bpy.data.meshes.new_from_object' in environment
    assert 'bpy.ops.export_scene' not in addon
