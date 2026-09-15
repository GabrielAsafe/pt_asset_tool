from __future__ import annotations
import json
from pathlib import Path
from pt_asset_tool.tree_compare import compare_trees, write_outputs


def test_tree_compare_hash_and_missing(tmp_path: Path):
    left=tmp_path/'left'; right=tmp_path/'right'; left.mkdir(); right.mkdir()
    (left/'same.bin').write_bytes(b'abc')
    (right/'same.bin').write_bytes(b'abc')
    (left/'same_size_diff.bin').write_bytes(b'111')
    (right/'same_size_diff.bin').write_bytes(b'222')
    (left/'size.bin').write_bytes(b'1')
    (right/'size.bin').write_bytes(b'22')
    (left/'only-left.bin').write_bytes(b'L')
    (right/'only-right.bin').write_bytes(b'R')
    r=compare_trees(left,right,content_hash=True)
    s=r['summary']
    assert r['read_only'] is True
    assert s['same_sha256_count']==1
    assert s['different_sha256_count']==1
    assert s['different_size_count']==1
    assert s['only_left_count']==1 and s['only_right_count']==1
    out=tmp_path/'result.json'; paths=write_outputs(r,out)
    assert Path(paths['json']).is_file() and Path(paths['csv']).is_file() and Path(paths['markdown']).is_file()
    assert json.loads(out.read_text())['format']=='PT_ASSET_TREE_COMPARE_V2'


def test_tree_compare_case_collision(tmp_path: Path):
    left=tmp_path/'left'; right=tmp_path/'right'; left.mkdir(); right.mkdir()
    (left/'A.txt').write_text('a'); (left/'a.txt').write_text('b'); (right/'A.txt').write_text('a')
    r=compare_trees(left,right,case_sensitive=False)
    assert r['summary']['left_case_collision_count']==1


def test_cli_refuses_output_inside_source_tree(tmp_path: Path):
    import subprocess, sys
    root=Path(__file__).resolve().parents[1]
    left=tmp_path/'left'; right=tmp_path/'right'; left.mkdir(); right.mkdir()
    (left/'x').write_text('x'); (right/'x').write_text('x')
    out=left/'result.json'
    cp=subprocess.run([sys.executable,str(root/'payload/pt_asset.py'),'compare','trees','--left',str(left),'--right',str(right),'--output',str(out)],cwd=root/'payload',text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    assert cp.returncode==2
    assert 'OUTPUT_INSIDE_SOURCE_TREE' in cp.stdout
    assert not out.exists()


def test_tree_compare_filters_and_differences_only(tmp_path: Path):
    left=tmp_path/'left'; right=tmp_path/'right'; left.mkdir(); right.mkdir()
    for root in (left,right):
        (root/'char/tmABCD').mkdir(parents=True)
        (root/'monster/ogre').mkdir(parents=True)
        (root/'image/interface').mkdir(parents=True)
    (left/'char/tmABCD/TfbF01.smd').write_bytes(b'AAA')
    (right/'char/tmABCD/TfbF01.smd').write_bytes(b'BBB')
    (left/'monster/ogre/a.smd').write_bytes(b'M')
    (right/'monster/ogre/a.smd').write_bytes(b'M')
    (left/'image/interface/panel.png').write_bytes(b'P')
    (right/'image/interface/panel.png').write_bytes(b'P')
    r=compare_trees(left,right,content_hash=True,extensions=['smd'],category='CHARACTER',differences_only=True)
    assert r['filters']['extensions']==['.smd']
    assert r['filters']['category']=='CHARACTER'
    assert r['summary']['left_file_count']==1 and r['summary']['right_file_count']==1
    assert r['summary']['different_sha256_count']==1
    assert r['summary']['displayed_row_count']==1
    assert r['rows'][0]['category']=='CHARACTER'


def test_tree_compare_path_and_glob_filters(tmp_path: Path):
    left=tmp_path/'left'; right=tmp_path/'right'; left.mkdir(); right.mkdir()
    for root in (left,right):
        (root/'char/tmABCD').mkdir(parents=True)
        (root/'char/other').mkdir(parents=True)
        (root/'char/tmABCD/a.smd').write_bytes(b'a')
        (root/'char/other/b.smd').write_bytes(b'b')
    r=compare_trees(left,right,path_contains='tmABCD',include_globs=['char/*'],exclude_globs=['*other*'])
    assert r['summary']['left_file_count']==1
    assert r['rows'][0]['left_path']=='char/tmABCD/a.smd'
