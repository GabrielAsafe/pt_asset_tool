from __future__ import annotations

import json
from pathlib import Path

from pt_asset_tool.source_catalog import SourceTree
from pt_asset_tool.summit_asset_migration_audit import (
    audit_canonical_asset_relations,
    audit_summit_asset_migration_gap,
)


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_canonical_runtime_paths_become_strong_client_roots(tmp_path: Path):
    project = tmp_path / "asset-tool"
    client = tmp_path / "client"
    source = tmp_path / "SourceCode"
    project.mkdir(); client.mkdir(); source.mkdir()
    _write(client / "Image" / "UI" / "inventory.tga")
    _write(client / "Effect" / "AnimationData" / "MonsterHit.ini")
    doc = source / "Content" / "canonical" / "text" / "resources" / "ui.json"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(json.dumps({
        "schema": "summit.test/v1",
        "id": "ui.inventory",
        "runtime_paths": ["cliente/Image/UI/inventory.tga", "Effect/AnimationData/MonsterHit.ini"],
        "provenance": {"legacy_path": "cliente/Image/old-unused.tga"},
    }), encoding="utf-8")

    result = audit_canonical_asset_relations(project, client, source)
    assert result["status"] == "PASS"
    roots = {x["path"].casefold() for x in result["strong_client_roots"]}
    assert "image/ui/inventory.tga" in roots
    assert "effect/animationdata/monsterhit.ini" in roots
    # provenance is evidence only, never promoted to runtime root.
    assert "image/old-unused.tga" not in roots


def test_migration_gap_finds_source_only_missing_effect_and_ui_text(tmp_path: Path):
    project = tmp_path / "asset-tool"
    client = tmp_path / "client"
    source = tmp_path / "SourceCode"
    project.mkdir(); client.mkdir(); source.mkdir()
    _write(client / "Image" / "UI" / "inventory.tga")
    _write(client / "Effect" / "legacy" / "sourceonly.part")

    canonical = source / "Content" / "canonical" / "text" / "resources" / "ui.json"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(json.dumps({
        "id": "ui.inventory",
        "runtime_paths": ["cliente/Image/UI/inventory.tga"],
    }), encoding="utf-8")

    cpp = source / "SrcGame" / "src" / "systems" / "ui" / "inventory" / "InventoryWindow.cpp"
    _write(cpp, r'''
void Draw() {
    ImageLoad("Image/UI/inventory.tga");
    LoadParticle("Effect/legacy/sourceonly.part");
    LoadParticle("Effect/legacy/missing.part");
    DrawText("Inventory Full");
}
''')

    tree = SourceTree("CURRENT_SOURCE", "TARGET_RUNTIME_SOURCE", source)
    result = audit_summit_asset_migration_gap(project, client, tree)
    assert result["status"] == "PASS"
    rows = (project / "pt_build" / "summit_asset_migration" / "migration_queue.tsv").read_text(encoding="utf-8")
    assert "Effect/legacy/sourceonly.part" in rows
    assert "SOURCE_ONLY_PRESENT" in rows
    assert "Effect/legacy/missing.part" in rows
    assert "SOURCE_ONLY_MISSING" in rows
    ui = (project / "pt_build" / "summit_asset_migration" / "ui_text_candidates.tsv").read_text(encoding="utf-8")
    assert "Inventory Full" in ui
    cook = json.loads((project / "pt_build" / "summit_asset_migration" / "runtime_cook_plan.json").read_text(encoding="utf-8"))
    by_path = {x["client_path"].casefold(): x for x in cook["entries"]}
    assert by_path["effect/legacy/sourceonly.part"]["cook_action"] == "COPY_AS_IS_TO_COOKED_RUNTIME"
