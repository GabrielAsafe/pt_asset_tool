from __future__ import annotations

import csv
import json
from pathlib import Path

from pt_asset_tool.catalog_character_index import build_character_index
from pt_asset_tool.ui_catalog import CatalogIndex, UIStateStore, infer_folder_bucket, infer_semantics


def _inventory(client: Path) -> dict:
    return {
        "canonical_client_root": str(client.resolve()),
        "records": [
            {
                "relative_path": "char/tmABCD/CtmbC010.smd",
                "extension": ".smd",
                "size": 180700,
                "mtime_ns": 1,
                "kind": "SMD_MODEL_062_RIGID_PHYSIQUE",
                "compatibility_family": "SMD_MODEL_062_RIGID_PHYSIQUE",
                "texture_refs": ["Ava_M_03.tga"],
            },
            {"relative_path": "char/tmABCD/Cc010.inx", "extension": ".inx", "size": 10, "mtime_ns": 1},
            {"relative_path": "char/tmABCD/Ava_M_03.tga", "extension": ".tga", "size": 10, "mtime_ns": 1},
            {"relative_path": "char/tmABCD/TmbC20_3.TGA", "extension": ".tga", "size": 10, "mtime_ns": 1},
            {"relative_path": "wav/Effects/player/Pikeman/hit.wav", "extension": ".wav", "size": 10, "mtime_ns": 1},
        ],
    }


def test_character_ownership_prefers_config_and_dependency_over_filename(tmp_path: Path):
    client = tmp_path / "client"
    client.mkdir()
    inv = _inventory(client)
    pairing = tmp_path / "inx_physical_pairing.csv"
    with pairing.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["inx", "model_smd"])
        w.writeheader()
        w.writerow({"inx": "char/tmABCD/Cc010.inx", "model_smd": "char/tmABCD/CtmbC010.smd"})

    idx = build_character_index(inv, pairing, {})
    by = idx["by_path"]
    assert by["char/tmabcd/ctmbc010.smd"]["owner"] == "Pikeman"
    assert by["char/tmabcd/ava_m_03.tga"]["owner"] == "Pikeman"
    assert any("SMD_MATERIAL_TEXLINK" in x for x in by["char/tmabcd/ava_m_03.tga"]["evidence"])

    # Community/file naming can suggest a class, but never assigns ownership alone.
    ambiguous = by["char/tmabcd/tmbc20_3.tga"]
    assert ambiguous["status"] == "FILENAME_HINT_ONLY"
    assert ambiguous["owner"] == ""
    assert ambiguous["filename_hint"] == "Pikeman"


def test_audio_stays_audio_and_folder_facet_does_not_become_character_name():
    category, role = infer_semantics("wav/Effects/player/Pikeman/hit.wav", ".wav")
    assert category == "AUDIO"
    assert role == "CHARACTER_AUDIO"
    label, root = infer_folder_bucket("wav/Effects/player/Pikeman/hit.wav", category)
    assert label.casefold() == "wav/effects/player"
    assert root.casefold() == "wav/effects/player"


def test_character_filter_and_manual_override_are_separate_from_folder(tmp_path: Path):
    client = tmp_path / "client"
    client.mkdir()
    inv_path = tmp_path / "asset_inventory.json"
    inv_path.write_text(json.dumps(_inventory(client)), encoding="utf-8")
    state = UIStateStore(tmp_path / "ui_state.json")
    catalog = CatalogIndex(client, state)
    catalog.rebuild_from_inventory(inv_path)
    catalog.apply_character_index({
        "by_path": {
            "char/tmabcd/ctmbc010.smd": {
                "owner": "Pikeman", "status": "PROVEN", "evidence": ["SOURCE_CONFIG_FAMILY:Cc010.inx"], "candidates": ["Pikeman"]
            }
        }
    })
    report = catalog.query(character="Pikeman")
    assert [x["path"] for x in report["items"]] == ["char/tmABCD/CtmbC010.smd"]

    changed = catalog.apply_state_update("char/tmABCD/Ava_M_03.tga", {"character_override": "Archer"})
    assert changed["character"] == "Archer"
    assert catalog.query(character="Archer")["items"][0]["path"] == "char/tmABCD/Ava_M_03.tga"


def test_frontend_refreshes_filters_immediately_and_exposes_smd_preview_and_dropdowns():
    root = Path(__file__).resolve().parents[1]
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    assert 'id="character"' in html
    assert "'#character'" in js
    assert "el.addEventListener('input'" in js
    assert "el.addEventListener('change'" in js
    assert "queueMicrotask" in js
    assert "smdPreviewStateHtml" in js
    assert "/api/smd-preview-status" in js
    assert "character_override" in js
    assert "<select id=catOverride>" in js
    assert "<select id=roleOverride>" in js
    assert "<select id=characterOverride>" in js


def test_smd_preview_pipeline_reuses_existing_importer_and_writes_only_pt_build():
    root = Path(__file__).resolve().parents[1]
    preview = (root / "pt_asset_tool/smd_preview.py").read_text(encoding="utf-8")
    renderer = (root / "pt_asset_tool/legacy_runtime/pt_catalog_smd_render.py").read_text(encoding="utf-8")
    assert 'pt_smd_blender_import_v4_generic.py' in preview
    assert 'blender_runtime_info' in preview
    assert 'pt_build" / "previews" / "smd_catalog' in preview
    assert 'client_modified": False' in preview
    assert 'bpy.ops.render.render(write_still=True)' in renderer
