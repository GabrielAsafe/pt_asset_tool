from __future__ import annotations

import json
from pathlib import Path

import pytest

from pt_asset_tool.item_visual_index import build_item_visual_index, load_or_build_item_visual_index
from pt_asset_tool.registry_bootstrap import FORMAT as REGISTRY_FORMAT, ensure_runtime_registry
from pt_asset_tool.ui_app import UIContext


def rec(path: str, **extra):
    p = Path(path)
    return {
        "relative_path": path,
        "extension": p.suffix.lower(),
        "size": 10,
        "mtime_ns": 1,
        **extra,
    }


def runtime(code: str, icon: str, drop: str):
    return {
        "code": code,
        "numeric_code": 1,
        "dorp_item": code,
        "expected_client_paths": {"inventory_icon": icon, "drop_model_ase": drop},
    }


def graph_fixture():
    return {
        "nodes": {},
        "edges": [
            {"src": "item:DA102", "dst": "client-expected:x", "relation": "catalog_icon", "note": "image/Sinimage/Items/Defense/itda102.bmp"},
            {"src": "item:DA301", "dst": "client-expected:y", "relation": "catalog_icon", "note": "image/Sinimage/Items/Defense/itda301.bmp"},
            {"src": "item:DA102", "dst": "client-expected:z", "relation": "catalog_drop_model", "note": "image/Sinimage/Items/DropItem/itda102.smd"},
            {"src": "item:DA301", "dst": "client-expected:w", "relation": "catalog_drop_model", "note": "image/Sinimage/Items/DropItem/itda301.smd"},
            {"src": "client:image/Sinimage/Items/DropItem/itda102.smd", "dst": "client:image/Sinimage/Items/DropItem/drda103.tga", "relation": "client_asset_reference"},
            {"src": "client:image/Sinimage/Items/DropItem/itda301.smd", "dst": "client:image/Sinimage/Items/DropItem/drda103.tga", "relation": "client_asset_reference"},
            {"src": "client:char/tmABCD/body.smd", "dst": "client:image/Sinimage/Items/DropItem/drda103.tga", "relation": "client_asset_reference"},
            {"src": "client:char/tmABCD/a002.ini", "dst": "client:char/tmABCD/body.smd", "relation": "client_asset_reference"},
        ],
    }


def inventory_fixture(client_root: str = "/client"):
    records = [
        rec("image/Sinimage/Items/Defense/itda102.bmp"),
        rec("image/Sinimage/Items/Defense/itda301.bmp"),
        rec("image/Sinimage/Items/DropItem/itda102.smd", texture_refs=["drda103.tga"]),
        rec("image/Sinimage/Items/DropItem/itda301.smd", texture_refs=["drda103.tga"]),
        rec("image/Sinimage/Items/DropItem/drda103.tga"),
        rec("char/tmABCD/body.smd", texture_refs=["image/Sinimage/Items/DropItem/drda103.tga"]),
        rec("char/tmABCD/a002.inx", model_ref="body.smd"),
        rec("char/tmABCD/a002.ini"),
    ]
    return {"format": REGISTRY_FORMAT, "canonical_client_root": client_root, "records": records}


def catalog_rows(manual_texture_role: str = ""):
    inv = inventory_fixture()
    rows = []
    for r in inv["records"]:
        path = r["relative_path"]
        ext = Path(path).suffix.lower()
        rows.append({
            "path": path,
            "ext": ext,
            "role": manual_texture_role if path.endswith("drda103.tga") and manual_texture_role else "MODEL",
            "previewable": ext in {".bmp", ".tga", ".png"},
        })
    return rows


def test_item_visual_index_reuses_census_graph_and_keeps_runtime_identities_distinct():
    entries = [
        runtime("DA102", "image/Sinimage/Items/Defense/itda102.bmp", "image/Sinimage/Items/DropItem/itda102.ASE"),
        runtime("DA301", "image/Sinimage/Items/Defense/itda301.bmp", "image/Sinimage/Items/DropItem/itda301.ASE"),
    ]
    idx = build_item_visual_index(inventory_fixture(), graph_fixture(), catalog_rows(), runtime_entries=entries)
    assert idx["bundle_count"] == 1
    bundle = idx["bundles"][0]
    assert bundle["runtime_codes"] == ["DA102", "DA301"]
    assert bundle["runtime_identity_count"] == 2
    assert bundle["evidence"] == "EXACT_FULL_TEXTURE_DEPENDENCY_SET"
    paths_by_role = {k: {x["path"].casefold() for x in v} for k, v in bundle["roles"].items()}
    assert "image/sinimage/items/defense/itda102.bmp" in paths_by_role["ITEM_INVENTORY_IMAGE"]
    assert "image/sinimage/items/dropitem/itda102.smd" in paths_by_role["ITEM_GROUND_MODEL"]
    assert "image/sinimage/items/dropitem/drda103.tga" in paths_by_role["ITEM_GROUND_TEXTURE"]
    assert "char/tmabcd/body.smd" in paths_by_role["ITEM_EQUIPPED_MODEL"]
    assert "char/tmabcd/a002.inx" in paths_by_role["ITEM_EQUIPPED_CONFIG"]
    assert "char/tmabcd/a002.ini" in paths_by_role["ITEM_EQUIPPED_CONFIG"]


