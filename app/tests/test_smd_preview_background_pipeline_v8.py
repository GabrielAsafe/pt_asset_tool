from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

from pt_asset_tool.ui_catalog import CatalogIndex, UIStateStore
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool import smd_preview_batch


def test_resolver_primes_from_persisted_inventory_without_client_scan(tmp_path: pathlib.Path):
    client = tmp_path / "client"
    client.mkdir()
    inv = tmp_path / "asset_inventory.json"
    inv.write_text(json.dumps({
        "canonical_client_root": str(client),
        "records": [
            {"relative_path": "char/tmABCD/CtmbC010.smd"},
            {"relative_path": "char/tmABCD/Ava_M_03.tga"},
        ],
    }), encoding="utf-8")
    r = ClientResolver(client)
    idx = r.prime_from_inventory(inv)
    assert "char/tmabcd/ctmbc010.smd" in idx
    assert r._index is idx
    assert r.resolve("CHAR/TMABCD/CTMBC010.SMD", required=False) == client / "char/tmABCD/CtmbC010.smd"


def test_catalog_preview_status_filter_is_backend_wide(tmp_path: pathlib.Path):
    client = tmp_path / "client"; client.mkdir()
    state = UIStateStore(tmp_path / "state.json")
    c = CatalogIndex(client, state)
    c.assets = [
        {"path": "char/a.smd", "name": "a.smd", "ext": ".smd", "category": "CHARACTER", "role": "BODY", "character": "Pikeman", "folder": "tmABCD", "folder_path": "char/tmABCD", "favorite": False, "visibility_tier": "AUTHORABLE", "size": 1, "_search_text": "char/a.smd"},
        {"path": "char/b.smd", "name": "b.smd", "ext": ".smd", "category": "CHARACTER", "role": "BODY", "character": "Pikeman", "folder": "tmABCD", "folder_path": "char/tmABCD", "favorite": False, "visibility_tier": "AUTHORABLE", "size": 1, "_search_text": "char/b.smd"},
        {"path": "image/x.tga", "name": "x.tga", "ext": ".tga", "category": "CHARACTER", "role": "BODY", "character": "Pikeman", "folder": "tmABCD", "folder_path": "char/tmABCD", "favorite": False, "visibility_tier": "AUTHORABLE", "size": 1, "_search_text": "image/x.tga"},
    ]
    c.by_path = {x["path"]: x for x in c.assets}
    c.apply_smd_preview_index({
        "char/a.smd": {"status": "READY"},
        "char/b.smd": {"status": "FAILED", "detail": "boom"},
    })
    ready = c.query(preview_status="READY", page_size=10)
    failed = c.query(preview_status="FAILED", page_size=10)
    assert [x["path"] for x in ready["items"]] == ["char/a.smd"]
    assert [x["path"] for x in failed["items"]] == ["char/b.smd"]
    assert {x["value"] for x in ready["facets"]["smd_previews"]} >= {"READY", "FAILED"}


def test_batch_persists_progress_and_uses_registry_not_rglob(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    inv = project / "pt_build/state/asset_registry/asset_inventory.json"
    pair = project / "pt_build/state/asset_registry/inx_physical_pairing.csv"
    inv.parent.mkdir(parents=True)
    inv.write_text("{}", encoding="utf-8"); pair.write_text("x\n", encoding="utf-8")

    settings = SimpleNamespace(client_root=client, inventory=inv, pairing=pair)
    monkeypatch.setattr(smd_preview_batch.Settings, "discover", classmethod(lambda cls, *a, **k: settings))
    monkeypatch.setattr(smd_preview_batch, "blender_runtime_info", lambda *a, **k: {"ready": True, "source": "TEST", "version": "3.6.23", "command": ["blender"]})

    class FakeResolver:
        def __init__(self, root): self.root = root; self.primed = False
        def prime_from_inventory(self, path): self.primed = True
    monkeypatch.setattr(smd_preview_batch, "ClientResolver", FakeResolver)

    assets = [SimpleNamespace(primary_path="char/a.smd", family="SMD_MODEL_062_STATIC"), SimpleNamespace(primary_path="char/b.smd", family="SMD_MODEL_062_STATIC")]
    class FakeRegistry:
        def __init__(self, *a, **k): self.assets = assets
    monkeypatch.setattr(smd_preview_batch, "AssetRegistry", FakeRegistry)
    monkeypatch.setattr(smd_preview_batch, "build_smd_preview_plan", lambda reg, res, rel: {"logical": rel, "dependency_paths": [], "smd": str(client / pathlib.PurePosixPath(rel)), "lod": "default"})

    class FakeManager:
        def __init__(self, *a, **k): pass
        def classify(self, plan): return {"status": "MISSING", "asset": plan["logical"]}
        def render_now(self, plan, retry=True, force=False): return {"status": "READY", "asset": plan["logical"], "dependency_count": 0}
    monkeypatch.setattr(smd_preview_batch, "SmdPreviewManager", FakeManager)

    out = smd_preview_batch.run_batch(project, client, mode="warmup", workers=2)
    assert out["status"] == "COMPLETE"
    assert out["selected_for_render"] == 2
    assert out["counts_final"]["READY"] == 2
    persisted = json.loads(smd_preview_batch.batch_state_path(project).read_text(encoding="utf-8"))
    assert persisted["status"] == "COMPLETE"
    assert persisted["blender"]["version"] == "3.6.23"


def test_v8_ui_exposes_batch_thumbnail_and_filters():
    root = pathlib.Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    assert 'id="smdPreviewStatus"' in html
    assert 'id="smdPreviewWarmupBtn"' in html
    assert 'id="catalogSmdPreviewTools"' in html
    assert "/api/smd-preview?path=" in js
    assert "smd_preview_status" in js
    assert "runSmdPreviewBatch('warmup')" in js
    assert "smd_preview_batch:'Gerar previews SMD'" in js


def test_cli_exposes_render_all_smd_command():
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "pt_asset.py").read_text(encoding="utf-8")
    assert 'args[0] == "preview" and args[1] == "render-all-smd"' in text
    assert "preview render-all-smd" in text
