from pathlib import Path

from pt_asset_tool.app_config import resolve_client_root


def test_app_discovery_uses_portable_workspace_layout(tmp_path):
    project = tmp_path / "workspace" / "pt_asset_tool" / "app"
    client = tmp_path / "workspace" / "client"
    project.mkdir(parents=True)
    client.mkdir(parents=True)
    resolved, source = resolve_client_root(project)
    assert resolved == client.resolve()
    assert source == "WORKSPACE_CLIENT_DIR"


def test_app_discovery_does_not_guess_developer_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "isolated" / "app"
    project.mkdir(parents=True)
    legacy = home / "Área de Trabalho" / "summit" / "Summit Tale Client Full" / "cliente"
    legacy.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    try:
        resolve_client_root(project)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("fresh install must not infer a developer-specific HOME path")