def test_manual_item_role_override_moves_asset_but_preserves_automatic_role():
    entries = [runtime("DA102", "image/Sinimage/Items/Defense/itda102.bmp", "image/Sinimage/Items/DropItem/itda102.ASE")]
    idx = build_item_visual_index(
        inventory_fixture(), graph_fixture(), catalog_rows("ITEM_INVENTORY_IMAGE"), runtime_entries=entries
    )
    membership = idx["by_path"]["image/sinimage/items/dropitem/drda103.tga"]
    assert membership["role"] == "ITEM_INVENTORY_IMAGE"
    assert membership["automatic_role"] == "ITEM_GROUND_TEXTURE"
    assert membership["manual_override"] is True
    bundle = idx["bundle_map"][membership["bundle_key"]]
    assert any(x["path"].endswith("drda103.tga") for x in bundle["roles"]["ITEM_INVENTORY_IMAGE"])
    assert not any(x["path"].endswith("drda103.tga") for x in bundle["roles"]["ITEM_GROUND_TEXTURE"])


def test_item_visual_index_is_persisted_and_second_start_uses_cache(tmp_path: Path):
    inventory_path = tmp_path / "asset_inventory.json"
    graph_path = tmp_path / "graph.json"
    cache_path = tmp_path / "item_visual.json"
    inventory_path.write_text(json.dumps(inventory_fixture()), encoding="utf-8")
    graph_path.write_text(json.dumps(graph_fixture()), encoding="utf-8")
    entries = [runtime("DA102", "image/Sinimage/Items/Defense/itda102.bmp", "image/Sinimage/Items/DropItem/itda102.ASE")]
    first, hit1 = load_or_build_item_visual_index(
        inventory_path=inventory_path, graph_path=graph_path, cache_path=cache_path,
        catalog_rows=catalog_rows(), state_revision=0, client_signature="abc", runtime_entries=entries,
    )
    second, hit2 = load_or_build_item_visual_index(
        inventory_path=inventory_path, graph_path=graph_path, cache_path=cache_path,
        catalog_rows=catalog_rows(), state_revision=0, client_signature="abc", runtime_entries=entries,
    )
    assert hit1 is False
    assert hit2 is True
    assert second["by_path"] == first["by_path"]


def test_ui_fast_registry_path_does_not_walk_client_signature(tmp_path: Path, monkeypatch):
    import pt_asset_tool.registry_bootstrap as rb

    client = tmp_path / "client"
    client.mkdir()
    registry_dir = tmp_path / "state"
    registry_dir.mkdir()
    inventory = registry_dir / "asset_inventory.json"
    pairing = registry_dir / "inx_physical_pairing.csv"
    inventory.write_text(json.dumps({"canonical_client_root": str(client), "records": []}), encoding="utf-8")
    pairing.write_text("inx,model_ref\n", encoding="utf-8")
    (registry_dir / "registry_meta.json").write_text(json.dumps({
        "format": REGISTRY_FORMAT,
        "client_root": str(client),
        "record_count": 0,
        "client_signature": {"stat_sha256": "persisted"},
    }), encoding="utf-8")
    monkeypatch.setattr(rb, "_client_stat_signature", lambda *_: pytest.fail("UI fast path walked the client"))
    result = ensure_runtime_registry(client, inventory, pairing, verify_signature=False)
    assert result["status"] == "READY_PERSISTED"
    assert result["signature_verified_now"] is False


def test_ui_context_starts_from_persisted_inventory_without_physical_catalog_scan(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (project / "pt_asset.py").write_text("print('1.0.0')\n", encoding="utf-8")
    registry_dir = project / "pt_build/state/asset_registry"
    registry_dir.mkdir(parents=True)
    inv = {"canonical_client_root": str(client), "records": [rec("image/test.bmp")]}
    (registry_dir / "asset_inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    (registry_dir / "inx_physical_pairing.csv").write_text("inx,model_ref\n", encoding="utf-8")
    (registry_dir / "registry_meta.json").write_text(json.dumps({
        "format": REGISTRY_FORMAT, "client_root": str(client), "record_count": 1,
        "client_signature": {"stat_sha256": "persisted"},
    }), encoding="utf-8")

    from pt_asset_tool import ui_catalog
    monkeypatch.setattr(ui_catalog.CatalogIndex, "rebuild", lambda *_: pytest.fail("startup used physical scan"))
    ctx = UIContext(project, client)
    assert ctx.catalog.source_mode == "PERSISTED_RUNTIME_REGISTRY"
    assert ctx.catalog.stats.file_count == 1


def test_frontend_reuses_entity_results_when_reentering_page_and_exposes_item_roles():
    root = Path(__file__).resolve().parents[1]
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    assert "entityListCache" in js
    assert "if(!force&&S.entityListCache[cacheKey])" in js
    assert "async function refreshEntities()" in js
    assert "Item visual role" in js
    assert "itemVisualBundleHtml" in js
    assert "Item relationship" in html
