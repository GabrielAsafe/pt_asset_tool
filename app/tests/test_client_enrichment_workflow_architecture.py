from __future__ import annotations

import json
import pathlib
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from bs4 import BeautifulSoup

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


def test_client_page_is_workflow_oriented_and_does_not_duplicate_catalog_entities():
    root = pathlib.Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    client = soup.find(id="tab-client")
    assert client is not None

    workflows = [x.get("data-client-workflow") for x in client.select("[data-client-workflow]")]
    assert workflows == ["overview", "diagnostics", "census", "validation", "enhancement", "activity"]
    assert len(client.select("[data-client-workflow-pane]")) == 6

    # Client/Enrichment is no longer a second Catalog/Entities cockpit.
    for duplicated_id in ["assetRows", "galleryMode", "detailPanel", "entityGrid", "entityDetail"]:
        assert client.find(id=duplicated_id) is None

    text = client.get_text(" ", strip=True)
    assert "one authority per task" in text
    assert "Catalog" in text and "Entities" in text
    assert "Client / Enrichment Activity" in text
    assert "workflows with their own page" in (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8").lower()
    assert "global/batch workflow" in text

    assert "switchClientWorkflow" in js
    assert "loadClientActivity" in js
    assert "openClientJobResult" in js
    assert "surface=client" in js
    assert "!['server','client'].includes(j.surface)" in js


def test_client_jobs_keep_surface_workflow_and_result_anchor(tmp_path: pathlib.Path):
    project, client, ctx, server, thread, url = make(tmp_path)
    source, reference, server_root = tmp_path / "source", tmp_path / "reference", tmp_path / "server"
    for path in (source, reference, server_root):
        path.mkdir()
    try:
        _, boot = request(url + "/api/bootstrap")
        token = boot["token"]
        request(url + "/api/server/config", token, {"server_root": str(server_root)})
        request(url + "/api/contracts/config", token, {
            "source_root": str(source),
            "reference_source_root": str(reference),
            "donor_clients": [],
            "donor_servers": [],
        })

        _, analyzed = request(url + "/api/client/analyze", token, {})
        aj = analyzed["job"]
        assert aj["surface"] == "client"
        assert aj["workflow"] == "validation"
        assert aj["result_anchor"] == "clientValidationPanel"

        _, classes = request(url + "/api/contracts/analyze", token, {"mode": "player_classes", "surface": "client"})
        cj = classes["job"]
        assert cj["surface"] == "client"
        assert cj["workflow"] == "diagnostics"
        assert cj["result_anchor"] == "clientPlayerSummary"

        _, graph = request(url + "/api/server/analyze", token, {"mode": "vendor_graph", "surface": "client"})
        gj = graph["job"]
        assert gj["surface"] == "client"
        assert gj["workflow"] == "census"
        assert gj["result_anchor"] == "clientGraphSummary"

        _, client_jobs = request(url + "/api/jobs?surface=client&limit=20")
        ids = {x["id"] for x in client_jobs["jobs"]}
        assert {aj["id"], cj["id"], gj["id"]} <= ids
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_client_enhancement_jobs_are_routed_back_to_dedicated_workflow():
    root = pathlib.Path(__file__).resolve().parents[1]
    app = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    for action in ["enhancement_batch_run", "enhancement_batch_resume", "enhancement_batch_publish", "enhancement_batch_restore"]:
        needle = f'self.ctx.jobs.submit("{action}", None, cmd, surface="client", workflow="enhancement", result_anchor="clientEnhancementBatchSummary")'
        assert needle in app
