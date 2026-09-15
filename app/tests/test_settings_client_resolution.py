from __future__ import annotations
import pathlib
from pt_asset_tool.app_config import save_client_root
from pt_asset_tool.config import Settings


def test_core_settings_uses_persistent_client_root(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.delenv('PT_CLIENT_ROOT',raising=False)
    project=tmp_path/'design_work'; client=tmp_path/'client'; project.mkdir(); client.mkdir()
    save_client_root(project,client)
    s=Settings.discover(project_root=project)
    assert s.client_root==client.resolve()


def test_explicit_core_client_root_still_wins(tmp_path: pathlib.Path):
    project=tmp_path/'design_work'; configured=tmp_path/'configured'; explicit=tmp_path/'explicit'
    project.mkdir(); configured.mkdir(); explicit.mkdir()
    save_client_root(project,configured)
    s=Settings.discover(project_root=project,client_root=explicit)
    assert s.client_root==explicit.resolve()
