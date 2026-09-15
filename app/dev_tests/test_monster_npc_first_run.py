from __future__ import annotations

from pathlib import Path

from pt_asset_tool import monster_npc_census as m


def test_refresh_census_routes_client_root_after_consolidated_command(monkeypatch, tmp_path: Path):
    seen = {}
    class CP:
        returncode = 0
    def fake_run(cmd, cwd, text):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        return CP()
    monkeypatch.setattr(m.subprocess, "run", fake_run)
    project = tmp_path / "p"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    census = project / "pt_build" / "semantic_asset_census_current.json"
    m.refresh_census(project, census, client)
    assert seen["cmd"][2:4] == ["audit", "semantic-asset-census"]
    assert seen["cmd"][4:6] == ["--client-root", str(client)]
    assert "--output" in seen["cmd"]
