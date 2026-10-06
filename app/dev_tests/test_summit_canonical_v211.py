from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pt_asset_tool.canonical_authoring import atomic_update_definition, stage_canonical_authoring, stage_canonical_document_set, publish_canonical_source, publish_canonical_packs, deploy_canonical_runtime, restore_canonical_transaction, typed_patch_document, resolve_authoring_document
from pt_asset_tool.legacy_authoring import stage_authoring
from pt_asset_tool.summit_canonical import PACK_FILENAMES, SummitCanonicalContentProvider, build_semantic_catalog_v2, gameplay_config_browser, gameplay_reference_browser, localization_browser, query_canonical_resources, extended_content_browser


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "summit"
    content = root / "Content"
    _write_json(content / "CANONICAL_SOURCE.json", {"schema": "summit.canonical-source/v1", "families": {"maps": {"files": 2, "bytes": 123, "sha256": "a" * 64}}})
    packs = {}
    for name in PACK_FILENAMES:
        p = content / "packs" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(("pack:" + name).encode())
        packs[name] = {"path": f"packs/{name}", "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    _write_json(content / "BUILD.json", {"schema": "summit.canonical-content-build/v1", "packs": packs})

    _write_json(content / "canonical/text/resources/Servidor/GameServer/OpenItem/2_WA108.txt.json", {
        "schema": "summit.canonical-text-resource/v1",
        "family": "open_item_definition",
        "canonical_id": "item.2_wa108",
        "semantic": {
            "fields": {"Name": "Canonical Demon Hunter", "Code": "WA108", "Price": 100, "Bionic": True},
            "directives": [
                {"field": "Name", "token": "*NAME", "values": ["Canonical Demon Hunter"], "raw_values_hex": ["43616e6f6e6963616c2044656d6f6e2048756e746572"], "quoted": [True]},
                {"field": "Code", "token": "*CODE", "values": ["WA108"], "raw_values_hex": ["5741313038"], "quoted": [False]},
                {"field": "Price", "token": "*PRICE", "values": [100], "raw_values_hex": ["313030"], "quoted": [False]},
                {"field": "Bionic", "token": "*BIONIC", "values": [], "raw_values_hex": []},
            ],
            "unknown_tokens": [{"raw": "*CUSTOM 1"}],
        },
        "source": {"path": "Servidor/GameServer/OpenItem/2_WA108.txt"},
        "compatibility": {"Name_byte_capacity": 32},
    })
    _write_json(content / "canonical/text/resources/Servidor/GameServer/OpenItem/BC130.txt.json", {
        "schema": "summit.canonical-text-resource/v1",
        "family": "open_item_definition",
        "canonical_id": "item.bc130",
        "semantic": {
            "fields": {"Name": "", "Code": "BC130"},
            "directives": [
                {"field": "Name", "token": "*NAME", "values": [""], "raw_values_hex": [""], "quoted": [True]},
                {"field": "Code", "token": "*CODE", "values": ["BC130"], "raw_values_hex": ["4243313330"], "quoted": [False]},
            ],
            "unknown_tokens": [],
        },
        "source": {"path": "Servidor/GameServer/OpenItem/BC130.txt"},
        "compatibility": {"Name_byte_capacity": 32},
    })
    _write_json(content / "canonical/text/resources/Servidor/GameServer/Monster/Cuepy.inf.json", {
        "schema": "summit.canonical-text-resource/v1",
        "family": "monster_definition",
        "canonical_id": "monster.cuepy",
        "semantic": {"fields": {"Name": "Cuepy"}, "directives": [{"field": "Name", "values": ["Cuepy"], "raw_values_hex": ["4375657079"], "quoted": [True]}], "unknown_tokens": []},
    })
    _write_json(content / "canonical/text/resources/Servidor/GameServer/NPC/7crystal.npc.json", {
        "schema": "summit.canonical-text-resource/v1",
        "family": "npc_definition",
        "canonical_id": "npc.7crystal",
        "semantic": {"fields": {"Name": "Traveler Dela"}, "directives": [{"field": "Name", "values": ["Traveler Dela"], "raw_values_hex": ["54726176656c65722044656c61"], "quoted": [True]}], "unknown_tokens": []},
    })
    _write_json(content / "canonical/item_profiles/client.items.json", {"profile": "client", "items": [{"code": "WA108"}, {"code": "BC130"}]})
    _write_json(content / "canonical/item_profiles/server.items.json", {"profile": "server", "items": [{"code": "WA108"}]})
    _write_json(content / "canonical/maps/client.maps.json", {"profile": "client", "legacy_dynamic_field": {"field_code": 54, "strategy": "append_after_static"}, "maps": [{"canonical_id": "map.fore_3", "legacy_field_code": 0, "name": "Forest Client"}, {"canonical_id": "map.field53", "legacy_field_code": 53, "name": "Field 53 Client"}]})
    _write_json(content / "canonical/maps/server.maps.json", {"profile": "server", "legacy_dynamic_field": {"field_code": 54, "strategy": "append_after_static"}, "maps": [{"canonical_id": "map.fore_3", "legacy_field_code": 0, "name": "Forest Server"}, {"canonical_id": "map.field53", "legacy_field_code": 53, "name": "Field 53 Server"}]})
    _write_json(content / "canonical/text/resources/Servidor/Configs/game.ini.json", {
        "schema": "summit.canonical-text-resource/v1", "id": "text.game", "kind": "ini_config",
        "selection_reason": "immutable_gameplay_config", "source": {"legacy_path": "Servidor/Configs/game.ini"},
        "semantic": {"entries": [{"line": 1, "section": "", "key": "A", "value": "1"}]},
    })
    _write_json(content / "canonical/text/resources/cliente/help.ini.json", {
        "schema": "summit.canonical-text-resource/v1", "id": "text.help", "kind": "ini_config",
        "selection_reason": "ui_text_config", "source": {"legacy_path": "cliente/help.ini"},
        "semantic": {"entries": [{"line": 1, "section": "", "key": "H", "value": "x"}]},
    })
    _write_json(content / "canonical/text/index.json", {"schema": "summit.canonical-text-index/v1", "documents": 6})
    _write_json(content / "canonical/text/localization/report.json", {"schema": "summit.localization-report/v1", "keys": 2, "locales": {"en": 2, "pt-BR": 2}})
    _write_json(content / "canonical/text/localization/pt-BR.json", {
        "schema": "summit.localization-catalog/v1", "locale": "pt-BR",
        "entries": [{"key": "a", "text": "Olá", "quality": "translated", "source": "text.a"}, {"key": "b", "text": "Mundo", "quality": "translated", "source": "text.b"}],
    })
    for folder in ("stage_spawns", "stage_start_points", "fixed_npcs", "gameplay_reference"):
        (content / "canonical" / folder).mkdir(parents=True, exist_ok=True)
    _write_json(content / "canonical/gameplay_reference/quests/priston_tale_quests.pt-BR.json", {
        "schema": "summit.quest-codex/v1",
        "progression_quests": [{"id": "q1"}, {"id": "q2"}],
        "daily_quests": [{"id": "q3"}],
        "aline_daily_quests": [{"id": "q4"}],
        "weekly_quests": [{"id": "q5"}],
    })
    _write_json(content / "canonical/gameplay_reference/quests/runtime_bindings.json", {
        "schema": "summit.quest-runtime-bindings/v1",
        "bindings": [{"quest_id": "q1", "supported": True}, {"quest_id": "q2", "supported": True}, {"quest_id": "q5", "supported": False}],
    })
    _write_json(content / "canonical/gameplay_reference/mix/priston_tale_mix_table.pt-BR.json", {
        "schema": "summit.mix-guide/v1",
        "recipes": [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}],
    })
    _write_json(content / "canonical/commerce/coin_shop.json", {
        "schema": "summit.coin-shop-catalog/v1",
        "shops": {"coin": [{"code": "WA108", "section": 1, "price": 100}], "time": [{"code": "BC130", "section": 1, "price": 10}]},
        "policy": {"quest_only_item_codes": ["QW103", "QW106"]},
    })
    _write_json(content / "canonical/commerce/npc_shop_overrides.json", {
        "schema": "summit.npc-shop-overrides/v1", "overrides": []
    })
    _write_json(content / "canonical/model_configs/models/char.monster.cuepy.json", {
        "schema": "summit.model-config/v1", "schema_version": 1, "id": "model.char.monster.cuepy", "semantic": {}
    })
    _write_json(content / "canonical/equipment_sets/equipment_sets.json", {
        "schema": "summit.equipment-sets/v1", "schema_version": 1, "sets": [{"id": "set.test", "pieces": [], "bonuses": []}]
    })
    _write_json(content / "canonical/head_cosmetics/head_cosmetics.json", {
        "schema": "summit.head-cosmetics/v1", "schema_version": 1, "cosmetics": []
    })
    _write_json(content / "canonical/world_story/campaigns.json", {
        "schema": "summit.world-story-campaigns/v1", "schema_version": 1, "campaigns": []
    })
    _write_json(content / "canonical/world_phases/world_phases.json", {
        "schema": "summit.world-phases/v1", "schema_version": 1, "worlds": []
    })
    _write_json(content / "canonical/covenant_altars/placement_plan.json", {
        "schema": "summit.covenant-altar-placement-plan/v1", "schema_version": 1, "placements": []
    })
    _write_json(content / "canonical/gameplay_balance/experience.json", {
        "schema": "summit.experience-balance/v1", "schema_version": 1, "party": {"max_members": 8}
    })
    return root


