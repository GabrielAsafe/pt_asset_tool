from __future__ import annotations

import json
from pathlib import Path

from pt_asset_tool.asset_contract_registry import source_registry
from pt_asset_tool.legacy_management_audit import audit_legacy_management
from pt_asset_tool.legacy_management_contracts import (
    classify_item_code,
    legacy_management_summary,
    parse_pritator_config,
    verify_management_root,
)
from pt_asset_tool.server_item_census import audit_server_item_bundles


def test_legacy_management_contract_is_exposed_through_source_registry():
    data = source_registry("legacy_management")
    assert data["format"] == "PT_LEGACY_MANAGEMENT_CONTRACT_V1"
    assert data["evidence"]["policy"] == "STATIC_EVIDENCE_ONLY_NEVER_EXECUTE_LEGACY_EXE"
    assert any(x["name"] == "PriTaTor_1.8.857.exe" for x in data["tools"])
    assert legacy_management_summary()["tool_count"] >= 7


def test_pritator_item_taxonomy_uses_longest_prefix_and_preserves_ambiguity():
    assert classify_item_code("WA121")["category"] == "Axe"
    assert classify_item_code("DA118")["category"] == "Armor"
    assert classify_item_code("DA223")["category"] == "Robe"
    assert classify_item_code("WS224")["category"] == "Sword"
    ambiguous = classify_item_code("SP101")
    assert ambiguous["status"] == "LEGACY_PREFIX_AMBIGUOUS"
    assert {x["category"] for x in ambiguous["candidates"]} == {"Quest Items", "Event Items"}


def test_pritator_config_parser_preserves_selector_sections(tmp_path: Path):
    cfg = tmp_path / "PriTaTor.Config.txt"
    cfg.write_text(
        "ItemSelector:\r\nArmor=da1\r\nBow=ws1,ws3\r\n<End>\r\n"
        "Server-Path=C:\\Server\\\r\nMax-Exp=1000000\r\n",
        encoding="cp1252",
    )
    out = parse_pritator_config(cfg)
    assert out["sections"]["ItemSelector"]["Armor"] == "da1"
    assert out["sections"]["ItemSelector"]["Bow"] == "ws1,ws3"
    assert out["globals"]["Server-Path"] == "C:\\Server\\"


def test_management_verification_never_executes_and_reports_missing(tmp_path: Path):
    out = verify_management_root(tmp_path)
    assert out["status"] == "PASS"
    assert out["executed_legacy_binaries"] is False
    assert out["missing_count"] > 0
    assert out["mismatch_count"] == 0


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("cp1252"))


def test_server_items_gain_historical_pritator_category(tmp_path: Path):
    project = tmp_path / "project"
    server = tmp_path / "server"
    project.mkdir()
    _write_text(server / "GameServer/OpenItem/WA121.txt", '*CODE "WA121"\r\n')
    out = audit_server_item_bundles(project, server, progress_every=0)
    row = out["rows"][0]
    assert row["legacy_management_category"]["category"] == "Axe"
    assert out["legacy_management_category_counts"]["Weapons::Axe"] == 1


def test_legacy_management_audit_reconstructs_spm_monster_drop_openitem_chain(tmp_path: Path):
    project = tmp_path / "project"
    server = tmp_path / "server"
    client = tmp_path / "client"
    tutorials = tmp_path / "tutorials"
    project.mkdir()
    tutorials.mkdir()

    _write_text(server / "GameServer/OpenItem/WA121.txt", '*CODE "WA121"\r\n')
    _write_text(client / "IMAGE/SinImage/Items/Weapon/itWA121.BMP", "icon")
    _write_text(client / "IMAGE/SinImage/Items/DropItem/itWA121.ase", "drop")
    _write_text(
        server / "GameServer/Monster/Cuepy.inf",
        '*J_NAME "Cuepy"\r\n*DROP 100 WA121\r\n*ZHOON "name\\Cuepy.zhoon"\r\n',
    )
    _write_text(server / "GameServer/Monster/name/Cuepy.zhoon", "Cuepy\r\n")
    _write_text(server / "GameServer/NPC/ricarden-store.npc", '*J_NAME "Store"\r\n*ITEM WA121\r\n')
    _write_text(server / "GameServer/Field/town.spm", '*ACTOR "Cuepy" 100\r\n')
    _write_text(tutorials / "drops.txt", "Drop WA121 WS224\r\n")

    out = audit_legacy_management(project, server_root=server, client_root=client, tutorial_root=tutorials, sample_limit=20)
    assert out["status"] == "PASS"
    ev = out["server_evidence"]
    assert ev["monster_item_reference_count"] == 1
    assert ev["npc_item_reference_candidate_count"] == 1
    assert ev["item_reference_without_openitem_count"] == 0
    assert ev["field_spm_count"] == 1
    assert ev["unresolved_spm_actor_count"] == 0
    assert ev["maps"][0]["actors"][0]["item_codes"] == ["WA121"]
    closure = out["client_item_visual_evidence"]
    assert closure["closed_count"] == 1
    assert closure["review_count"] == 0
    assert closure["rows"][0]["closures"][0]["inventory_icon"]["status"] == "PRESENT"
    assert closure["rows"][0]["closures"][0]["drop_model_ase"]["status"] == "PRESENT"
    assert out["tutorial_evidence"]["unique_item_codes"] == 2
    saved = json.loads(Path(out["report"]).read_text(encoding="utf-8"))
    assert saved["format"] == "PT_ASSET_LEGACY_MANAGEMENT_AUDIT_V1"
    assert saved["scope"]["legacy_executables_executed"] is False


def test_runtime_item_catalog_exposes_exact_sitem_semantics():
    from pt_asset_tool.item_runtime_catalog import lookup_item_runtime
    out = lookup_item_runtime("WA121")
    assert out["status"] == "SOURCE_VERIFIED"
    assert out["match_count"] == 1
    row = out["matches"][0]
    assert row["code"] == "WA121"
    assert row["item_file_path"] == "Weapon"
    assert row["class_value"] == 6
    assert row["dorp_item"] == "WA121"
    assert row["set_model_posi"] == 4
    assert row["sound_index"] == 1
    assert row["weapon_class"] == 1
    assert row["expected_client_paths"]["inventory_icon"] == "image/Sinimage/Items/Weapon/itWA121.bmp"
    assert row["expected_client_paths"]["drop_model_ase"] == "image/Sinimage/Items/DropItem/itWA121.ASE"


def test_runtime_item_catalog_preserves_dorpitem_case_when_it_differs_from_code():
    from pt_asset_tool.item_runtime_catalog import lookup_item_runtime
    row = lookup_item_runtime("OA101")["matches"][0]
    assert row["code"] == "OA101"
    assert row["dorp_item"] == "oa101"
    assert row["expected_client_paths"]["inventory_icon"].endswith("/itoa101.bmp")
