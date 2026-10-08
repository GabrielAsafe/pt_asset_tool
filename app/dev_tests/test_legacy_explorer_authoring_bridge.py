from __future__ import annotations

import json
from pathlib import Path

from pt_asset_tool.legacy_management_web import query_legacy_management_report


def test_world_closure_rows_expose_exact_authoring_targets(tmp_path):
    project = tmp_path / "project"
    legacy_dir = project / "pt_build/devtest/legacy_management"
    census_dir = project / "pt_build/devtest/server_item_census"
    legacy_dir.mkdir(parents=True)
    census_dir.mkdir(parents=True)
    (census_dir / "result.json").write_text(json.dumps({
        "status": "PASS",
        "rows": [{"code": "BC123", "definition": "GameServer/OpenItem/Event/BC123.txt"}],
    }), encoding="utf-8")
    (legacy_dir / "result.json").write_text(json.dumps({
        "status": "PASS",
        "server_evidence": {
            "maps": [{"spm": "GameServer/Field/town.spm", "actors": [], "actor_count": 0, "item_codes": []}],
            "definitions": [
                {"kind": "MONSTER", "definition": "GameServer/Monster/Cuepy.inf", "item_references": [], "item_reference_count": 0, "zhoon_references": [], "reasons": [], "error": None},
                {"kind": "NPC", "definition": "GameServer/NPC/Shop.npc", "item_references": [], "item_reference_count": 0, "zhoon_references": [], "reasons": [], "error": None},
            ],
        },
        "client_item_visual_evidence": {"rows": [{"code": "BC123", "status": "REVIEW", "closures": []}]},
    }), encoding="utf-8")

    item = query_legacy_management_report(project, section="items")["rows"][0]
    assert item["authoring_kind"] == "ITEM"
    assert item["authoring_path"] == "GameServer/OpenItem/Event/BC123.txt"
    assert item["authoring_ready"] is True

    spm = query_legacy_management_report(project, section="maps")["rows"][0]
    assert spm["authoring_kind"] == "SPM"
    assert spm["authoring_path"] == "GameServer/Field/town.spm"

    defs = query_legacy_management_report(project, section="definitions")["rows"]
    assert [(x["authoring_kind"], x["authoring_path"]) for x in defs] == [
        ("MONSTER", "GameServer/Monster/Cuepy.inf"),
        ("NPC", "GameServer/NPC/Shop.npc"),
    ]


def test_world_closure_selection_is_wired_to_authoring_ui():
    root = Path(__file__).resolve().parents[1]
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    assert "runLegacyReviewAction" in js
    assert "legacyAuthoringOpenReviewTarget" in js
    assert "loaded explicitly from REVIEW" in js
    assert "switchLegacyTask(legacyTaskForKind(kind))" in js
    assert "await legacyAuthoringLoadExplorerSelection(section,row)" not in js
