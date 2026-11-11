"""V28.1 regression: adaptive LOD budget and backward-compatible cache.

The user-observed Blender failure was LOD0=190310, budget=120000. The real
Blender 5.2 operation must be repeated on the user's model; pure tests cannot
certify Blender Decimate behavior on that mesh.
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
from pt_asset_tool.lod_planning_v28_1 import (
    MAX_PASSES, MIN_REDUCIBLE_FACES, choose_collapse_ratio, assess_lod,
)
from pt_asset_tool.environment_lods_v28 import (
    _read_worker_report, build_manifest, FORMAT, LOD_BUDGETS,
    ROOT_REL, prepare_asset, sha256_file, validate_prepared,
)


def test_reproducer_190310_faces_generates_second_pass():
    ratio=choose_collapse_ratio(190310,120000,1)
    assert 0.4 < ratio < 0.65
    # Observed V28 Blender output overshot the expected per-mesh ratio by
    # a factor around 1.59; recomputing against output should converge.
    estimate=int(190310 * ratio * 1.59)
    assert estimate < 180000
    assert estimate < 190310


def test_adaptive_ratio_iteration_on_uneven_decimation():
    budget=120000
    faces=1_250_000
    for step in range(MAX_PASSES):
        ratio=choose_collapse_ratio(faces,budget,step)
        # Simulated modifier output differs by 50% due to mixed topology;
        # this is why the old single pass was incorrect.
        faces=max(5_000, round(faces*ratio*1.5))
        if faces<=budget:
            break
    assert assess_lod(faces,budget) in {'WITHIN_BUDGET','OVER_TARGET_REVIEW'}


def test_small_components_remain_protected():
    assert MIN_REDUCIBLE_FACES >= 4
    assert choose_collapse_ratio(60,120,0)==1.0
    assert choose_collapse_ratio(1_000_000,7_000,0)>=0.00005
    assert choose_collapse_ratio(200000,120000,4)<choose_collapse_ratio(200000,120000,0)


@pytest.mark.parametrize('value,target,status', [
    (120000,120000,'WITHIN_BUDGET'),
    (130000,120000,'OVER_TARGET_REVIEW'),
    (180000,120000,'OVER_TARGET_REVIEW'),
    (190310,120000,'REJECT'),
    (0,120000,'REJECT'),
])
def test_strict_safety_limits(value,target,status):
    assert assess_lod(value,target)==status


@pytest.mark.parametrize('bad',(0,-1,1.5,'3'))
def test_invalid_face_counts(bad):
    with pytest.raises(ValueError):
        choose_collapse_ratio(bad,120000,0)


def _report(quality=True):
    levels={}
    for name,budget in LOD_BUDGETS.items():
        faces=int(budget*1.18) if name=='LOD0' else budget-12
        levels[name]={'faces':faces,'vertices':faces*2,'passes':2}
        if quality:
            levels[name]['quality']=assess_lod(faces,budget)
    return {'format':'PT_ETERVALE_LOD_WORKER_V28',
            'source_vertices':2_000_000,'source_faces':2_800_000,
            'mesh_parts':3,'height':4.5,'missing_textures':[],
            'levels':levels}


def test_report_accepts_bounded_over_target_and_rejects_quality_mismatch(tmp_path):
    marker=tmp_path/'worker.json'
    marker.write_text(json.dumps(_report()))
    assert _read_worker_report(marker)['levels']['LOD0']['quality']=='OVER_TARGET_REVIEW'
    doc=_report()
    doc['levels']['LOD0']['quality']='WITHIN_BUDGET'
    marker.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='QUALITY_INCONSISTENTE'):
        _read_worker_report(marker)


def test_report_rejects_excessive_pass_count(tmp_path):
    marker=tmp_path/'worker.json'
    doc=_report()
    doc['levels']['LOD0']['passes']=MAX_PASSES+1
    marker.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='PASSAGENS_INVALIDAS'):
        _read_worker_report(marker)


def test_manifest_saves_quality_and_cache_retains_it(tmp_path):
    root=tmp_path/'project'
    library=root/'AssetsForAutomaticSubstitution'
    library.mkdir(parents=True)
    tree=library/'island_tree_01_1k.blend.zip'
    with ZipFile(tree,'w') as z:
        z.writestr('src/tree.blend', b'BLENDER-v280'+b'tree'*15)
        z.writestr('src/textures/leaf.png', b'IMG')
    (root/'app/pt_asset_tool/blender').mkdir(parents=True)
    (root/'app/pt_asset_tool/blender/environment_prepare_worker_v28.py').write_text('# mock')
    staging=tmp_path/'staging'
    staging.mkdir()
    for lod in LOD_BUDGETS:
        (staging/f'{lod}.blend').write_bytes(b'FAKE-BLEND'+lod.encode())
    result=_report()
    data=build_manifest(source=tree,source_sha=sha256_file(tree),worker_result=result,staged_dir=staging)
    assert data['levels']['LOD0']['quality']=='OVER_TARGET_REVIEW'
    assert data['levels']['LOD0']['passes']==2
    assert data['game_assets_modified'] is False
    cache=root/ROOT_REL/(sha256_file(tree)+'-r1')
    cache.parent.mkdir(parents=True)
    staging.rename(cache)
    (cache/'manifest.json').write_text(json.dumps(data))
    _,checked=validate_prepared(root/ROOT_REL,tree,'LOD0')
    assert checked['levels']['LOD0']['quality']=='OVER_TARGET_REVIEW'
    # A V28-valid cache lacking the optional new metadata stays valid.
    data['levels']['LOD0'].pop('quality')
    data['levels']['LOD0'].pop('passes')
    (cache/'manifest.json').write_text(json.dumps(data))
    validate_prepared(root/ROOT_REL,tree,'LOD0')


def test_worker_uses_adaptive_passes_and_no_source_scene_writes():
    script=(APP/'pt_asset_tool/blender/environment_prepare_worker_v28.py').read_text()
    assert 'choose_collapse_ratio(current_faces, budget, passes)' in script
    assert 'while current_faces > budget and passes < MAX_PASSES' in script
    assert '_collapse_copy(obj, ratio, depsgraph)' in script
    assert 'preserve_all_data_layers=True' in script
    assert 'NAO_APAGAR_FOLHAS_OU_TRONCO_SEM_REVISAO' in script
    assert 'bpy.data.libraries.write' in script
    assert 'bpy.ops.wm.open_mainfile' not in script
    assert 'bpy.ops.wm.save_as_mainfile' not in script
    assert 'bpy.ops.export_scene' not in script
