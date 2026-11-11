"""V31 regression: source-locked, non-destructive residual vegetation picking."""
import ast
from pathlib import Path
import pytest
from pt_asset_tool.environment_residual_v31 import (
    MODES, expand, face_neighbors, blank, check_state, accept,
)

SHA = 'd'*64


def _geometry():
    # Face 0-1 are connected leaf cards; face 2 same texture but disconnected,
    # face 3 another leaf image nearby and face 4 is terrain, also nearby.
    return {
        'face_vertices':[(0,1,2),(2,1,3),(4,5,6),(7,8,9),(10,11,12)],
        'face_keys':['tex:leaf_a']*3 + ['tex:leaf_b', 'tex:ground'],
        'face_centers':[(0.,0.,2.),(.3,0.,2.),(1.,0.,2.1),(.5,.2,2.3),(.4,.3,1.)],
    }


def pick(seed=0, mode='ILHA_MATERIAL', **kw):
    d=_geometry()
    return expand(seed, mode, **d, foliage_keys={'tex:leaf_a','tex:leaf_b'}, **kw)


def test_connected_island_does_not_merge_disconnected_cards():
    assert pick() == [0,1]


def test_masked_faces_never_reselected():
    assert pick(hidden={1}) == [0]
    with pytest.raises(ValueError,match='JA_SUBSTITUIDA'):
        pick(seed=1,hidden={1})


def test_local_tree_includes_other_leaf_materials_but_not_ground():
    assert pick(mode='ARVORE_LOCAL', radius=2.) == [0,1,2,3]


def test_local_tree_without_foliage_seed_restricts_to_selected_texture():
    d = _geometry()
    assert expand(4, 'ARVORE_LOCAL', **d, foliage_keys={'tex:leaf_a','tex:leaf_b'},radius=3.) == [4]


def test_global_material_only_one_texture_and_never_includes_ground():
    assert pick(mode='MATERIAL_TODO') == [0,1,2]


def test_all_foliage_requires_explicit_known_key():
    assert pick(mode='FOLHAGEM_TODA', hidden={2}) == [0,1,3]
    with pytest.raises(ValueError, match='NAO_E_MATERIAL_FOLHAGEM'):
        pick(4,mode='FOLHAGEM_TODA')


def test_limits_and_unknown_mode_are_safely_rejected():
    with pytest.raises(ValueError,match='SELECAO_ACIMA_LIMITE'):
        pick(mode='MATERIAL_TODO',maximum=2)
    with pytest.raises(ValueError,match='MODO_INVALIDO'):
        pick(mode='X')
    with pytest.raises(ValueError,match='RAIO_INVALIDO'):
        pick(mode='ARVORE_LOCAL',radius=float('nan'))
    with pytest.raises(ValueError,match='MASCARA_INVALIDA'):
        pick(hidden={99})


def test_state_accept_requires_explicit_seed_and_keeps_sha():
    doc=blank('Field/forest/fore-1.smd',SHA,10)
    updated=accept(doc,[0,1],seed=0,mode='ILHA_MATERIAL',material_key='tex:leaf_a',
                   asset=doc['asset'],sha=SHA,face_count=10)
    assert doc['extra_faces']==[]
    assert updated['extra_faces']==[0,1]
    assert updated['publish_enabled'] is False and updated['game_assets_modified'] is False
    assert updated['selections'][0]['review_only'] is True
    with pytest.raises(ValueError,match='JA_GUARDADA'):
        accept(updated,[1],seed=1,mode='ILHA_MATERIAL',material_key='tex:leaf_a',
               asset=doc['asset'],sha=SHA,face_count=10)


def test_source_hash_and_out_of_range_are_refused():
    doc=blank('Field/forest/fore-1.smd',SHA,10)
    with pytest.raises(ValueError, match='FONTE_OU_ESTADO'):
        check_state(doc,asset=doc['asset'],sha='a'*64,face_count=10)
    doc['extra_faces']=[10]
    with pytest.raises(ValueError, match='INDICES_PERSISTIDOS'):
        check_state(doc,asset=doc['asset'],sha=SHA,face_count=10)


def test_compatibility_integration_registers_panel_and_reapplies_saved_mask():
    root=Path(__file__).resolve().parents[1] / 'pt_asset_tool' / 'blender'
    bpy_main=(root/'stage072_semantic_paint.py').read_text()
    env=(root/'stage072_environment_v26.py').read_text()
    addon=(root/'environment_residual_v31.py').read_text()
    for src in (bpy_main,env,addon):
        ast.parse(src)
    assert 'res_v31.CLASSES' in bpy_main and 'res_v31.configure()' in bpy_main
    assert 'res_v31.saved_extra_faces()' in env
    assert '_mask_v29_faces(sorted(set(plan[\'masked_face_indices\']) | extra))' in env
    assert 'pt_env.v31_pick_remaining' in addon
    assert 'pt_env.v31_confirm_mask' in addon
    assert 'invoke_confirm(self, event)' in addon
    assert 'source_unchanged=true game_unchanged=true publish=false' in addon


def test_report_ground_truth_v30_when_available():
    # Safely verifies the uploaded report when the current tool runtime has it.
    import json
    p=Path('/mnt/data/6cd0d6e8c7586543.v24_groups.v26_environment.v30_full_preview.json')
    if not p.is_file():
        pytest.skip('relatorio V30 apenas no contexto de teste da release')
    d=json.loads(p.read_text())
    assert d['instance_count']==99 and d['masked_face_count']==4817
    assert d['residual_suspect_material_faces']==1565
    assert d['publish_enabled'] is False
