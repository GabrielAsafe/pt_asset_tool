from __future__ import annotations

from pathlib import Path

from pt_asset_tool.legacy_authoring import authoring_workspace_guide
from pt_asset_tool.legacy_management_web import legacy_management_dashboard


def test_authoring_workspace_guide_is_task_oriented(tmp_path):
    server = tmp_path / "server"; server.mkdir()
    client = tmp_path / "client"; client.mkdir()
    guide = authoring_workspace_guide(server_root=server, client_root=client)
    assert guide["status"] == "PASS"
    assert guide["legacy_executable_required"] is False
    assert set(guide["domains"]) == {"ITEM", "MONSTER", "NPC", "MAP"}
    item = guide["domains"]["ITEM"]
    assert item["required_fields"] == ["name", "code"]
    assert item["create_scope"] == "OPENITEM_FOR_EXISTING_RUNTIME_CODE"
    assert "sITEM" in item["hard_block"]
    monster = guide["domains"]["MONSTER"]
    assert monster["required_fields"] == ["name", "model_file"]
    field = guide["domains"]["MAP"]
    assert set(field["subtypes"]) == {"SPM", "SPP", "SPC"}


def test_legacy_dashboard_reports_python_replacement_status(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    dashboard = legacy_management_dashboard(project)
    rows = {x["tool"]: x for x in dashboard["replacement_matrix"]}
    assert rows["NPCManager.exe"]["status"] == "PORTED"
    assert rows["Editor de Itens.exe"]["status"] == "PORTED_BETTER"
    assert rows["ItemDistributor.exe"]["status"] == "PORTED"
    assert rows["ControllerUser.exe"]["status"] == "PORTED_SAFE_PLUS_EXPERT_ABI_AND_INVENTORY_ADMIN"
    assert rows["Level Editor.exe"]["status"] == "PORTED_WITH_AUDITED_GAME_TABLE"
    assert rows["MudarNome.exe"]["status"] == "PORTED_SAFE"


def test_legacy_ui_exposes_task_tabs_and_demotes_historical_tools():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    assert 'data-legacy-task="item"' in html
    assert 'data-legacy-task="monster"' in html
    assert 'data-legacy-task="npc"' in html
    assert 'data-legacy-task="map"' in html
    assert 'data-legacy-task="world"' in html
    assert 'data-legacy-task="evidence"' not in html
    assert "legacy executables are evidence only" in html.casefold()
    assert 'id="legacyReplacementMatrix"' not in html
    assert "/api/legacy-authoring/guide" in js
    assert "openLegacyAuthoring" in js
    assert "openLegacyWorld" in js


def test_management_hash_verification_is_not_part_of_operator_workspace():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    assert 'id="legacyVerifyResult"' not in html
    assert "verifyLegacyManagement" not in js
    # The low-level provenance endpoint remains available for engineering/audit.
    assert 'u.path == "/api/legacy-management/verify"' in py


def test_character_account_ui_exposes_explicit_account_graph_migration_not_magic_dataserver1():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    assert 'id="legacyAccountCopySourceRoot"' in html
    assert 'id="legacyAccountCopyAllowReplace"' in html
    assert 'id="legacyAccountCopyPlanBtn"' in html
    assert "Replaces the button <code>Copy</code>" in html
    assert "ACCOUNT_GRAPH_COPY" in js
    assert "source_server_root" in js
