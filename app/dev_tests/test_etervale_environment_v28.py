"""V28 tests: hash cache, per-model isolated worker, Blender UI integration.

No Blender runtime is available in CI; tests simulate the worker protocol.
Real 5.2 Flatpak LOD generation must be verified on user machine.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile
import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from pt_asset_tool.environment_lods_v28 import (
    LOD_BUDGETS, FORMAT, RECIPE_VERSION, ROOT_REL, sha256_file,
    prepared_dir, validate_prepared, prepare_asset, _read_worker_report,
    MAX_SCENE_INSTANCES,
)


def project(tmp_path):
    root=tmp_path/'pt_asset_tool'
    (root/'AssetsForAutomaticSubstitution').mkdir(parents=True)
    (root/'app/pt_asset_tool/blender').mkdir(parents=True)
    (root/'app/pt_asset.py').write_text('')
    (root/'app/pt_asset_tool/blender/environment_prepare_worker_v28.py').write_text('# mock worker')
    (root/'app/pt_build/etervale/stage072_semantic_v21/maps').mkdir(parents=True)
    stage=root/'app/pt_build/etervale/stage072_semantic_v21/maps/test.v25_review.json'
    stage.write_text('{"sentinel": "untouched"}')
    asset=root/'AssetsForAutomaticSubstitution/island_tree_01_1k.blend.zip'
    with ZipFile(asset, 'w') as z:
        z.writestr('src/tree.blend', b'BLENDER-v280' + b'tree'*15)
        z.writestr('src/textures/leaf.png', b'IMG')
    return root, asset, stage


def fake_worker(cmd, **kwargs):
    assert '--background' in cmd and '--factory-startup' in cmd
    assert '--python' in cmd and '--python-exit-code' in cmd
    worker=Path(cmd[cmd.index('--python')+1])
    assert worker.name=='environment_prepare_worker_v28.py'
    out=Path(cmd[cmd.index('--output')+1])
    for lod in LOD_BUDGETS:
        (out/f'{lod}.blend').write_bytes(b'BLENDER-FAKE' + lod.encode()*10)
    result={'format':'PT_ETERVALE_LOD_WORKER_V28', 'source_vertices':3_700_000,
            'source_faces':6_500_000, 'mesh_parts':3, 'height':7.3,
            'missing_textures':[], 'levels':{
                'LOD0':{'faces':110_000,'vertices':150_000},
                'LOD1':{'faces':32_000,'vertices':45_000},
                'LOD2':{'faces':6_700,'vertices':9_000}}}
    (out/'worker_result.json').write_text(json.dumps(result))
    return subprocess.CompletedProcess(cmd, 0, 'PT_V28_WORKER=PASS')


def test_prepared_three_lods_without_changing_source_or_stage(tmp_path, monkeypatch):
    root, source, stage=project(tmp_path)
    src_sha=sha256_file(source)
    stage_bytes=stage.read_bytes()
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run', fake_worker)
    result=prepare_asset(name=source.name,project_root=root,blender='blender')
    assert result['status']=='PREPARADO'
    assert result['source_vertices']==3_700_000  # over previous hard cutoff
    assert sha256_file(source)==src_sha and stage.read_bytes()==stage_bytes
    for level in LOD_BUDGETS:
        path, doc=validate_prepared(root / ROOT_REL,source,level)
        assert path.name==f'{level}.blend' and path.is_file()
        assert doc['source_sha256']==src_sha
        assert doc['publish_enabled'] is False
        assert doc['game_assets_modified'] is False
        assert doc['runtime_certified'] is False
    assert not any(p.name.startswith('.v28_prepare_') for p in (root / ROOT_REL).iterdir())


def test_second_run_skips_worker_and_existing_cache_is_immutable(tmp_path,monkeypatch):
    root,source,_=project(tmp_path)
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run',fake_worker)
    first=prepare_asset(name=source.name,project_root=root,blender='blender')
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run',
                        lambda *a,**k: pytest.fail('worker rerun'))
    again=prepare_asset(name=source.name,project_root=root,blender='blender')
    assert again['status']=='JA_PREPARADO'
    assert again['path']==first['path']


def test_sha_guard_blocks_mutated_lod_and_preserves_cache(tmp_path,monkeypatch):
    root,source,_=project(tmp_path)
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run',fake_worker)
    prepare_asset(name=source.name,project_root=root,blender='blender')
    out,_=validate_prepared(root/ROOT_REL,source,'LOD0')
    out.write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA256_INVALIDO'):
        validate_prepared(root/ROOT_REL,source,'LOD0')
    with pytest.raises(ValueError,match='SHA256_INVALIDO'):
        prepare_asset(name=source.name,project_root=root,blender='blender')
    assert out.read_bytes()==b'changed'  # never auto-overwrite corrupted data


def test_changed_source_gets_new_hash_and_original_cache_is_preserved(tmp_path,monkeypatch):
    root,source,_=project(tmp_path)
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run',fake_worker)
    first=prepare_asset(name=source.name,project_root=root,blender='blender')
    with source.open('ab') as f: f.write(b'changed after first build')
    with pytest.raises(FileNotFoundError,match='NAO_PREPARADO'):
        validate_prepared(root/ROOT_REL,source,'LOD1')
    second=prepare_asset(name=source.name,project_root=root,blender='blender')
    assert second['path'] != first['path']
    assert Path(first['path']).exists()


def test_model_filter_disallows_bark_material(tmp_path):
    root,source,_=project(tmp_path)
    with pytest.raises(ValueError,match='NAO_E_ARVORE'):
        prepare_asset(name='tree_bark_03_1k.blend.zip',project_root=root,
                      blender='blender',dry_run=True)


def test_dry_run_writes_nothing(tmp_path):
    root,source,_=project(tmp_path)
    result=prepare_asset(name=source.name,project_root=root,
                         blender='flatpak run org.blender.Blender',dry_run=True)
    assert result['status']=='DRY_RUN'
    assert result['blender_command']==['flatpak','run','org.blender.Blender']
    assert not (root/ROOT_REL).exists()


def test_worker_failure_leaves_no_partial_cache(tmp_path,monkeypatch):
    root,source,_=project(tmp_path)
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run',
        lambda cmd,**kw: subprocess.CompletedProcess(cmd,13,'Blender failed'))
    with pytest.raises(RuntimeError,match='WORKER_FAIL'):
        prepare_asset(name=source.name,project_root=root,blender='blender')
    assert (root/ROOT_REL).is_dir()
    assert not list((root/ROOT_REL).iterdir())


def test_worker_excessive_mesh_report_rejected(tmp_path,monkeypatch):
    root,source,_=project(tmp_path)
    def corrupt(cmd,**kw):
        r=fake_worker(cmd,**kw)
        out=Path(cmd[cmd.index('--output')+1])
        doc=json.loads((out/'worker_result.json').read_text())
        doc['levels']['LOD2']['faces']=999_999
        (out/'worker_result.json').write_text(json.dumps(doc))
        return r
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run',corrupt)
    with pytest.raises(ValueError,match='LOD_INVALIDO'):
        prepare_asset(name=source.name,project_root=root,blender='blender')
    assert not list((root/ROOT_REL).iterdir())


def test_manifest_rejects_wrong_level_name(tmp_path,monkeypatch):
    root,source,_=project(tmp_path)
    monkeypatch.setattr('pt_asset_tool.environment_lods_v28.subprocess.run',fake_worker)
    prepare_asset(name=source.name,project_root=root,blender='blender')
    marker=prepared_dir(root/ROOT_REL,sha256_file(source))/'manifest.json'
    doc=json.loads(marker.read_text())
    doc['levels']['LOD1']['file']='../../escape.blend'
    marker.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='MANIFESTO_INVALIDO'):
        validate_prepared(root/ROOT_REL,source,'LOD1')


def test_ui_is_bounded_and_uses_instances_only():
    env=(APP/'pt_asset_tool/blender/stage072_environment_v26.py').read_text()
    worker=(APP/'pt_asset_tool/blender/environment_prepare_worker_v28.py').read_text()
    launcher=(APP/'pt_environment.py').read_text()
    assert 'validate_prepared' in env and '_loaded_prepared' in env
    assert "ob.instance_type = 'COLLECTION'" in env
    assert 'MAX_SCENE_INSTANCES' in env
    assert 'pt_env.v28_preview_batch' in env
    assert 'pt_v28_lod' in env
    assert "linked=False" in env
    assert '--prepare-model' in launcher and '--prepare-all-models' in launcher
    assert 'bpy.data.libraries.write' in worker
    assert 'bpy.ops.wm.open_mainfile' not in worker
    assert 'bpy.ops.wm.save_as_mainfile' not in worker
    assert 'export_scene' not in worker


def test_lod_and_instance_budgets_are_bounded():
    assert LOD_BUDGETS['LOD2'] < LOD_BUDGETS['LOD1'] < LOD_BUDGETS['LOD0'] < 200000
    assert MAX_SCENE_INSTANCES <= 100
    assert RECIPE_VERSION>=1
    assert FORMAT.startswith('PT_ETERVALE_')
