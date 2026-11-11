"""Offline regression coverage for Stage072 semantic paint V21 (Blender-independent)."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import struct
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from pt_asset_tool.stage072_semantic_core import (
    FORMAT, VERSION, annotation_path, atomic_write_json, check_document,
    replace_overlapping_faces, source_anchor_from_view_vertices,
    source_to_view, suggest_material, view_to_source,
)


def test_source_view_mapping_with_actual_ricarten_center():
    center = (1043.207031, 324.892578, -17783.8125)
    scale = 0.0108945442
    source = (643.58984375, 273.265625, -20026.49609375)
    proxy = source_to_view(source, center, scale)
    assert tuple(round(x, 8) for x in proxy) == tuple(round(x, 8) for x in ((source[0]-center[0])*scale, (source[2]-center[2])*scale, (source[1]-center[1])*scale))
    reconstructed = view_to_source(proxy, center, scale)
    assert max(abs(a-b) for a,b in zip(source,reconstructed)) < 1e-8


def test_anchor_is_bottom_center_not_guessed_ground_contact():
    anchor = source_anchor_from_view_vertices([(0,0,3), (3,5,8), (2,4,7)], (10,20,30), 0.5)
    assert anchor['view_anchor'] == [1.5,2.5,3.0]
    assert anchor['game_anchor'] == [13.,26.,35.]
    assert 'NOT_GROUND_CERTIFIED' in anchor['method']


def test_material_keywords_are_hints_and_wall_not_collision():
    assert suggest_material('PT_STAGE072_MAT_0012_leaf01.tga')['category'] == 'ARVORE'
    assert suggest_material('field/fire/f-flame_0.tga')['category'] == 'FOGO'
    assert suggest_material('PT_STAGE072_MAT_0034_rock02.bmp')['category'] == 'PEDRA'
    assert suggest_material('WALL_BLUE_CHECKER')['confidence'] == 'REVER_WALL'
    assert suggest_material('WALL_BLUE_CHECKER')['category'] == 'PAREDE'
    assert suggest_material('tem_wall04.bmp')['category'] == 'PAREDE'
    assert suggest_material('pt_stage_mat_0023_wood_plank.bmp')['category'] == 'OUTRO'


def test_region_overwrite_preserves_unrelated_faces_and_never_publishes():
    a = {'view_anchor':[0,0,0], 'game_anchor':[0,0,0], 'method':'UNTESTED'}
    rows = replace_overlapping_faces([], obj_name='PT_STAGE072_VIEW_STAGE', chosen_faces=[3,4,5], category='ARVORE', region_id='id1', anchor=a, material_names=['leaf'])
    rows = replace_overlapping_faces(rows, obj_name='PT_STAGE072_VIEW_STAGE', chosen_faces=[4,6], category='ARBUSTO', region_id='id2', anchor=a, material_names=['bush'])
    assert rows[0]['faces'] == [3,5]
    assert rows[0]['anchor_needs_review'] is True
    assert rows[1]['faces'] == [4,6]
    assert all(r['accepted_for_runtime'] is False for r in rows)
    rows = replace_overlapping_faces(rows, obj_name='PT_STAGE072_VIEW_STAGE', chosen_faces=[6], category='APAGAR', region_id='x', anchor=a, material_names=[])
    assert rows[1]['faces'] == [4]
    assert len(rows) == 2


def test_wrong_category_does_not_corrupt_existing_regions():
    with pytest.raises(ValueError, match='UNKNOWN_CATEGORY'):
        replace_overlapping_faces([], obj_name='p', chosen_faces=[0], category='DELETE_ALL', region_id='x', anchor={}, material_names=[])
    with pytest.raises(ValueError, match='INVALID_FACE_SELECTION'):
        replace_overlapping_faces([], obj_name='p', chosen_faces=[-1], category='PEDRA', region_id='x', anchor={}, material_names=[])


def _doc(regions=None):
    return {'format':FORMAT,'version':VERSION,'asset':'Field/forest/fore-1.smd',
            'source_sha256':'a'*64,'source_face_count':9,'source_vertex_count':8,
            'regions': list(regions or []), 'publish_enabled':False}


def test_source_and_topology_guard():
    d = _doc()
    check_document(d, asset=d['asset'], source_sha256=d['source_sha256'], vertex_count=8, face_count=9)
    with pytest.raises(ValueError, match='SOURCE_IDENTITY_MISMATCH'):
        check_document(d, asset=d['asset'], source_sha256='b'*64, vertex_count=8, face_count=9)
    with pytest.raises(ValueError, match='SOURCE_TOPOLOGY_MISMATCH'):
        check_document(d, asset=d['asset'], source_sha256=d['source_sha256'], vertex_count=8, face_count=10)
    d['regions'] = [{'id':'x','category':'ARVORE','proxy_object':'p','faces':[9]}]
    with pytest.raises(ValueError, match='OUT_OF_BOUNDS'):
        check_document(d, asset=d['asset'], source_sha256=d['source_sha256'], vertex_count=8, face_count=9)


def test_overlapping_labels_or_runtime_publish_cannot_be_passed():
    r = {'id':'x','category':'ARVORE','proxy_object':'p','faces':[0,1],'accepted_for_runtime':False}
    d = _doc([r,{**r,'id':'y','category':'PEDRA','faces':[1,2]}])
    with pytest.raises(ValueError, match='OWNERSHIP_COLLISION'):
        check_document(d, asset=d['asset'], source_sha256=d['source_sha256'], vertex_count=8, face_count=9)
    d = _doc([{**r,'accepted_for_runtime':True}])
    with pytest.raises(ValueError, match='NOT_RUNTIME_PUBLICATION'):
        check_document(d, asset=d['asset'], source_sha256=d['source_sha256'], vertex_count=8, face_count=9)


def test_atomic_json_and_safe_annotation_path(tmp_path):
    logical='Field/Ricarten/village-2.smd'
    p=annotation_path(tmp_path,logical)
    assert p.parent.name=='maps'
    atomic_write_json(p,{'a':1,'name':'Árvore'})
    assert json.loads(p.read_text(encoding='utf8'))['name']=='Árvore'
    assert not list(p.parent.glob('*.tmp'))
    with pytest.raises(ValueError, match='UNSAFE_LOGICAL_ASSET'):
        annotation_path(tmp_path,'../../etc/passwd')


def test_blender_script_static_contract():
    script = APP/'pt_asset_tool/blender/stage072_semantic_paint.py'
    tree = ast.parse(script.read_text(encoding='utf8'))
    functions = {node.name for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
    for name in ('_get_view_ray','_hit_proxy','_anchor_for','_commit_stroke','_initialize','_save'):
        assert name in functions
    source=script.read_text(encoding='utf8')
    assert "bpy.app.timers.register(_initialize" in source
    assert "view_module.configure_stage072_view()" in source
    assert "inv = obj.matrix_world.inverted_safe()" in source
    assert "event.mouse_x - region.x" in source  # N-panel-safe picking
    assert "atomic_write_json(opts.output, DOCUMENT)" in source
    assert 'bpy.ops.wm.save_as_mainfile' not in source
    assert 'src.data.transform(' not in source
    assert 'PT_STAGE072_VIEW_STAGE' in source


def test_launcher_static_contract():
    script = APP/'pt_stage072_semantic_paint.py'
    source=script.read_text(encoding='utf8')
    assert 'load_validated_maps(' in source
    assert "_file_sha256(m['source'])" in source
    assert "shutil.copy2(m['preview_blend'], disposable)" in source
    assert "disposable.unlink(missing_ok=True)" in source
    assert "--source-sha256" in source
    assert "--include-classified" in source
    assert 'subprocess.run(args' in source