def test_provider_fails_closed_on_unknown_authority_schema(tmp_path):
    root = _source(tmp_path)
    _write_json(root / "Content/CANONICAL_SOURCE.json", {"schema": "summit.canonical-source/v999"})
    with pytest.raises(ValueError, match="CANONICAL_SOURCE_SCHEMA_UNSUPPORTED"):
        SummitCanonicalContentProvider(root)


def test_semantic_catalog_v2_uses_canonical_identity_and_alias_overlay(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    catalog = build_semantic_catalog_v2(provider)
    assert catalog["authority"] == "SUMMIT_CANONICAL_SOURCE"
    assert catalog["counts"]["items"] == 2
    by_id = {x["canonical_id"]: x for x in catalog["items"]}
    # Existing IDs may use the V2.9 pt-BR/name overlay, but existence comes from canonical source.
    assert by_id["item.2_wa108"]["display_name_source"] == "LEGACY_PT_BR_ALIAS_OVERLAY"
    # Source-only IDs never receive an invented friendly name.
    assert by_id["item.bc130"]["display_name"] == "BC130 — item.bc130"
    assert by_id["item.bc130"]["display_warning"] == "MISSING_DISPLAY_NAME"
    assert by_id["item.bc130"]["in_client_profile"] is True
    assert by_id["item.bc130"]["in_server_profile"] is False
    assert catalog["counts"]["maps_client"] == 2
    assert catalog["counts"]["maps_server"] == 2
    assert sum(1 for x in catalog["maps"] if x["dynamic_reserved_entry"]) == 0
    assert {x["field_code"] for x in catalog["maps"]} == {0, 53}
    assert {x["dynamic_field_code"] for x in catalog["maps"]} == {54}
    assert catalog["dynamic_field_policy"] == "APPEND_AFTER_STATIC_CATALOG"
    assert catalog["counts"]["gameplay_configs"] == 1
    assert catalog["counts"]["gameplay_config_entries"] == 1
    assert catalog["counts"]["text_resources"] == 6


def test_atomic_definition_writer_updates_fields_and_directives_and_preserves_provenance(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    doc = provider.find_definition("item.2_wa108").data
    before_unknown = doc["semantic"]["unknown_tokens"]
    before_source = doc["source"]
    before_compat = doc["compatibility"]
    edited = atomic_update_definition(doc, {"Name": "New Axe", "Price": 999})
    assert edited["semantic"]["fields"]["Name"] == "New Axe"
    name_directive = next(x for x in edited["semantic"]["directives"] if x.get("field") == "Name")
    price_directive = next(x for x in edited["semantic"]["directives"] if x.get("field") == "Price")
    assert name_directive["values"] == ["New Axe"]
    assert bytes.fromhex(name_directive["raw_values_hex"][0]).decode("cp1252") == "New Axe"
    assert price_directive["values"] == [999]
    assert bytes.fromhex(price_directive["raw_values_hex"][0]).decode("ascii") == "999"
    assert edited["semantic"]["unknown_tokens"] == before_unknown
    assert edited["source"] == before_source
    assert edited["compatibility"] == before_compat


def test_atomic_definition_writer_enforces_encoding_and_capacity(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    doc = provider.find_definition("item.2_wa108").data
    with pytest.raises(ValueError, match="LEGACY_ENCODING_UNREPRESENTABLE"):
        atomic_update_definition(doc, {"Name": "Sword 🗡"})
    with pytest.raises(ValueError, match="LEGACY_FIELD_BYTE_CAPACITY_EXCEEDED"):
        atomic_update_definition(doc, {"Name": "X" * 40})


def test_atomic_definition_writer_preserves_presence_only_boolean_directive(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    doc = provider.find_definition("item.2_wa108").data
    edited = atomic_update_definition(doc, {"Bionic": True})
    directive = next(x for x in edited["semantic"]["directives"] if x.get("field") == "Bionic")
    assert directive["values"] == []
    assert directive["raw_values_hex"] == []
    with pytest.raises(ValueError, match="PRESENCE_FLAG_FALSE"):
        atomic_update_definition(doc, {"Bionic": False})


def test_provider_separates_declared_and_asset_tool_family_fingerprints(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    status = provider.status()
    assert status["declared_family_fingerprints"]["maps"]["sha256"] == "a" * 64
    assert status["computed_family_fingerprints"]["maps"]["sha256"] != "a" * 64
    assert status["canonical_file_inventory"]["files"] > 0


def test_specialized_gameplay_config_and_localization_browsers(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    configs = gameplay_config_browser(provider)
    assert configs["documents"] == 1
    assert configs["entries"] == 1
    assert configs["rows"][0]["canonical_id"] == "text.game"
    ini_rows = query_canonical_resources(provider, family="ini_config", limit=20)["rows"]
    by_id = {x["canonical_id"]: x for x in ini_rows}
    assert by_id["text.game"]["authoring_kind"] == "GAMEPLAY_CONFIG"
    assert by_id["text.help"]["authoring_kind"] is None
    assert by_id["text.help"]["read_only"] is True
    loc = localization_browser(provider, locale="pt-BR", q="olá")
    assert loc["total"] == 1
    assert loc["rows"][0]["key"] == "a"
    assert loc["publish_gate"]["production_publish"] == "BLOCKED"



def test_gameplay_reference_browser_exposes_reference_only_quest_and_mix_summary(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    result = gameplay_reference_browser(provider)
    assert result["authority"] == "REFERENCE_ONLY"
    assert result["quest_runtime_authority"] is False
    assert result["summary"]["quest_codex"]["quests"] == 5
    assert result["summary"]["quest_codex"]["runtime_bindings"] == 3
    assert result["summary"]["quest_codex"]["supported_runtime_bindings"] == 2
    assert result["summary"]["mix_guide"]["recipes"] == 3


def test_stage_copies_complete_canonical_tree_and_records_provenance_without_running_source_tools(tmp_path):
    root = _source(tmp_path)
    provider = SummitCanonicalContentProvider(root)
    project = tmp_path / "asset_tool"
    project.mkdir()
    result = stage_canonical_authoring(project, provider, {
        "kind": "ITEM",
        "canonical_id": "item.2_wa108",
        "patch": {"fields": {"Name": "Staged Axe"}},
    }, run_validation=False, run_build=False)
    manifest = result["manifest"]
    stage_root = Path(manifest["stage_root"])
    assert (stage_root / "canonical/item_profiles/client.items.json").is_file()
    assert (stage_root / "canonical/maps/client.maps.json").is_file()
    assert manifest["source_pre_sha256"] != manifest["staged_post_sha256"]
    assert manifest["canonical_source_sha256"] == provider.status()["canonical_source_sha256"]
    assert manifest["publish_phases"] == ["SOURCE_JSON", "SOURCE_PACKS", "CLIENT_SERVER_RUNTIME_DEPLOY"]
    assert Path(manifest["source_canonical_file_hash_manifest"]).is_file()
    assert Path(manifest["staged_canonical_file_hash_manifest"]).is_file()
    assert manifest["source_canonical_file_inventory"]["files"] == manifest["staged_canonical_file_inventory"]["files"]
    assert manifest["source_canonical_file_inventory"]["sha256"] != manifest["staged_canonical_file_inventory"]["sha256"]


def test_legacy_stage_is_disabled_when_canonical_mode_is_active(tmp_path, monkeypatch):
    root = _source(tmp_path)
    project = tmp_path / "project"
    client = tmp_path / "client"
    server = tmp_path / "server"
    project.mkdir(); client.mkdir(); server.mkdir()
    monkeypatch.setenv("PT_SOURCE_ROOT", str(root))
    with pytest.raises(ValueError, match="LEGACY_AUTHORITATIVE_WRITER_DISABLED_IN_CANONICAL_MODE"):
        stage_authoring(project, server, client, {"kind": "SPM", "mode": "EDIT", "path": "GameServer/Field/a.spm", "patch": {"action": "ADD_ACTOR"}})


def test_canonical_contract_graph_keeps_profiles_and_dynamic_append_policy_explicit(tmp_path):
    from pt_asset_tool.summit_canonical import build_canonical_contract_graph
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    graph = build_canonical_contract_graph(provider, include_documents=False)
    keys = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
    assert ("canonical:map_profile:client", "canonical:pack:maps_client.smap", "COMPILES_TO") in keys
    assert ("canonical:map_profile:server", "canonical:pack:maps_server.smap", "COMPILES_TO") in keys
    assert ("canonical:source", "canonical:map_dynamic_append", "DECLARES_DYNAMIC_FIELD_POLICY") in keys
    assert graph["metadata"]["profile_collapse_forbidden"] is True


def test_publish_source_rejects_diagnostic_stage_without_validated_build(tmp_path):
    from pt_asset_tool.canonical_authoring import publish_canonical_source
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    staged = stage_canonical_authoring(project, provider, {
        "kind": "ITEM", "canonical_id": "item.2_wa108", "patch": {"fields": {"Price": 777}},
    }, run_validation=False, run_build=False)
    with pytest.raises(ValueError, match="REQUIRES_SCHEMA_VALIDATION_PASS"):
        publish_canonical_source(project, staged["manifest"], confirm="PUBLISH CANONICAL SOURCE")


def test_map_profile_compare_and_field53_is_normal_static_map(tmp_path):
    from pt_asset_tool.summit_canonical import compare_map_profiles
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    cmp = compare_map_profiles(provider, "map.fore_3")
    assert cmp["profiles_present"] == ["CLIENT", "SERVER"]
    assert any(x["field"] == "name" for x in cmp["differences"])
    assert cmp["dynamic_field_policy"] == "APPEND_AFTER_STATIC_CATALOG"
    assert cmp["dynamic_field_codes"] == {"CLIENT": 54, "SERVER": 54}
    client_doc = provider.map_profiles()["client"]["data"]
    edited = typed_patch_document("MAP", client_doc, {"fields": {"name": "Renamed Client"}}, canonical_id="map.fore_3")
    assert edited["maps"][0]["name"] == "Renamed Client"
    field53 = typed_patch_document("MAP", client_doc, {"fields": {"name": "Editable Field 53"}}, canonical_id="map.field53")
    assert field53["maps"][1]["name"] == "Editable Field 53"


def test_generic_canonical_text_is_read_only_without_typed_writer(tmp_path):
    from pt_asset_tool.canonical_authoring import typed_patch_document
    with pytest.raises(ValueError, match="BROWSER_READ_ONLY"):
        typed_patch_document("CANONICAL_TEXT", {"x": 1}, {"set": {"x": 2}})


def test_extended_domains_browser_and_fixed_document_authoring(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    result = extended_content_browser(provider)
    by_id = {row["id"]: row for row in result["rows"]}
    assert by_id["coin_shop"]["present"] is True
    assert by_id["coin_shop"]["entries"] == 2
    assert by_id["model_configs"]["documents"] == 1
    assert by_id["equipment_sets"]["schema"] == "summit.equipment-sets/v1"

    kind, path, doc = resolve_authoring_document(provider, {"kind": "EQUIPMENT_SETS"})
    assert kind == "EQUIPMENT_SETS"
    assert path.name == "equipment_sets.json"
    edited = typed_patch_document(kind, doc, {"set": {"sets.0.id": "set.renamed"}})
    assert edited["sets"][0]["id"] == "set.renamed"
    with pytest.raises(ValueError, match="SCHEMA_IMMUTABLE"):
        typed_patch_document(kind, doc, {"set": {"schema": "bad/v1"}})

    mkind, mpath, mdoc = resolve_authoring_document(provider, {"kind": "MODEL_CONFIG", "canonical_id": "model.char.monster.cuepy"})
    assert mkind == "MODEL_CONFIG"
    assert mpath.name == "char.monster.cuepy.json"
    assert mdoc["schema"] == "summit.model-config/v1"


def test_v211_ui_and_api_surfaces_are_wired():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    assert 'V2.12 · Summit Canonical Source' in html
    assert 'canonicalV211ItemProfiles' in html
    assert 'canonicalV211References' in html
    assert 'canonicalV211Domains' in html
    assert 'COIN_SHOP_CATALOG' in html
    assert 'WORLD_PHASES' in html
    assert 'canonicalV211GameplayConfig' in html
    assert 'canonicalV211Localization' in html
    assert 'canonicalV211CompareMap' in html
    assert '/api/canonical/stage' in js
    assert '/api/canonical/map-compare' in js
    assert 'u.path == "/api/canonical/stage"' in py
    assert 'path == "/api/canonical/resources"' in py
    assert 'path == "/api/canonical/gameplay-reference"' in py
    assert 'path == "/api/canonical/domains"' in py
    assert 'path == "/api/canonical/gameplay-config"' in py
    assert 'path == "/api/canonical/localization"' in py


def test_atomic_document_set_can_create_spawn_and_update_index_without_touching_source(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    project = tmp_path / "project"; project.mkdir()
    index_path = provider.canonical_root / "stage_spawns/index.json"
    _write_json(index_path, {"schema": "summit.stage-spawn-index/v1", "documents": []})
    doc = {"schema": "summit.stage-spawn/v1", "schema_version": 1, "id": "spawn.lost3", "logical_path": "GameServer/Field/lost3.ASE.spm", "legacy_source": {"path": "Servidor/GameServer/Field/lost3.ASE.spm", "sha256": "1" * 64}, "limit_max": 300, "delay": {"shift": 1, "milliseconds": 2000}, "open_limit": 1, "actors": [], "bosses": []}
    idx = {"schema": "summit.stage-spawn-index/v1", "documents": [{"id": "spawn.lost3", "logical_path": "GameServer/Field/lost3.ASE.spm", "json_path": "spawns/GameServer/Field/lost3.ASE.spm.json"}]}
    result = stage_canonical_document_set(project, provider, [
        {"relative_path": "canonical/stage_spawns/spawns/GameServer/Field/lost3.ASE.spm.json", "document": doc},
        {"relative_path": "canonical/stage_spawns/index.json", "document": idx},
    ], kind="STAGE_SPAWN", canonical_id="spawn.lost3", run_validation=False, run_build=False)
    m = result["manifest"]
    assert len(m["source_changes"]) == 2
    assert m["source_changes"][0]["source_existed"] is False
    assert not (provider.canonical_root / "stage_spawns/spawns/GameServer/Field/lost3.ASE.spm.json").exists()
    assert Path(m["source_changes"][0]["staged_json"]).is_file()
    assert json.loads(index_path.read_text(encoding="utf-8"))["documents"] == []


def test_runtime_deploy_is_role_aware_and_transactionally_restorable(tmp_path):
    provider = SummitCanonicalContentProvider(_source(tmp_path))
    project = tmp_path / "project"; project.mkdir()
    staged = stage_canonical_authoring(project, provider, {
        "kind": "ITEM", "canonical_id": "item.2_wa108", "patch": {"fields": {"Price": 101}},
    }, run_validation=False, run_build=False)
    m = staged["manifest"]
    stage_root = Path(m["stage_root"])
    # Build-independent test fixture: use the current verified packs as the staged pack set.
    stage_packs = stage_root / "packs"; stage_packs.mkdir(exist_ok=True)
    m["pack_hashes"] = {}
    for name in PACK_FILENAMES:
        data = (provider.packs_root / name).read_bytes()
        (stage_packs / name).write_bytes(data)
        m["pack_hashes"][name] = hashlib.sha256(data).hexdigest()
    (stage_root / "BUILD.json").write_bytes(provider.build_path.read_bytes())
    m["validation"] = {"status": "PASS"}
    m["build"] = {"status": "PASS", "pack_hashes": dict(m["pack_hashes"])}
    m["staged_build_manifest"] = {"status": "PASS"}
    publish_canonical_source(project, m, confirm="PUBLISH CANONICAL SOURCE")
    publish_canonical_packs(project, m, confirm="PUBLISH CANONICAL PACKS")

    client = tmp_path / "cliente"; server = tmp_path / "Servidor"; client.mkdir(); server.mkdir()
    stale = client / "Content/packs/definitions_server.scfg"; stale.parent.mkdir(parents=True); stale.write_bytes(b"old-server-pack")
    result = deploy_canonical_runtime(project, m, confirm="DEPLOY CANONICAL RUNTIME", client_root=client, server_root=server)
    assert result["deploy_phase"] == "APPLIED"
    assert (client / "Content/packs/definitions_client.scfg").is_file()
    assert not (client / "Content/packs/definitions_server.scfg").exists()
    assert (server / "Content/packs/definitions_server.scfg").is_file()
    assert json.loads((client / "Content/RUNTIME_CONTENT.json").read_text())["role"] == "client"
    restored = restore_canonical_transaction(project, m, confirm="RESTORE CANONICAL TRANSACTION")
    assert restored["deploy_phase"] == "RESTORED"
    assert stale.read_bytes() == b"old-server-pack"


def test_canonical_tool_failure_surfaces_tool_output(tmp_path):
    import sys
    import pt_asset_tool.canonical_authoring as ca
    script = tmp_path / "fail_tool.py"
    script.write_text("import sys\nprint('precise validator failure')\nsys.exit(7)\n", encoding="utf-8")
    log = []
    with pytest.raises(RuntimeError) as exc:
        ca._run([sys.executable, str(script)], cwd=tmp_path, log=log)
    assert "CANONICAL_TOOL_FAILED:fail_tool.py:7" in str(exc.value)
    assert "precise validator failure" in str(exc.value)
    assert log[0]["returncode"] == 7


def test_document_set_marks_localization_change_for_publish_gate(tmp_path):
    root = _source(tmp_path)
    provider = SummitCanonicalContentProvider(root)
    project = tmp_path / "project"; project.mkdir()
    source_doc = json.loads((root / "Content/canonical/text/localization/pt-BR.json").read_text(encoding="utf-8"))
    source_doc["entries"].append({"key": "monster.new.name", "text": "Novo", "quality": "translated", "source": "monster.new"})
    result = stage_canonical_document_set(
        project, provider,
        [{"relative_path": "canonical/text/localization/pt-BR.json", "document": source_doc}],
        kind="MONSTER_DEPENDENCY_SET", run_validation=False, run_build=False,
    )
    assert result["manifest"]["localization_edit"] is True


def test_document_set_captures_materialized_localization_json_deltas(monkeypatch, tmp_path):
    import pt_asset_tool.canonical_authoring as ca
    root = _source(tmp_path)
    provider = SummitCanonicalContentProvider(root)
    project = tmp_path / "project"; project.mkdir()
    pt = json.loads((root / "Content/canonical/text/localization/pt-BR.json").read_text(encoding="utf-8"))
    pt["entries"].append({"key": "monster.new.name", "text": "Novo", "quality": "translated", "source": "monster.new"})

    def fake_validate(_provider, stage_root):
        loc = stage_root / "canonical/text/localization"
        _write_json(loc / "en.json", {
            "schema": "summit.localization-catalog/v1", "schema_version": 1,
            "locale": "en", "fallback_locale": None,
            "entries": [{"key": "monster.new.name", "text": "New", "quality": "translated", "source": "monster.new"}],
        })
        report = json.loads((loc / "report.json").read_text(encoding="utf-8"))
        report["keys"] = 3
        _write_json(loc / "report.json", report)
        return {"status": "PASS", "commands": []}

    monkeypatch.setattr(ca, "validate_staged_canonical", fake_validate)
    result = ca.stage_canonical_document_set(
        project, provider,
        [{"relative_path": "canonical/text/localization/pt-BR.json", "document": pt}],
        kind="MONSTER_DEPENDENCY_SET", run_validation=True, run_build=False,
    )
    rows = {x["canonical_json_path"]: x for x in result["manifest"]["source_changes"]}
    assert "canonical/text/localization/pt-BR.json" in rows
    assert "canonical/text/localization/en.json" in rows
    assert "canonical/text/localization/report.json" in rows
    assert rows["canonical/text/localization/en.json"]["source_existed"] is False
    assert rows["canonical/text/localization/report.json"]["generated_by_stage"] == "materialize_localization_catalog.py"
