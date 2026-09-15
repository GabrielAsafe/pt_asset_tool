from pathlib import Path

from pt_asset_tool.app_config import resolve_client_root


def test_app_discovery_keeps_historical_home_desktop_layout_consistent_with_settings(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "transfer" / "app"
    project.mkdir(parents=True)
    client = home / "Área de Trabalho" / "summit" / "Summit Tale Client Full" / "cliente"
    client.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    resolved, source = resolve_client_root(project)
    assert resolved == client.resolve()
    assert source == "LEGACY_HOME_DESKTOP_LAYOUT"
