from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PT=ROOT/'payload/pt_asset.py'


def run(*args):
    return subprocess.run([sys.executable,str(PT),*args],cwd=ROOT/'payload',text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=False)


def test_release_version_and_status():
    r=run('--version'); assert r.returncode==0 and r.stdout.strip()=='0.12.0'
    h=run('--help'); assert h.returncode==0 and 'compare trees' in h.stdout and 'monster-npc-census' in h.stdout and 'ui | gui' in h.stdout
    r=run('status'); assert r.returncode==1, r.stdout; assert json.loads(r.stdout)['status']=='WARN'
    d=json.loads(r.stdout)
    assert d['status']=='WARN'
    assert d['features']['gui'] and d['features']['tree_compare'] and d['features']['monster_npc_census']
    assert d['certified_writer_hashes_valid'] is True


def test_compare_trees_cli_route(tmp_path: Path):
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir(); (a/'x').write_text('1'); (b/'x').write_text('1')
    out=tmp_path/'cmp.json'
    r=run('compare','trees','--left',str(a),'--right',str(b),'--hash','--output',str(out))
    assert r.returncode==0,r.stdout
    assert 'tree_compare=PASS' in r.stdout
    assert json.loads(out.read_text())['summary']['same_sha256_count']==1


def test_gui_route_version():
    r=run('ui','--version'); assert r.returncode==0 and r.stdout.strip()=='0.12.0'


def test_config_routes(tmp_path: Path):
    client=tmp_path/'client'; client.mkdir()
    r=run('config','set-client-root',str(client)); assert r.returncode==0,r.stdout
    d=json.loads(r.stdout); assert d['client_root']==str(client.resolve())
    r=run('config','show'); assert r.returncode==0,r.stdout
    d=json.loads(r.stdout); assert d['resolved_client_root']==str(client.resolve()) and d['resolved_client_root_source']=='PERSISTENT_CONFIG'
    r=run('config','clear-client-root'); assert r.returncode==0,r.stdout
    # Cleanup test-local config created beside the payload wrapper.
    cfg=ROOT/'payload/pt_build/state/pt_asset_app_config.json'
    if cfg.exists(): cfg.unlink()


def test_smoke_route_with_persisted_client(tmp_path: Path):
    client=tmp_path/'client'; (client/'image').mkdir(parents=True); (client/'image/x.bmp').write_bytes(b'BMdemo')
    r=run('config','set-client-root',str(client)); assert r.returncode==0,r.stdout
    try:
        r=run('smoke'); assert r.returncode==0,r.stdout
        d=json.loads(r.stdout)
        assert d['status']=='PASS'
        assert d['checks']['catalog_bootstrap'] is True
        assert d['details']['catalog_file_count']==1
        assert d['client_modified'] is False
    finally:
        run('config','clear-client-root')
        cfg=ROOT/'payload/pt_build/state/pt_asset_app_config.json'
        if cfg.exists(): cfg.unlink()
