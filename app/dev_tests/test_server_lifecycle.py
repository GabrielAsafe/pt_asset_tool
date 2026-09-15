from pt_asset_tool.server_lifecycle import (
    ASSET_MAP_METADATA,
    ASSET_MAP_METADATA_REVIEW,
    ASSET_SHARED_3D,
    ASSET_STATIC,
    CONFIG_REVIEW,
    LOG_FORENSICS_EXCLUDED,
    PERSISTENCE_BLOCKED,
    RUNTIME_INTEGRITY_BLOCKED,
    SECURITY_STATE_BLOCKED,
    classify_server_path,
)


def test_server_path_lifecycle_separates_assets_from_runtime_state():
    cases = {
        "GameServer/monster/Foo.inf": ASSET_STATIC,
        "GameServer/npc/Bar.npc": ASSET_STATIC,
        "GameServer/OpenItem/item.txt": ASSET_STATIC,
        "GameServer/Field/forest.spm": ASSET_STATIC,
        "GameServer/Field/forest.spp": ASSET_MAP_METADATA,
        "GameServer/Field/forest.spc": ASSET_MAP_METADATA_REVIEW,
        "name/Foo.zhoon": ASSET_STATIC,
        "char/monster/Foo/Foo.inx": ASSET_SHARED_3D,
        "char/monster/Foo/Foo.smd": ASSET_SHARED_3D,
        "char/monster/Foo/Foo.smb": ASSET_SHARED_3D,
        "Configs/hotuk.ini": CONFIG_REVIEW,
        "DataServer/userdata/00/a.dat": PERSISTENCE_BLOCKED,
        "PostBox/00/a.dat": PERSISTENCE_BLOCKED,
        "LogItemData/1@2.itm": LOG_FORENSICS_EXCLUDED,
        "BlackUser/1.bur": SECURITY_STATE_BLOCKED,
        "FuncBox/123.dat": RUNTIME_INTEGRITY_BLOCKED,
        "BlessCastle.dat": SECURITY_STATE_BLOCKED,
        "cpItem.dat": SECURITY_STATE_BLOCKED,
    }
    for rel, expected in cases.items():
        assert classify_server_path(rel).lifecycle == expected, rel


def test_logitemdata_never_becomes_asset_candidate():
    c = classify_server_path("LogItemData/158265217@8721833.itm")
    assert c.lifecycle == LOG_FORENSICS_EXCLUDED
    assert c.asset_candidate is False
    assert c.design_visible is False
    assert c.write_policy == "FORENSICS_ONLY"


def test_authoritative_lifecycle_blocks_whole_runtime_roots_and_war_everywhere():
    blocked = {
        "DataServer/foo.dat": PERSISTENCE_BLOCKED,
        "PostBox/a.dat": PERSISTENCE_BLOCKED,
        "BlackUser/temp.bur": SECURITY_STATE_BLOCKED,
        "FuncBox/15122.dat": RUNTIME_INTEGRITY_BLOCKED,
        "foo/bar/player.war": PERSISTENCE_BLOCKED,
    }
    for rel, lifecycle in blocked.items():
        row = classify_server_path(rel)
        assert row.lifecycle == lifecycle
        assert row.asset_candidate is False
