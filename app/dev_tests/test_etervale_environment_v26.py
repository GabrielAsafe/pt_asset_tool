from pathlib import Path
import importlib.util
import io
import json
import os
import stat
import sys
from zipfile import ZipFile, ZipInfo
import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from pt_asset_tool.environment_library_v26 import (
    classify_name, scan_library, inventory, prepare_model, find_model_archive_blend,
)


def _archive(where: Path, entries: dict):
    with ZipFile(where, 'w') as z:
        for n, b in entries.items():
            z.writestr(n, b)


def test_inventory_user_34_assets(tmp_path):
    library = tmp_path/'AssetsForAutomaticSubstitution'
    library.mkdir()
    for n in ('island_tree_01_1k.blend.zip', 'island_tree_02_1k.blend.zip',
              'pine_sapling_medium_1k.blend.zip', 'boulder_01_1k.blend.zip',
              'bark_willow_1k.blend.zip','goegap_2k.exr','PavingStones036_1K-JPG.zip'):
        (library/n).write_bytes(b'not_opened')
    entries=scan_library(library)
    assert len(entries)==7
    assert len([x for x in entries if x.kind=='ARVORE' and x.ready])==3
    assert len([x for x in entries if x.kind=='PEDRA' and x.ready])==1
    assert len([x for x in entries if x.kind=='MATERIAL' and not x.ready])==3
    assert inventory(library)['model_candidates']==4


def test_safe_unpack_blend_archive_and_cache(tmp_path):
    root=tmp_path/'assets'; root.mkdir()
    p=root/'island_tree_01_1k.blend.zip'
    _archive(p, {'tree/tree.blend':b'BLENDER-v5 model', 'tree/textures/diffuse.png':b'PNG'})
    assert find_model_archive_blend(p) == 'tree/tree.blend'
    result=prepare_model(p,root,tmp_path/'cache')
    assert result.read_bytes()==b'BLENDER-v5 model'
    assert result.parent.joinpath('textures/diffuse.png').read_bytes()==b'PNG'
    assert prepare_model(p,root,tmp_path/'cache')==result
    assert p.read_bytes()


@pytest.mark.parametrize('entry', ('../escape.blend','/absolute.blend',
                                    'C:/bad.blend','a\\b.blend'))
def test_zip_traversal_rejected(tmp_path, entry):
    root=tmp_path/'assets'; root.mkdir()
    p=root/'island_tree_01_1k.blend.zip'
    _archive(p,{entry:b'BLENDER'})
    with pytest.raises(ValueError):
        prepare_model(p,root,tmp_path/'cache')
    assert not (tmp_path/'escape.blend').exists()


def test_zip_symlink_rejected(tmp_path):
    root=tmp_path/'assets'; root.mkdir()
    p=root/'island_tree_01_1k.blend.zip'
    with ZipFile(p,'w') as z:
        symlink = ZipInfo('path.blend')
        symlink.create_system=3
        symlink.external_attr=(stat.S_IFLNK | 0o777)<<16
        z.writestr(symlink, b'../../etc/passwd')
    with pytest.raises(ValueError, match='SYMLINK'):
        prepare_model(p,root,tmp_path/'cache')


def test_ambiguous_blend_rejected(tmp_path):
    root=tmp_path/'assets'; root.mkdir()
    p=root/'island_tree_01_1k.blend.zip'
    _archive(p,{'a.blend':b'BLENDER','b.blend':b'BLENDER'})
    with pytest.raises(ValueError,match='AMBIGUO'):
        prepare_model(p,root,tmp_path/'cache')


def test_library_file_cannot_be_symlink(tmp_path):
    root=tmp_path/'assets'; root.mkdir()
    elsewhere=tmp_path/'secret'; elsewhere.write_bytes(b'BLENDER')
    (root/'island_tree_01_1k.blend').symlink_to(elsewhere)
    assert scan_library(root)==[]
    with pytest.raises(ValueError,match='LINK'):
        prepare_model(root/'island_tree_01_1k.blend',root,tmp_path/'cache')


def test_ui_one_panel_legacy_kept_in_code():
    source=(APP/'pt_asset_tool/blender/stage072_semantic_paint.py').read_text()
    assert 'LEGACY_PANELS' in source
    assert 'if cls not in LEGACY_PANELS' in source
    assert 'env_v26.configure()' in source
    env=(APP/'pt_asset_tool/blender/stage072_environment_v26.py').read_text()
    assert 'class PT_PT_EnvironmentV26' in env
    assert 'PT_V26_ARVORE_EM_INSPECAO' in env
    assert 'publish_enabled' in env
    assert 'def _assert_native_hidden' in env
    assert 'bpy.ops.wm.save_as_mainfile' not in env
    assert 'bpy.ops.export_scene' not in env


def test_new_launcher_reuses_original_lifecycle():
    launcher=(APP/'pt_environment.py').read_text()
    assert 'from pt_stage072_semantic_paint import main as original_main' in launcher
    assert "--inventory" in launcher
    assert 'subprocess.run' not in launcher


def test_py_compile():
    import py_compile
    for rel in ('pt_asset_tool/blender/stage072_environment_v26.py',
                'pt_asset_tool/blender/stage072_semantic_paint.py',
                'pt_asset_tool/environment_library_v26.py',
                'pt_environment.py'):
        py_compile.compile(str(APP/rel),doraise=True)
