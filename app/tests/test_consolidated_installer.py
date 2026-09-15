from __future__ import annotations
import hashlib, json, pathlib, subprocess
import pytest

ROOT=pathlib.Path(__file__).resolve().parents[1]
WRITERS={
 'pt_asset_tool/rare_rigid_edit.py':'229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42',
 'pt_asset_tool/rare_rigid_multivertex.py':'0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991',
 'pt_asset_tool/rare_rigid_multibone_bridge.py':'010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0',
 'pt_asset_tool/rare_rigid_normal_bridge.py':'67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96',
}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def test_consolidated_install_closes_hashes_and_ui(tmp_path: pathlib.Path):
    if not (ROOT/'install.sh').is_file():
        pytest.skip('standalone audited runtime intentionally removed the historical overlay installer')
    target=tmp_path/'design_work'; target.mkdir(); (target/'pt_build').mkdir()
    r=subprocess.run([str(ROOT/'install.sh'),str(target)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=False)
    assert r.returncode==0,r.stdout
    assert 'installed_release=0.12.0' in r.stdout
    assert 'ui_merged=true' in r.stdout and 'monster_npc_merged=true' in r.stdout and 'tree_compare_merged=true' in r.stdout
    assert (target/'pt_asset_gui.py').is_file() and (target/'pt_asset_tool/ui_static/index.html').is_file()
    assert (target/'pt_asset_tool/monster_npc_census.py').is_file() and (target/'pt_asset_tool/tree_compare.py').is_file()
    for rel,h in WRITERS.items(): assert sha(target/rel)==h
