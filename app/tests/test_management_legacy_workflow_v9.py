from __future__ import annotations

import io
import json
import pathlib
import sqlite3

import pytest
from bs4 import BeautifulSoup

from pt_asset_tool.asset_compiler import _source_token
from pt_asset_tool.legacy_apps.common import app_project_root, legacy_build_root
from pt_asset_tool.legacy_apps.plan_store import save_plan
from pt_asset_tool.legacy_apps.selections import selection_catalog
from pt_asset_tool.legacy_apps.workspace import workspace_status, plan_operation
from pt_asset_tool.ui_app import UIHandler


APP = pathlib.Path(__file__).resolve().parents[1]


def _fake_app(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    repo = tmp_path / "repo"
    app = repo / "app"
    (app / "pt_asset_tool").mkdir(parents=True)
    (app / "pt_asset.py").write_text("# test\n", encoding="utf-8")
    return repo, app


def _server(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "server"
    (root / "GameServer" / "OpenItem").mkdir(parents=True)
    (root / "DataServer" / "userdata" / "a").mkdir(parents=True)
    (root / "DataServer" / "userinfo" / "a").mkdir(parents=True)
    (root / "DataServer" / "warehouse" / "a").mkdir(parents=True)
    return root


def test_legacy_pt_build_root_never_duplicates_app(tmp_path: pathlib.Path):
    repo, app = _fake_app(tmp_path)
    assert app_project_root(app) == app.resolve()
    assert app_project_root(repo) == app.resolve()
    assert legacy_build_root(app) == app.resolve() / "pt_build"
    assert legacy_build_root(repo) == app.resolve() / "pt_build"
    saved = save_plan(app, "TEST_PLAN", {"status": "READY", "write_authorized": False})
    path = pathlib.Path(saved["path"])
    assert path.is_file()
    assert path.is_relative_to(app / "pt_build" / "legacy_apps" / "plans")
    assert "/app/app/pt_build/" not in path.as_posix()


def test_selection_catalog_combines_runtime_code_openitem_name_and_identities(tmp_path: pathlib.Path):
    server = _server(tmp_path)
    name_token = _source_token("item_tokens", "Name")
    code_token = _source_token("item_tokens", "Code")
    # WA101 is part of the source-backed runtime catalogue in the bundled contracts.
    (server / "GameServer" / "OpenItem" / "WA101.txt").write_text(
        f'{name_token} "Sword Test"\n{code_token} WA101\n', encoding="utf-8"
    )
    (server / "DataServer" / "userdata" / "a" / "Hero.dat").write_bytes(b"x")
    (server / "DataServer" / "userinfo" / "a" / "Account.dat").write_bytes(b"x")
    report = selection_catalog(server, refresh=True)
    row = next(x for x in report["items"] if x["code"].casefold() == "wa101")
    assert row["runtime_verified"] is True
    assert row["name"] == "Sword Test"
    assert row["display"] == "WA101 — Sword Test"
    assert row["openitem_path"] == "GameServer/OpenItem/WA101.txt"
    assert "Hero" in report["characters"]
    assert "Account" in report["accounts"]


def test_sqlite_database_is_discovered_by_schema_not_filename(tmp_path: pathlib.Path):
    server = _server(tmp_path)
    db_dir = server / "Database"
    db_dir.mkdir()
    wrong = db_dir / "summit.sqlite3"
    with sqlite3.connect(wrong) as db:
        db.execute("CREATE TABLE unrelated(x INTEGER)")
    right = db_dir / "runtime_state.db"
    with sqlite3.connect(right) as db:
        db.execute("CREATE TABLE RunLog(id INTEGER)")
        db.execute("CREATE TABLE UL(id INTEGER)")
        db.execute("CREATE TABLE CL(id INTEGER)")
        db.execute("CREATE TABLE GameRecordBPRank(CharName TEXT, ok INTEGER)")
        db.execute("CREATE TABLE GameUser(userid TEXT, BlockChk INTEGER, reason TEXT)")
    status = workspace_status(tmp_path, server)
    assert status["database"]["backend"] == "SQLite"
    assert pathlib.Path(status["database"]["path"]) == right.resolve()
    assert status["database"]["selection_basis"] == "SCHEMA_MATCH"
    assert status["database"]["capabilities"] == {"sod": True, "bprank": True, "account_block": True}
    bp = plan_operation(server, "BPRANK_MARK", {"db_path": str(right), "char_name": "Hero"})
    assert bp["status"] == "READY" and bp["schema_verified"] is True
    block = plan_operation(server, "ACCOUNT_BLOCK", {"db_path": str(right), "account": "Account", "reason": "test"})
    assert block["status"] == "READY" and block["schema_verified"] is True


def test_legacy_plan_validation_reports_missing_values_before_binary_work(tmp_path: pathlib.Path):
    server = _server(tmp_path)
    with pytest.raises(ValueError, match="CHARACTER_REQUIRED"):
        plan_operation(server, "CHARACTER_RENAME", {"old_name": "", "new_name": "x"})
    with pytest.raises(ValueError, match="NEW_CHARACTER_NAME_REQUIRED"):
        plan_operation(server, "CHARACTER_RENAME", {"old_name": "Hero", "new_name": ""})
    with pytest.raises(ValueError, match="ITEM_CODE_REQUIRED"):
        plan_operation(server, "ITEM_DISTRIBUTE", {"account": "a", "character": "b", "item_code": ""})


def test_json_writer_treats_browser_disconnect_as_benign():
    class Broken:
        def write(self, _data):
            raise BrokenPipeError(32, "closed")

    h = UIHandler.__new__(UIHandler)
    h.wfile = Broken()
    h.close_connection = False
    h.send_response = lambda _status: None
    h.send_header = lambda *_args: None
    h.end_headers = lambda: None
    # Must not re-raise or try to synthesize a second error response.
    h._json(200, {"ok": True})
    assert h.close_connection is True


def test_management_page_is_task_local_and_help_matches_runtime():
    html = (APP / "pt_asset_tool" / "ui_static" / "index.html").read_text(encoding="utf-8")
    js = (APP / "pt_asset_tool" / "ui_static" / "app.js").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    ids = [x.get("id") for x in soup.find_all(attrs={"id": True})]
    assert len(ids) == len(set(ids))
    assert {x.get("data-legacy-editor-mount") for x in soup.select("[data-legacy-editor-mount]")} == {"item", "monster", "npc", "map"}
    assert soup.select_one("#legacyAuthoringPublishBtn").has_attr("disabled")
    assert soup.select_one("#legacyCharacterName").name == "select"
    assert soup.select_one("#legacyPostboxItem").name == "select"
    assert soup.select_one("#legacyDatabasePath").name == "select"
    assert "Local admin:</strong> the database is SQLite detected by schema" in html
    assert "Substitui as capacidades comprovadas de Level Editor" not in html
    assert "Substitui o botão <code>Copy</code>" not in html
    assert "function mountLegacyEditor(task)" in js
    assert "/api/legacy-ops/selections" in js
    assert "Run Stage for this task before publishing" in js
    assert "legacyDatabaseFor('sod')" in js
    assert "legacyDatabaseFor('bprank')" in js
    assert "legacyDatabaseFor('account_block')" in js
    assert "db_path" in js


def test_legacy_source_has_no_app_app_pt_build_regression():
    roots = [APP / "pt_asset_tool" / "legacy_apps" / "plan_store.py", APP / "pt_asset_tool" / "legacy_apps" / "apply.py"]
    for path in roots:
        text = path.read_text(encoding="utf-8")
        assert '/ "app" / "pt_build"' not in text


def test_all_static_ui_api_calls_have_backend_routes():
    import re
    js = (APP / "pt_asset_tool" / "ui_static" / "app.js").read_text(encoding="utf-8")
    backend = (APP / "pt_asset_tool" / "ui_app.py").read_text(encoding="utf-8")
    calls = {
        m.group(2).rstrip("/")
        for m in re.finditer(r"api\((['\"`])(/api/[^'\"`?${]*)", js)
    }
    routes = set(re.findall(r"(?:path|u\.path)\s*==\s*['\"](/api/[^'\"]+)", backend))
    routes |= set(re.findall(r"(?:path|u\.path)\.startswith\(['\"](/api/[^'\"]+)", backend))
    for group in re.findall(r"(?:path|u\.path)\s+in\s+\{([^}]+)\}", backend):
        routes |= set(re.findall(r"['\"](/api/[^'\"]+)['\"]", group))
    missing = [
        call for call in sorted(calls)
        if not (call in routes or any(call.startswith(r.rstrip('/')) or r.startswith(call.rstrip('/')) for r in routes))
    ]
    assert missing == []


def test_active_management_runtime_is_sqlite_first():
    workspace = (APP / "pt_asset_tool" / "legacy_apps" / "workspace.py").read_text(encoding="utf-8")
    ui = (APP / "pt_asset_tool" / "ui_static" / "index.html").read_text(encoding="utf-8")
    assert "SQLiteSodDataSource" in workspace
    assert "PyodbcSodDataSource" not in workspace
    assert "SQLite database" in ui
    assert "SQL Server" not in ui[ui.index('id="tab-legacy"'):ui.index('id="tab-particles"')]
