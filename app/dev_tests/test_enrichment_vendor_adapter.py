import json
import pathlib
import subprocess

import pt_asset_tool.enrichment_vendor_adapter as adapter


def _fixture(tmp_path):
    pkg = tmp_path / "package"
    project = pkg / "app"
    vendor = pkg / "vendor" / "summit_asset_enrichment_v9"
    client = tmp_path / "client"
    server = tmp_path / "server"
    donor = tmp_path / "donor"
    project.mkdir(parents=True); vendor.mkdir(parents=True); client.mkdir(); server.mkdir(); donor.mkdir()
    (vendor / "PACKAGE_MANIFEST.json").write_text(json.dumps({"version": "v9-fix136", "files": []}), encoding="utf-8")
    (vendor / "summit_paths.json").write_text(json.dumps({
        "target_client": "/stale/client",
        "target_server": "/stale/server",
        "donors": [
            {"label": "live", "side": "client", "root": str(donor), "priority": 1},
            {"label": "missing", "side": "server", "root": str(tmp_path / "missing"), "priority": 2},
        ],
    }), encoding="utf-8")
    (vendor / "migrate_assets.py").write_text("# fixture\n", encoding="utf-8")
    (vendor / "build_dependency_graph.py").write_text("# fixture\n", encoding="utf-8")
    state = project / "pt_build" / "state"
    state.mkdir(parents=True)
    (state / "pt_asset_app_config.json").write_text(json.dumps({
        "format": "PT_ASSET_APP_CONFIG_V1",
        "contract_donor_clients": [{"label": "LIVE", "path": str(donor)}],
        "contract_donor_servers": [{"label": "MISSING", "path": str(tmp_path / "missing")}],
    }), encoding="utf-8")
    return project, client, server, donor


def test_enrichment_plan_uses_current_roots_filters_missing_donors_and_stays_under_pt_build(monkeypatch, tmp_path):
    project, client, server, donor = _fixture(tmp_path)

    def fake_run(cmd, **kwargs):
        out = pathlib.Path(cmd[cmd.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("status,path\nAUTO,x\n", encoding="utf-8")
        out.with_suffix(".summary.json").write_text(json.dumps({"AUTO": 1}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(adapter, "_run", fake_run)
    result = adapter.generate_migration_plan(project, client, server)
    assert result["status"] == "PASS"
    assert result["available_donor_count"] == 1
    assert result["unavailable_donor_count"] == 1
    cfg = json.loads(pathlib.Path(result["config"]).read_text(encoding="utf-8"))
    assert cfg["target_client"] == str(client.resolve())
    assert cfg["target_server"] == str(server.resolve())
    assert cfg["donors"][0]["root"] == str(donor.resolve())
    assert project / "pt_build" in pathlib.Path(result["manifest"]).parents
    assert result["client_write_authorized"] is False
    assert result["server_write_authorized"] is False


def test_enrichment_graph_is_read_only_and_reports_graph_summary(monkeypatch, tmp_path):
    project, client, server, donor = _fixture(tmp_path)

    def fake_run(cmd, **kwargs):
        out = pathlib.Path(cmd[cmd.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps({"nodes": 10, "edges": 12}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(adapter, "_run", fake_run)
    result = adapter.build_dependency_graph(project, client, server, skip_client_scan=True)
    assert result["status"] == "PASS"
    assert result["summary_data"] == {"nodes": 10, "edges": 12}
    assert result["skip_client_scan"] is True
    assert result["production_authorized"] is False
