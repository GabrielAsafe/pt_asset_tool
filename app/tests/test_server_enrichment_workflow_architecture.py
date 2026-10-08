from __future__ import annotations

import json
import pathlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from bs4 import BeautifulSoup

from pt_asset_tool.app_config import validate_contract_donor_specs
from pt_asset_tool.ui_app import UIContext, UIHandler


def request(url: str, token: str | None = None, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {}
    if token:
        headers["X-PT-UI-Token"] = token
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode())


def request_error(url: str, token: str, body: dict):
    try:
        request(url, token, body)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())
    raise AssertionError("request unexpectedly succeeded")


def make(tmp_path: pathlib.Path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    (project / "pt_asset_tool").mkdir(parents=True)
    client.mkdir()
    (project / "pt_asset.py").write_text(
        "#!/usr/bin/env python3\nimport json,sys\n"
        "if sys.argv[1:]==['--version']: print('9.9-test')\n"
        "else: print(json.dumps({'status':'PASS','argv':sys.argv[1:]}))\n"
    )
    ctx = UIContext(project, client)
    server = ThreadingHTTPServer(("127.0.0.1", 0), UIHandler)
    server.ctx = ctx
    ctx.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return project, client, ctx, server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def test_donor_parser_accepts_gui_and_cli_forms_and_explains_bad_line(tmp_path: pathlib.Path):
    client = tmp_path / "donor client with spaces"
    server = tmp_path / "donor server with spaces"
    client.mkdir(); server.mkdir()

    c = validate_contract_donor_specs([
        f"OFFICIAL={client}",
        "# comment",
    ], "client")
    assert c["ok"] is True
    assert c["normalized"] == [f"OFFICIAL={client.resolve()}"]

    s = validate_contract_donor_specs([
        f"--donor-server 'PT_EU={server}'",
    ], "server")
    assert s["ok"] is True
    assert s["normalized"] == [f"PT_EU={server.resolve()}"]

    bad = validate_contract_donor_specs(["GOOD=/does/not/exist", "NO_EQUALS"], "client")
    assert bad["ok"] is False
    assert [(x["line"], x["code"]) for x in bad["issues"]] == [
        (1, "DONOR_ROOT_NOT_FOUND"),
        (2, "DONOR_ROOT_FORMAT_INVALID"),
    ]
    assert bad["issues"][1]["side"] == "client"
    assert "Falta '='" in bad["issues"][1]["message"]


def test_invalid_contract_config_is_line_specific_and_does_not_replace_saved_config(tmp_path: pathlib.Path):
    project, client, ctx, server, thread, url = make(tmp_path)
    source1, ref1, donor1 = tmp_path / "source1", tmp_path / "ref1", tmp_path / "donor1"
    source2, ref2 = tmp_path / "source2", tmp_path / "ref2"
    for p in (source1, ref1, donor1, source2, ref2):
        p.mkdir()
    try:
        _, boot = request(url + "/api/bootstrap")
        token = boot["token"]
        _, saved = request(url + "/api/contracts/config", token, {
            "source_root": str(source1),
            "reference_source_root": str(ref1),
            "donor_clients": [f"OFFICIAL={donor1}"],
            "donor_servers": [],
        })
        assert saved["source_root"] == str(source1.resolve())

        status, error = request_error(url + "/api/contracts/config", token, {
            "source_root": str(source2),
            "reference_source_root": str(ref2),
            "donor_clients": ["BROKEN WITHOUT EQUALS"],
            "donor_servers": [],
        })
        assert status == 400
        assert error["error"] == "CONTRACT_SOURCE_CONFIG_INVALID"
        issue = error["issues"][0]
        assert issue["side"] == "client" and issue["line"] == 1
        assert issue["code"] == "DONOR_ROOT_FORMAT_INVALID"

        _, current = request(url + "/api/contracts")
        assert current["source_root"] == str(source1.resolve())
        assert current["reference_source_root"] == str(ref1.resolve())
        assert current["donor_clients"] == [f"OFFICIAL={donor1.resolve()}"]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_server_jobs_keep_surface_and_result_workflow_while_client_jobs_stay_out(tmp_path: pathlib.Path):
    project, client, ctx, server, thread, url = make(tmp_path)
    source, reference, server_root = tmp_path / "source", tmp_path / "reference", tmp_path / "server"
    for p in (source, reference, server_root):
        p.mkdir()
    try:
        _, boot = request(url + "/api/bootstrap")
        token = boot["token"]
        request(url + "/api/server/config", token, {"server_root": str(server_root)})
        request(url + "/api/contracts/config", token, {
            "source_root": str(source), "reference_source_root": str(reference),
            "donor_clients": [], "donor_servers": [],
        })

        _, server_job = request(url + "/api/contracts/analyze", token, {"mode": "source", "surface": "server"})
        sj = server_job["job"]
        assert sj["surface"] == "server"
        assert sj["workflow"] == "diagnostics"
        assert sj["result_anchor"] == "sourceContractsSummary"

        _, client_job = request(url + "/api/contracts/analyze", token, {"mode": "player_classes", "surface": "client"})
        cj = client_job["job"]
        assert cj["surface"] == "client"
        assert cj["workflow"] == "diagnostics"
        assert cj["result_anchor"] == "clientPlayerSummary"

        # Jobs may finish immediately in the fake backend; routing metadata remains.
        time.sleep(0.05)
        _, server_jobs = request(url + "/api/jobs?surface=server&limit=20")
        ids = {x["id"] for x in server_jobs["jobs"]}
        assert sj["id"] in ids and cj["id"] not in ids
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_server_page_is_workflow_oriented_and_authoring_is_not_duplicated():
    root = pathlib.Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    server = soup.find(id="tab-server")
    assert server is not None

    workflow_names = [x.get("data-server-workflow") for x in server.select("[data-server-workflow]")]
    assert workflow_names == ["config", "diagnostics", "census", "validation", "evidence", "activity"]
    assert len(server.select("[data-server-workflow-pane]")) == 6

    # The old second authoring cockpit is gone from Server / Enrichment.
    for obsolete_id in [
        "serverExplorerKind", "serverExplorerRows", "fieldOpenSpm", "fieldOpenSpp", "fieldOpenSpc",
        "fieldEditorForm", "assetRecipeInput", "assetRecipePlanBtn", "assetRecipeBuildBtn",
    ]:
        assert server.find(id=obsolete_id) is None

    server_text = server.get_text(" ", strip=True)
    assert "Management Legacy" in server_text
    assert "Server / Enrichment Activity" in server_text
    assert "line copied from the CLI" in server_text
    assert "nothing is partially saved" in server_text

    assert "switchServerWorkflow" in js
    assert "loadServerActivity" in js
    assert "openServerJobResult" in js
    assert "!['server','client'].includes(j.surface)" in js
    assert "runContractAnalysis('player_classes','client')" in js
