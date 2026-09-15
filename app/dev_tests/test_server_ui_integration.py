import json
from pathlib import Path

from pt_asset_tool.app_config import resolve_server_root, save_server_root
from pt_asset_tool.server_ui import build_server_ui_summary, server_report_rows


def test_server_root_persistent_config_and_home_discovery(monkeypatch, tmp_path):
    project = tmp_path / "app"; project.mkdir()
    configured = tmp_path / "Servidor"; configured.mkdir()
    save_server_root(project, configured)
    resolved, source = resolve_server_root(project)
    assert resolved == configured.resolve()
    assert source == "PERSISTENT_CONFIG"


def test_server_ui_summary_reads_pt_build_reports_and_keeps_writes_disabled(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "Servidor"; server.mkdir()
    report_dir = project / "pt_build" / "devtest" / "server_inventory"
    report_dir.mkdir(parents=True)
    (report_dir / "result.json").write_text(json.dumps({
        "status": "PASS", "total_files": 124900, "total_bytes": 123,
        "asset_candidate_files": 4000, "design_visible_files": 5000,
        "hard_excluded_files": 124823,
        "lifecycle_counts": {"LOG_FORENSICS_EXCLUDED": 124823},
        "layout_counts": {"INX_MODERN_172": 10},
    }), encoding="utf-8")
    integration_dir = project / "pt_build" / "devtest" / "integration_regression_auto"
    integration_dir.mkdir(parents=True)
    (integration_dir / "result.json").write_text(json.dumps({
        "status": "PASS", "integration_regression_ready": True,
        "required_failures": [], "next_gate": "PHYSICAL_REGRESSION_AUTO",
    }), encoding="utf-8")
    result = build_server_ui_summary(project, server, client)
    assert result["status"] == "READY"
    assert result["reports"]["inventory"]["hard_excluded_files"] == 124823
    assert result["reports"]["integration"]["integration_regression_ready"] is True
    assert result["safety"] == {
        "server_source_write": False,
        "persistence_write": False,
        "client_source_write": False,
        "outputs_only_under_pt_build": True,
    }
    assert any("Monster:" in row for row in result["bundle_model"])


def test_server_tab_and_endpoints_are_present_in_ui_source():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool" / "ui_static" / "index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool" / "ui_static" / "app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool" / "ui_app.py").read_text(encoding="utf-8")
    assert 'data-tab="server"' in html
    assert 'Summit Server / Asset Enrichment' in html
    assert 'Validar Client + Server' in html
    assert 'Gerar plano v9' in html
    assert 'Grafo de dependências v9' in html
    assert "runServerAnalysis('integration')" in js
    assert '/api/server' in js
    assert '/api/server/analyze' in js
    assert 'u.path == "/api/server/config"' in py
    assert 'u.path == "/api/server/analyze"' in py
    assert '"integration": ["validate", "integration-regression-auto"]' in py
    assert '"vendor_plan": ["audit", "enrichment-plan"]' in py
    assert '"vendor_graph": ["audit", "enrichment-graph"]' in py
    assert '--skip-client-scan' not in py.split('"vendor_graph":', 1)[1].split('}', 1)[0]

    assert 'id="generalCensusBtn"' in html
    assert 'id="generalCensusRows"' in html
    assert '/api/general-census?' in js
    assert 'u.path == "/api/contracts/analyze"' in py
    assert '"audit", "general-asset-census"' in py

    assert 'id="fieldOpenSpm"' in html
    assert 'id="fieldOpenSpp"' in html
    assert 'id="fieldOpenSpc"' in html
    assert '/api/server/field-editor?' in js
    assert '/api/server/field-editor/stage' in js
    assert 'path == "/api/server/field-editor"' in py
    assert 'u.path == "/api/server/field-editor/stage"' in py


def test_server_report_rows_filters_bundle_reports(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    report_dir = project / "pt_build" / "devtest" / "server_item_census"
    report_dir.mkdir(parents=True)
    (report_dir / "result.json").write_text(json.dumps({
        "status": "PASS",
        "status_counts": {"PASS": 1, "REVIEW": 1},
        "reason_counts": {"DUPLICATE_CODE": 1},
        "rows": [
            {"definition": "GameServer/OpenItem/WA001.txt", "code": "WA001", "status": "PASS", "reasons": []},
            {"definition": "GameServer/OpenItem/WA002.txt", "code": "WA002", "status": "REVIEW", "reasons": ["DUPLICATE_CODE"]},
        ],
    }), encoding="utf-8")
    result = server_report_rows(project, "items", query="wa002", status="REVIEW", reason="duplicate")
    assert result["status"] == "PASS"
    assert result["total_rows"] == 2
    assert result["filtered_rows"] == 1
    assert result["rows"][0]["code"] == "WA002"
    assert result["server_write_authorized"] is False
    assert result["client_write_authorized"] is False


def test_server_ui_contains_bundle_explorer_and_beginner_guides():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool" / "ui_static" / "index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool" / "ui_static" / "app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool" / "ui_app.py").read_text(encoding="utf-8")
    assert 'id="serverExplorerKind"' in html
    assert 'data-tab="docs"' in html
    assert 'Runbook recomendado' in html
    assert '/api/server/report?' in js
    assert 'renderServerRowDetail' in js
    assert 'path == "/api/server/report"' in py
