from __future__ import annotations

import json
from pathlib import Path

from pt_asset_tool.legacy_management_web import (
    legacy_management_dashboard,
    legacy_management_item_detail,
    query_legacy_management_report,
)
from pt_asset_tool.resolver import ClientResolver


def test_legacy_web_dashboard_exposes_contract_and_safety(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = legacy_management_dashboard(project)
    assert result["status"] == "PASS"
    assert result["legacy_contract"]["tool_count"] >= 10
    assert result["capabilities"]["item_lookup"] is True
    assert result["capabilities"]["runtime_item_writer_authorized"] is False
    assert result["capabilities"]["legacy_exe_execution"] is False


def test_legacy_web_item_lookup_closes_source_paths_against_client(tmp_path):
    client = tmp_path / "client"
    icon = client / "image/Sinimage/Items/Weapon/itWA121.bmp"
    drop = client / "image/Sinimage/Items/DropItem/itWA121.ASE"
    icon.parent.mkdir(parents=True)
    drop.parent.mkdir(parents=True)
    icon.write_bytes(b"BM")
    drop.write_text("*3DSMAX_ASCIIEXPORT", encoding="ascii")
    result = legacy_management_item_detail("WA121", resolver=ClientResolver(client))
    assert result["status"] == "PASS"
    assert result["runtime_item_contract"]["status"] == "SOURCE_VERIFIED"
    assert result["legacy"]["category"] == "Axe"
    physical = result["physical_client_closure"][0]
    assert physical["inventory_icon"]["status"] == "PRESENT"
    assert physical["drop_model_ase"]["status"] == "PRESENT"
    assert result["writer_authorized"] is False


def test_legacy_web_report_query_normalizes_world_statuses(tmp_path):
    project = tmp_path / "project"
    out = project / "pt_build/devtest/legacy_management"
    out.mkdir(parents=True)
    (out / "result.json").write_text(json.dumps({
        "status": "PASS",
        "server_evidence": {
            "maps": [
                {"spm": "GameServer/Field/town.spm", "actors": [{"name": "A", "status": "RESOLVED"}], "actor_count": 1, "item_codes": ["WA121"]},
                {"spm": "GameServer/Field/bad.spm", "actors": [{"name": "B", "status": "UNRESOLVED"}], "actor_count": 1, "item_codes": []},
            ],
            "definitions": [
                {"kind": "MONSTER", "definition": "GameServer/Monster/A.inf", "item_references": [{"code": "WA121", "openitem_definition_present": True}], "item_reference_count": 1, "zhoon_references": [], "reasons": [], "error": None},
                {"kind": "NPC", "definition": "GameServer/NPC/B.npc", "item_references": [{"code": "WA999", "openitem_definition_present": False}], "item_reference_count": 1, "zhoon_references": [], "reasons": [], "error": None},
            ],
        },
        "client_item_visual_evidence": {"rows": [{"code": "WA121", "status": "CLOSED", "closures": []}]},
    }), encoding="utf-8")
    maps = query_legacy_management_report(project, section="maps", status="UNRESOLVED")
    assert maps["filtered_rows"] == 1 and maps["rows"][0]["spm"].endswith("bad.spm")
    defs = query_legacy_management_report(project, section="definitions", status="REVIEW")
    assert defs["filtered_rows"] == 1 and defs["rows"][0]["kind"] == "NPC"
    items = query_legacy_management_report(project, section="items", query="WA121")
    assert items["filtered_rows"] == 1


def test_legacy_management_web_surface_is_wired_into_ui_sources():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    assert 'data-tab="legacy"' in html
    assert 'id="tab-legacy"' in html
    assert 'Item Runtime / OpenItem / DorpItem' in html
    assert 'World Closure Explorer' in html
    assert '/api/legacy-management/item?' in js
    assert '/api/legacy-management/report?' in js
    assert '/api/legacy-management/audit' in js
    assert 'path == "/api/legacy-management"' in py
    assert 'path == "/api/legacy-management/item"' in py
    assert 'u.path == "/api/legacy-management/verify"' in py
    assert 'u.path == "/api/legacy-management/audit"' in py


def test_legacy_management_http_endpoints_are_live(tmp_path):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pt_asset_tool.ui_app import UIContext, UIHandler

    project = tmp_path / "project"
    client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (project / "pt_asset.py").write_text('#!/usr/bin/env python3\nprint("test")\n', encoding="utf-8")
    ctx = UIContext(project, client)
    server = ThreadingHTTPServer(("127.0.0.1", 0), UIHandler)
    server.ctx = ctx; ctx.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(base + "/api/legacy-management", timeout=5) as response:
            dashboard = json.loads(response.read().decode("utf-8"))
        assert dashboard["ok"] is True
        assert dashboard["legacy_contract"]["tool_count"] >= 10
        with urllib.request.urlopen(base + "/api/legacy-management/item?code=WA121", timeout=5) as response:
            item = json.loads(response.read().decode("utf-8"))
        assert item["ok"] is True
        assert item["runtime_item_contract"]["status"] == "SOURCE_VERIFIED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_legacy_authoring_web_surface_is_wired():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    assert "Legacy Authoring / Reescrita Python" in html
    assert 'id="legacyAuthoringStageBtn"' in html
    assert '/api/legacy-authoring/inspect?' in js
    assert '/api/legacy-authoring/stage' in js
    assert 'path == "/api/legacy-authoring/inspect"' in py
    assert 'u.path == "/api/legacy-authoring/stage"' in py


def test_legacy_authoring_http_inspect_endpoint_is_live(tmp_path):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pt_asset_tool.ui_app import UIContext, UIHandler

    project = tmp_path / "project"
    client = tmp_path / "client"
    server_root = tmp_path / "server"
    project.mkdir(); client.mkdir(); server_root.mkdir()
    (project / "pt_asset.py").write_text('#!/usr/bin/env python3\nprint("test")\n', encoding="utf-8")
    target = server_root / "GameServer/OpenItem/WA121.txt"
    target.parent.mkdir(parents=True)
    from pt_asset_tool.asset_compiler import _legacy_line, _source_token
    target.write_bytes((
        _legacy_line(_source_token("item_tokens", "Name"), ["Axe"]) + "\r\n" +
        _legacy_line(_source_token("item_tokens", "Code"), ["WA121"]) + "\r\n"
    ).encode("cp949"))
    ctx = UIContext(project, client, server_root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), UIHandler)
    server.ctx = ctx; ctx.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        url = base + "/api/legacy-authoring/inspect?kind=ITEM&path=GameServer%2FOpenItem%2FWA121.txt"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["result"]["kind"] == "ITEM"
        assert data["result"]["exists"] is True
        assert data["result"]["detail"]["runtime_item_contract"]["status"] == "SOURCE_VERIFIED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
