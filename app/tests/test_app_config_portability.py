from __future__ import annotations

import pathlib

from pt_asset_tool.app_config import discover_client_root, load_config, save_client_root


def test_sibling_summit_layout_is_discovered(tmp_path: pathlib.Path):
    project = tmp_path / "design_work"
    client = tmp_path / "summit" / "Summit Tale Client Full" / "cliente"
    project.mkdir()
    client.mkdir(parents=True)
    assert discover_client_root(project) == client.resolve()


def test_persistent_client_root_overrides_layout(tmp_path: pathlib.Path):
    project = tmp_path / "design_work"
    client = tmp_path / "external_client"
    project.mkdir()
    client.mkdir()
    path = save_client_root(project, client)
    assert path == project.resolve() / "pt_build" / "state" / "pt_asset_app_config.json"
    assert load_config(project)["client_root"] == str(client.resolve())
    assert discover_client_root(project) == client.resolve()


def test_resolution_source_and_clear(tmp_path: pathlib.Path):
    from pt_asset_tool.app_config import clear_client_root, resolve_client_root
    project=tmp_path/'design_work'; configured=tmp_path/'configured'; sibling=tmp_path/'summit'/'Summit Tale Client Full'/'cliente'
    project.mkdir(); configured.mkdir(); sibling.mkdir(parents=True)
    save_client_root(project, configured)
    path, source=resolve_client_root(project)
    assert path==configured.resolve() and source=='PERSISTENT_CONFIG'
    clear_client_root(project)
    path, source=resolve_client_root(project)
    assert path==sibling.resolve() and source=='SIBLING_SUMMIT_LAYOUT'


def test_env_client_root_has_highest_priority(tmp_path: pathlib.Path, monkeypatch):
    from pt_asset_tool.app_config import resolve_client_root
    project=tmp_path/'design_work'; configured=tmp_path/'configured'; envroot=tmp_path/'envroot'
    project.mkdir(); configured.mkdir(); envroot.mkdir()
    save_client_root(project, configured)
    monkeypatch.setenv('PT_CLIENT_ROOT',str(envroot))
    path, source=resolve_client_root(project)
    assert path==envroot.resolve() and source=='PT_CLIENT_ROOT'
