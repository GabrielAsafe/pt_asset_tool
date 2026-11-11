"""V31.1: precision and stability checks without Blender installed."""
import ast
import json
from pathlib import Path
import pytest
from pt_asset_tool.residual_review_v31_1 import click_offsets, additions
from pt_asset_tool.environment_residual_v31 import check_state

SHA = 'df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62'


def test_click_center_first_and_bounded_snap():
    assert click_offsets(0) == [(0,0)]
    assert click_offsets(10)[0] == (0,0)
    assert len(click_offsets(10)) <= 17
    assert (10,0) in click_offsets(10)
    assert (-10,-10) in click_offsets(10)
    assert len(click_offsets(10)) == len(set(click_offsets(10)))
    assert click_offsets(20) == click_offsets(20)
    for bad in (-1, 21, True, 1.5, '10'):
        with pytest.raises(ValueError,match='SNAP_PX_INVALIDO'):
            click_offsets(bad)


def test_incremental_mask_does_not_rewrite_earlier_faces():
    old={1,2,3,4}
    assert additions(old,[6,5,6],10)==[5,6]
    assert old=={1,2,3,4}
    with pytest.raises(ValueError,match='JA_MASCARADA'):
        additions(old,[3],10)
    for invalid in ([10],[-1],[True],[]):
        with pytest.raises(ValueError):
            additions(old,invalid,10)


def test_blender_scripts_parse_and_stability_features_are_exposed():
    base=Path(__file__).resolve().parents[1]/'pt_asset_tool'
    addon=(base/'blender/environment_residual_v31.py').read_text()
    for src in (addon,(base/'residual_review_v31_1.py').read_text()):
        ast.parse(src)
    assert 'pt_env.v31_light_review' in addon
    assert 'pt_v31_snap_px' in addon
    assert 'pt_v31_auto_light' in addon
    assert 'GEOMETRY_CACHE' in addon
    assert 'mesh.from_pydata(verts, [], polygons)' in addon
    assert '_append_mask_without_node_rebuild(env, SELECTED)' in addon
    assert '_mask_v29_faces(sorted(previous_mask | set(SELECTED)))' not in addon
    assert 'atomic_write_json(_path(), updated)' in addon
    assert 'atomic_write_json(_path(), STATE)' in addon
    assert "v25._hide_native_stage_sources()" in addon
    assert 'PT_V31_1_LIGHT=PASS' in addon


def test_real_user_v31_json_preserved_if_present():
    path=Path('/mnt/data/6cd0d6e8c7586543.v24_groups.v31_residuais.json')
    if not path.is_file():
        pytest.skip('Dados reais V31 disponíveis apenas no ambiente de trabalho')
    doc=json.loads(path.read_text())
    check_state(doc,asset='Field/forest/fore-1.smd',sha=SHA,face_count=35519)
    assert len(doc['extra_faces'])==1781
    assert len(doc['selections'])==6
    assert doc['selections'][0]['count']==1565
    assert doc['publish_enabled'] is False and doc['game_assets_modified'] is False
