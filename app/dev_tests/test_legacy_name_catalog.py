from __future__ import annotations

from pathlib import Path

import pytest

from pt_asset_tool.legacy_apps.selections import selection_catalog
from pt_asset_tool.legacy_authoring import authoring_capabilities, authoring_workspace_guide, stage_authoring
from pt_asset_tool.legacy_name_catalog import (
    FORMAT,
    authoring_name_catalog,
    lookup_semantic_ref,
    semantic_binding_for_spec,
    semantic_matches_for_path,
    semantic_monster_matches_for_model,
    semantic_related_bindings_for_spec,
)


def _roots(tmp_path: Path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    server = tmp_path / "server"
    project.mkdir(); client.mkdir(); server.mkdir()
    return project, client, server


def test_semantic_catalog_contract_counts_match_uploaded_map():
    c = authoring_name_catalog()
    assert c["format"] == FORMAT
    assert c["counts"] == {
        "unique_1x1": 2607,
        "items": 1893,
        "mobs": 383,
        "npcs": 175,
        "maps": 53,
        "spawn_stages": 54,
        "texts": 779,
        "ambiguous_visible_names": 230,
    }
    assert len(c["items"]) == 1893
    assert len(c["mobs"]) == 383
    assert len(c["npcs"]) == 175
    assert len(c["spawn_stages"]) == 54
    assert len(c["ambiguous"]) == 230




def test_slab_reverse_catalog_has_unique_ptbr_aliases_for_exact_monster_models():
    expected = {
        r"char\monster\LEngineer\LEngineer.ini": ("monster.slab_114_engenheiro_do_laborat_u00f3rio", "Engenheiro do Laboratório"),
        r"char\monster\ITechnician\ITechnician.ini": ("monster.slab_114_t_u00e9cnico_do_laborat_u00f3rio", "Técnico do Laboratório"),
        r"char\monster\LTechnician\LTechnician.ini": ("monster.slab_114_t_u00e9cnico_invasor", "Técnico Invasor"),
        r"char\monster\IBomber\IBomber.ini": ("monster.slab_115_bombardeiro_invasor", "Bombardeiro Invasor"),
        r"char\monster\ISoldier\ISoldier.ini": ("monster.slab_115_soldado_invasor", "Soldado Invasor"),
    }
    for model_file, (canonical_id, display_name) in expected.items():
        rows = semantic_monster_matches_for_model(model_file)
        assert [(row["canonical_id"], row["display_name"]) for row in rows] == [(canonical_id, display_name)]

def test_ricarten_resolves_to_village2_field_files():
    row = lookup_semantic_ref("map.village_2")
    assert row is not None
    assert row["display_name"] == "Ricarten"
    assert row["internal_name"] == "village-2"
    assert row["field_code"] == 3
    assert row["logical_spm"] == "GameServer/Field/Village-2.ase.spm"
    assert row["logical_spp"] == "GameServer/Field/Village-2.ase.spp"
    assert row["logical_spc"] == "GameServer/Field/Village-2.ase.spc"
    matches = semantic_matches_for_path("GameServer/Field/Village-2.ase.spm")
    assert {x["canonical_id"] for x in matches} >= {"map.village_2", "spawn.village_2"}


def test_duplicate_runtime_item_code_keeps_distinct_canonical_identity():
    c = authoring_name_catalog()
    rows = [x for x in c["items"] if x["code"] == "WS122"]
    assert len(rows) == 3
    assert {x["canonical_id"] for x in rows} == {
        "item.uws122_revenge_bow",
        "item.ws122",
        "item.zquest_ws122",
    }
    assert len({x["logical_path"] for x in rows}) == 3


def test_ambiguous_visible_item_name_is_marked_not_collapsed():
    c = authoring_name_catalog()
    rows = [x for x in c["items"] if x["display_name"] == "AK-47"]
    assert len(rows) == 2
    assert all(x["visible_name_ambiguous"] is True for x in rows)
    assert {x["code"] for x in rows} == {"TW112", "WS161"}


def test_semantic_binding_requires_canonical_kind_path_and_item_code():
    good = semantic_binding_for_spec("ITEM", {
        "kind": "ITEM",
        "mode": "EDIT",
        "path": "GameServer/OpenItem/WA121.txt",
        "semantic_ref": {"canonical_id": "item.wa121"},
        "fields": {"code": "WA121"},
    })
    assert good and good["canonical_id"] == "item.wa121"
    with pytest.raises(ValueError, match="SEMANTIC_PATH_MISMATCH"):
        semantic_binding_for_spec("ITEM", {
            "kind": "ITEM",
            "mode": "CREATE",
            "path": "GameServer/OpenItem/Other.txt",
            "semantic_ref": {"canonical_id": "item.wa121"},
            "fields": {"code": "WA121"},
        })
    with pytest.raises(ValueError, match="SEMANTIC_ITEM_CODE_MISMATCH"):
        semantic_binding_for_spec("ITEM", {
            "kind": "ITEM",
            "mode": "CREATE",
            "path": "GameServer/OpenItem/WA121.txt",
            "semantic_ref": {"canonical_id": "item.wa121"},
            "fields": {"code": "WS122"},
        })


def test_related_semantic_refs_validate_domain_and_preserve_identity():
    rows = semantic_related_bindings_for_spec("SPM", {
        "payload": {"actors": [{"name": "Arqueira das Cinzas", "weight": 100}]},
        "semantic_related_refs": [{"role": "ACTOR", "canonical_id": "monster.100_arqueira_das_cinzas"}],
    })
    assert rows[0]["category"] == "MONSTER"
    assert rows[0]["display_name"] == "Arqueira das Cinzas"
    with pytest.raises(ValueError, match="SEMANTIC_RELATED_KIND_MISMATCH"):
        semantic_related_bindings_for_spec("SPM", {
            "payload": {"actors": [{"name": "Traveler Dela", "weight": 100}]},
            "semantic_related_refs": [{"role": "ACTOR", "canonical_id": "npc.7crystal"}],
        })



def test_related_semantic_ref_cannot_be_stale_or_unbound():
    with pytest.raises(ValueError, match="SEMANTIC_RELATED_REF_UNBOUND"):
        semantic_related_bindings_for_spec("MONSTER", {
            "payload": {"drops": [{"percentage": 100, "items": ["WS122"]}]},
            "semantic_related_refs": [{"role": "ITEM_REFERENCE", "canonical_id": "item.wa121"}],
        })

def test_selection_catalog_exposes_semantic_authoring_lists(tmp_path):
    _, _, server = _roots(tmp_path)
    selections = selection_catalog(server, refresh=True)
    assert selections["semantic_catalog"]["counts"]["items"] == 1893
    assert len(selections["authoring_catalog"]["mobs"]) == 383
    assert len(selections["authoring_catalog"]["npcs"]) == 175
    assert any(x["canonical_id"] == "map.village_2" for x in selections["authoring_catalog"]["maps"])


def test_stage_item_create_persists_semantic_binding_in_manifest(tmp_path):
    project, client, server = _roots(tmp_path)
    result = stage_authoring(project, server, client, {
        "kind": "ITEM",
        "mode": "CREATE",
        "path": "GameServer/OpenItem/WA121.txt",
        "semantic_ref": {"canonical_id": "item.wa121"},
        "fields": {"name": "Machado Wyvern", "code": "WA121", "price": 1, "weight": 1},
    })
    assert result["semantic_binding"]["canonical_id"] == "item.wa121"
    manifest = result["manifest"]
    assert manifest["authoring_semantic_binding"]["canonical_id"] == "item.wa121"
    assert manifest["assets"][0]["authoring_semantic_binding"]["canonical_id"] == "item.wa121"


def test_stage_monster_create_persists_related_item_semantic_provenance(tmp_path):
    project, client, server = _roots(tmp_path)
    row = lookup_semantic_ref("monster.100_arqueira_das_cinzas")
    assert row is not None
    result = stage_authoring(project, server, client, {
        "kind": "MONSTER",
        "mode": "CREATE",
        "path": row["logical_path"],
        "semantic_ref": {"canonical_id": row["canonical_id"]},
        "semantic_related_refs": [{"role": "ITEM_REFERENCE", "canonical_id": "item.wa121"}],
        "payload": {
            "fields": {
                "name": row["display_name"],
                "model_file": row["model_file"],
                "level": row["level"],
                "life": 100,
                "experience": 1,
            },
            "drops": [{"percentage": 100, "items": ["WA121"]}],
        },
    })
    assert result["semantic_binding"]["canonical_id"] == row["canonical_id"]
    assert result["semantic_related_bindings"][0]["canonical_id"] == "item.wa121"
    assert result["manifest"]["authoring_semantic_related_bindings"][0]["role"] == "ITEM_REFERENCE"


def test_authoring_guide_and_capabilities_advertise_semantic_identity(tmp_path):
    _, client, server = _roots(tmp_path)
    guide = authoring_workspace_guide(server_root=server, client_root=client)
    assert guide["format"] == "PT_LEGACY_AUTHORING_WORKSPACE_GUIDE_V2"
    assert guide["semantic_catalog"]["identity_policy"] == "CANONICAL_ID_PRIMARY_RUNTIME_CODE_SECONDARY"
    assert "Ricarten" in guide["semantic_catalog"]["important_correction"]
    caps = authoring_capabilities()
    assert caps["semantic_catalog"]["enabled"] is True
    assert caps["semantic_catalog"]["canonical_id_is_primary_authoring_identity"] is True


def test_semantic_catalog_ui_controls_are_wired():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    for element_id in (
        "legacyAuthoringCatalogEntry",
        "legacyAuthoringUseCatalogBtn",
        "legacyAuthoringCatalogMeta",
        "legacyAuthoringEntityRef",
        "legacyAuthoringInsertEntityBtn",
    ):
        assert f'id="{element_id}"' in html
    assert "function semanticCatalog()" in js
    assert "function useLegacyCatalogEntry()" in js
    assert "function insertLegacyEntityIntoSpec()" in js
    assert "canonical_id" in js
    assert "semantic_related_refs" in js
