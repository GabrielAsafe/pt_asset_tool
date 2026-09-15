from pt_asset_tool.monster_npc_census import build_entity_catalog


def rec(path, group, ext):
    return {"relative_path": path, "semantic_group": group, "extension": ext}


def test_entity_catalog_groups_physical_directories_and_picks_preview():
    rows = [
        rec("char/npc/Ahin/Ahin.smd", "NPC", ".smd"),
        rec("char/npc/Ahin/Ahin.inx", "NPC", ".inx"),
        rec("char/npc/Ahin/Ahin.smb", "NPC", ".smb"),
        rec("char/npc/Ahin/Ahin-body.tga", "NPC", ".tga"),
        rec("char/monster/Acero/Acero.smd", "MONSTER", ".smd"),
        rec("char/monster/Acero/Acero.tga", "MONSTER", ".tga"),
    ]
    entities = build_entity_catalog(rows)
    by_name = {x["display_name"]: x for x in entities}
    assert by_name["Ahin"]["folder_root"] == "char/npc/Ahin"
    assert by_name["Ahin"]["has_model"] is True
    assert by_name["Ahin"]["has_config"] is True
    assert by_name["Ahin"]["has_skeleton"] is True
    assert by_name["Ahin"]["representative_preview"].endswith("Ahin-body.tga")
    assert by_name["Acero"]["representative_preview"].endswith("Acero.tga")
    assert by_name["Acero"]["writer_status"] == "UNAUTHORIZED"
