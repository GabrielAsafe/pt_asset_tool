from __future__ import annotations
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('m1_delta', Path(__file__).parents[1]/'tools/m1_real_stage_delta.py')
m1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m1)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    from pt_asset_tool.stage072_compiler import compile_stage072
    tool = tmp_path/'project'
    (tool/'app').mkdir(parents=True)
    real_package = Path(__import__('pt_asset_tool').__file__).resolve().parent
    (tool/'app/pt_asset_tool').symlink_to(real_package, target_is_directory=True)
    game=tmp_path/'Etervale-git'; assets=game/'assets'
    (assets/'Field/forest').mkdir(parents=True)
    material=[{'textures':['leaf.bmp'],'use_state':0,'mesh_state':0},
              {'in_use':False,'textures':[],'use_state':0x400,'mesh_state':0}]
    buf,_ = compile_stage072({'materials':material,
                              'vertices':[[0,0,0],[64,0,0],[0,0,64],[64,0,64]],
                              'faces':[{'vertices':[0,2,1],'material':0,'uv_layers':[[[0,0],[0,1],[1,0]]]},
                                       {'vertices':[1,2,3],'material':0,'uv_layers':[[[1,0],[0,1],[1,1]]]}]})
    stage=assets/'Field/forest/fore-1.smd';stage.write_bytes(buf)
    # Dependency graph resolves basename relative to stage directory.
    (stage.parent/'leaf.bmp').write_bytes(b'BM' + b'\x00'*70)
    (assets/'leaf.bmp').write_bytes(b'BM' + b'\x00'*70)
    map_dir = tool/'app/pt_build/etervale/stage072_semantic_v21/maps'
    map_dir.mkdir(parents=True)
    sh=m1.sha256(buf)
    base={'asset':'Field/forest/fore-1.smd','source_sha256':sh,'source_face_count':2}
    (map_dir/'a.v24_groups.json').write_text(json.dumps({**base,'format':'PT_ETERVALE_STAGE072_TREE_GROUPS_V24',
        'groups':[{'id':'abc','faces':[0],'anchor_game':[1,0,2]}]}))
    (map_dir/'a.v24_groups.v26_environment.v30_full_preview.json').write_text(json.dumps({**base,
        'format':'PT_ETERVALE_ENVIRONMENT_BATCH_V30','instance_group_ids':['abc'],
        'masked_face_count':1,'instance_count':1,'model_name':'tree.blend.zip','model_sha256':'f'*64,'lod':'LOD0'}))
    (map_dir/'a.v24_groups.v31_residuais.json').write_text(json.dumps({**base,
        'format':'PT_ETERVALE_ENVIRONMENT_RESIDUAL_V31','extra_faces':[]}))
    return tool,game,map_dir,sh,stage


def test_mask_only_changes_face_material_and_preserves_physics(fixture,tmp_path):
    from pt_asset_tool.stage072_corpus import parse_stage072
    tool,game,map_dir,sha,source=fixture
    masks, plan = m1.collect_selections(*(m1.read_json(m1.locate(map_dir,s)) for s in (
        '.v24_groups.json','.v24_groups.v26_environment.v30_full_preview.json','.v24_groups.v31_residuais.json')),
        stage_sha=sha,face_count=2)
    assert masks == {0}
    assert plan['planned_model_instances']==1
    target=tmp_path/'modified.smd'
    result=m1.patch_stage(source,masks,target,expected_sha=sha,expected_faces=2)
    assert result['remapped_faces']==1
    assert result['collision_classification_unchanged'] is True
    assert result['output_sha256'] != sha
    assert m1.file_sha(source)==sha
    parsed=parse_stage072(target,include_payload=True)
    assert parsed['payload']['faces'][0]['material']==1
    assert parsed['payload']['faces'][1]['material']==0
    diffs=[i for i,(a,b) in enumerate(zip(source.read_bytes(),target.read_bytes())) if a!=b]
    assert len(diffs)<=2


def test_unsafe_collision_material_not_remapped(fixture,tmp_path):
    # Make original material solid; invisible candidate is not.
    tool,game,map_dir,sha,source=fixture
    import struct
    from pt_asset_tool.stage072_corpus import DFILE_HEADER_SIZE, STAGE_HEADER_SIZE, MAT_GROUP_SIZE
    raw=bytearray(source.read_bytes())
    struct.pack_into('<I',raw,DFILE_HEADER_SIZE+STAGE_HEADER_SIZE+MAT_GROUP_SIZE+168,1)
    source.write_bytes(raw)
    with pytest.raises(ValueError,match='NO_SAFE_VISIBLE_FACE_CHANGES'):
        m1.patch_stage(source,{0},tmp_path/'x.smd',expected_sha=m1.file_sha(source),expected_faces=2)


def test_duplicate_group_face_rejected(fixture):
    tool,game,map_dir,sha,stage=fixture
    docs=[m1.read_json(m1.locate(map_dir,s)) for s in (
        '.v24_groups.json','.v24_groups.v26_environment.v30_full_preview.json','.v24_groups.v31_residuais.json')]
    docs[0]['groups'].append({'id':'def','faces':[0],'anchor_game':[1,0,3]})
    docs[1]['instance_group_ids'].append('def');docs[1]['instance_count']=2
    with pytest.raises(ValueError,match='DUPLICATED_GROUP_FACE'):
        m1.collect_selections(*docs,stage_sha=sha,face_count=2)


def test_plan_never_writes_game(fixture):
    tool,game,map_dir,sha,stage=fixture
    result=m1.prepare(tool,game,map_dir,expected_sha=sha,expected_faces=2)
    assert result['status']=='READY_FOR_STAGE_BUILD'
    assert result['game_assets_written'] is False
    assert m1.file_sha(stage)==sha


def test_real_pipeline_clone_commit_restore(fixture):
    tool,game,map_dir,sha,stage=fixture
    result=m1.clone_rehearsal(tool,game,map_dir=map_dir,expected_sha=sha,expected_faces=2)
    assert result['status']=='CLONE_MODIFIED_STAGE_COMMIT_ROLLBACK_PASS'
    assert result['output_sha256'] != sha
    assert result['clone_published_sha256']==result['output_sha256']
    assert result['clone_publish_state']=='APPLIED_VERIFIED'
    assert result['clone_restore_state']=='RESTORED_VERIFIED'
    assert m1.file_sha(stage)==sha


def test_real_game_publish_and_rollback_with_confirmation(fixture):
    tool,game,map_dir,sha,stage=fixture
    result=m1.clone_rehearsal(tool,game,map_dir=map_dir,expected_sha=sha,expected_faces=2)
    with pytest.raises(ValueError,match='CONFIRMATION_REQUIRED'):
        m1.real_publish(tool,game,confirmation='')
    pub=m1.real_publish(tool,game,confirmation=m1.APPLY_GAME_CONFIRM)
    assert pub['status']=='GAME_PUBLISHED_VERIFIED'
    assert m1.file_sha(stage)==result['output_sha256']
    with pytest.raises(ValueError,match='CONFIRMATION_REQUIRED'):
        m1.real_publish(tool,game,restore=True,confirmation='')
    restore=m1.real_publish(tool,game,restore=True,confirmation=m1.RESTORE_GAME_CONFIRM)
    assert restore['status']=='GAME_RESTORED_VERIFIED'
    assert m1.file_sha(stage)==sha
