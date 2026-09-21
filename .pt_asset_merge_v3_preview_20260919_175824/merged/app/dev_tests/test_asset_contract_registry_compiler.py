import json
import hashlib
import struct
from pathlib import Path

import pytest

from pt_asset_tool.asset_contract_registry import (
    get_contract,
    match_contracts_for_path,
    registry_summary,
    schema_for_contract,
)
from pt_asset_tool.asset_compiler import (
    CURRENT_NPC_OPCODE,
    compile_asset_recipe,
    plan_asset_recipe,
)


def _recipe(contract_id: str, output: str, payload: dict, side: str = "SERVER") -> dict:
    return {
        "format": "PT_ASSET_RECIPE_V1",
        "id": "test",
        "contract_id": contract_id,
        "target_side": side,
        "output": output,
        "payload": payload,
    }


def test_source_contract_registry_v4_is_loaded_and_implementation_is_separate():
    report = registry_summary()
    assert report["contract_count"] == 61
    assert report["status"] == "PASS"
    spc = get_contract("field.fixed_npc.spc").public()
    assert spc["capability"] == "ABI_BINARY_AUTHORABLE"
    assert spc["implementation"]["state"] == "COMPILER_READY"
    schema = schema_for_contract("field.fixed_npc.spc")
    assert schema is not None


def test_contract_matcher_prefers_exact_source_path_convention():
    rows = match_contracts_for_path("GameServer/Field/Ricarten.spc")
    assert rows[0]["match"] == "EXACT_PATH_CONVENTION"
    assert rows[0]["contract"]["id"] == "field.fixed_npc.spc"
    npc = match_contracts_for_path("GameServer/NPC/Test.inf")
    assert npc[0]["contract"]["id"] == "character.npc.npc"


def test_spp_recipe_is_exact_win32_file_and_only_stages_under_pt_build(tmp_path):
    recipe = _recipe(
        "field.startpoints.spp",
        "GameServer/Field/NewField.spp",
        {"records": [{"index": 0, "state": 1, "x": 123, "z": -456}]},
    )
    plan = plan_asset_recipe(recipe)
    assert plan["status"] == "READY"
    assert plan["preview"]["size"] == 2400
    build = compile_asset_recipe(tmp_path, recipe)
    output = Path(build["output"])
    assert output.is_file()
    assert tmp_path / "pt_build" in output.parents
    raw = output.read_bytes()
    assert len(raw) == 2400
    assert struct.unpack_from("<iii", raw, 0) == (1, 123, -456)


def test_spc_recipe_uses_current_opcode_zero_runtime_pointers_and_exact_size(tmp_path):
    recipe = _recipe(
        "field.fixed_npc.spc",
        "GameServer/Field/NewField.spc",
        {"records": [{
            "index": 3,
            "name": "Merchant",
            "model_ini": "char/npc/merchant.ini",
            "server_npc": "GameServer/NPC/merchant.npc",
            "x": 10,
            "y": 20,
            "z": 30,
        }]},
    )
    plan = plan_asset_recipe(recipe)
    assert plan["status"] == "READY"
    assert plan["preview"]["size"] == 50400
    build = compile_asset_recipe(tmp_path, recipe)
    raw = Path(build["output"]).read_bytes()
    base = 3 * 504
    assert len(raw) == 50400
    assert struct.unpack_from("<iI", raw, base) == (504, CURRENT_NPC_OPCODE)
    assert struct.unpack_from("<I", raw, base + 8 + 160)[0] == 0  # smCHAR_INFO object serial
    assert struct.unpack_from("<I", raw, base + 472)[0] == 0      # outer object serial
    assert raw[base + 8:base + 40].split(b"\0", 1)[0] == b"Merchant"


def test_sin_recipe_enforces_real_runtime_line_buffer():
    good = _recipe("ui.help.sin", "game/help/test.sin", {"text": "A\nB", "encoding": "cp1252"}, side="CLIENT")
    assert plan_asset_recipe(good)["status"] == "READY"
    bad = _recipe("ui.help.sin", "game/help/test.sin", {"text": "X" * 128, "encoding": "cp1252"}, side="CLIENT")
    plan = plan_asset_recipe(bad)
    assert plan["status"] == "BLOCKED"
    assert any("SIN_LINE_TOO_LONG" in x for x in plan["errors"])


def test_recipe_never_allows_runtime_state_contract():
    recipe = _recipe("runtime.cpitem.dat", "GameServer/cpItem.dat", {"text": "x"})
    plan = plan_asset_recipe(recipe)
    assert plan["status"] == "BLOCKED"
    assert "DIRECT_COMPILER_NOT_IMPLEMENTED" in plan["errors"]


def test_skill_config_compiler_uses_source_key_types_and_exact_ten_levels():
    good = _recipe(
        "server.skill_config",
        "Configs/Skill/Archer.ini",
        {"file": "Archer.ini", "values": {"A_Rage_Area": list(range(1, 11))}},
    )
    plan = plan_asset_recipe(good)
    assert plan["status"] == "READY"
    assert plan["preview"]["writer"]["writer"] == "SKILL_CONFIG_SOURCE_REGISTRY"
    assert plan["preview"]["writer"]["source_reader_contracts"]["A_Rage_Area"] == "int[10]"

    short = _recipe(
        "server.skill_config",
        "Configs/Skill/Archer.ini",
        {"file": "Archer.ini", "values": {"A_Rage_Area": [1] * 9}},
    )
    blocked = plan_asset_recipe(short)
    assert blocked["status"] == "BLOCKED"
    assert any("SKILL_CONFIG_REQUIRES_10_LEVELS:A_Rage_Area" in x for x in blocked["errors"])

    unknown = _recipe(
        "server.skill_config",
        "Configs/Skill/Archer.ini",
        {"file": "Archer.ini", "values": {"MadeUpSkillKey": [1] * 10}},
    )
    blocked = plan_asset_recipe(unknown)
    assert blocked["status"] == "BLOCKED"
    assert any("SKILL_CONFIG_UNKNOWN_KEYS" in x for x in blocked["errors"])


def test_server_main_config_compiler_blocks_non_active_directives_and_validates_shapes():
    good = _recipe(
        "server.main_config",
        "Configs/hotuk.ini",
        {"directives": {"*SERVER_CODE": 7, "*SERVER_AUTOPLAY": None, "*SERVER_NAME": "Summit"}},
    )
    plan = plan_asset_recipe(good)
    assert plan["status"] == "READY"
    meta = plan["preview"]["writer"]
    assert meta["writer"] == "SERVER_MAIN_CONFIG_SOURCE_DIRECTIVES"
    assert "*SERVER_CODE" in meta["directives"]

    dormant = _recipe(
        "server.main_config",
        "Configs/hotuk.ini",
        {"directives": {"<LEGACY_ONLY:rsServerConfig.DisableParty>": None}},
    )
    blocked = plan_asset_recipe(dormant)
    assert blocked["status"] == "BLOCKED"
    assert any("SERVER_DIRECTIVE_NOT_IN_ACTIVE_SOURCE" in x for x in blocked["errors"])

    bad_shape = _recipe(
        "server.main_config",
        "Configs/hotuk.ini",
        {"directives": {"*SERVER_CODE": [1, 2]}},
    )
    blocked = plan_asset_recipe(bad_shape)
    assert blocked["status"] == "BLOCKED"
    assert any("SERVER_DIRECTIVE_REQUIRES_ONE_INTEGER" in x for x in blocked["errors"])


def test_operational_ini_compiler_is_source_registry_strict():
    good = _recipe(
        "client.game_config",
        "game.ini",
        {"sections": {"Screen": {"Windowed": True}, "Audio": {"MusicVolume": 80}}},
        side="CLIENT",
    )
    plan = plan_asset_recipe(good)
    assert plan["status"] == "READY"
    meta = plan["preview"]["writer"]
    assert meta["writer"] == "SOURCE_REGISTRY_INI"
    assert meta["authored_key_count"] == 2

    unknown = _recipe(
        "client.game_config",
        "game.ini",
        {"sections": {"Screen": {"ImaginarySetting": 1}}},
        side="CLIENT",
    )
    blocked = plan_asset_recipe(unknown)
    assert blocked["status"] == "BLOCKED"
    assert any("INI_UNKNOWN_SOURCE_KEYS:Screen.ImaginarySetting" in x for x in blocked["errors"])

from pt_asset_tool.asset_compiler import (
    BUNDLE_RECIPE_FORMAT,
    plan_asset_bundle,
    compile_asset_bundle,
    plan_compiler_input,
)



def _minimal_model062(path: Path) -> Path:
    """One empty Model0.62 object; enough for structural/closure tests."""
    sh, si, so = 556, 40, 2236
    start = sh + si
    data = bytearray(start + so)
    data[:23] = b"SMD Model data Ver 0.62"
    struct.pack_into("<i", data, 24, 1)
    struct.pack_into("<i", data, 28, 0)
    struct.pack_into("<i", data, 32, start)
    struct.pack_into("<i", data, 36, start)
    data[sh:sh + 4] = b"obj\0"
    struct.pack_into("<i", data, sh + 32, so)
    struct.pack_into("<i", data, sh + 36, start)
    data[start + 172:start + 176] = b"obj\0"
    # nv/nf/nt and animation counts are zero by bytearray initialization.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _model062_with_texture(path: Path, texture_name: str) -> Path:
    sh, si, group, mat, so, sv, sf = 556, 40, 88, 320, 2236, 24, 36
    mat_point = sh + si
    strings = texture_name.encode("latin1") + b"\0\0"  # Name + empty NameA
    first_obj = mat_point + group + mat + 4 + len(strings)
    length = so + 3 * sv + sf
    data = bytearray(first_obj + length)
    data[:23] = b"SMD Model data Ver 0.62"
    struct.pack_into("<i", data, 24, 1)
    struct.pack_into("<i", data, 28, 1)
    struct.pack_into("<i", data, 32, mat_point)
    struct.pack_into("<i", data, 36, first_obj)
    data[sh:sh + 4] = b"obj\0"
    struct.pack_into("<i", data, sh + 32, length)
    struct.pack_into("<i", data, sh + 36, first_obj)
    struct.pack_into("<i", data, mat_point + 8, 1)
    m = mat_point + group
    struct.pack_into("<i", data, m + 0, 1)
    struct.pack_into("<i", data, m + 4, 1)
    struct.pack_into("<i", data, m + 304, 0)
    struct.pack_into("<i", data, m + mat, len(strings))
    data[m + mat + 4:m + mat + 4 + len(strings)] = strings
    raw = first_obj
    struct.pack_into("<iii", data, raw + 84, 3, 1, 0)
    data[raw + 172:raw + 176] = b"obj\0"
    vo = raw + so
    for idx, xyz in enumerate(((0, 0, 0), (256, 0, 0), (0, 256, 0))):
        struct.pack_into("<6i", data, vo + idx * sv, *(xyz + (0, 0, 256)))
    face = vo + 3 * sv
    struct.pack_into("<4H", data, face, 0, 1, 2, 0)
    struct.pack_into("<I", data, face + 32, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path

def _make_roots(tmp_path):
    client = tmp_path / "client"
    server = tmp_path / "server"
    (client / "char/monster/test").mkdir(parents=True)
    (client / "char/monster/test/test.ini").write_text("*모양파일 test.smd\r\n", encoding="cp949")
    _minimal_model062(client / "char/monster/test/test.smd")
    (client / "char/npc/test").mkdir(parents=True)
    (client / "char/npc/test/test.ini").write_text("*모양파일 test.smd\r\n", encoding="cp949")
    _minimal_model062(client / "char/npc/test/test.smd")
    (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*ACTOR "Existing" 100\r\n*MAX_ACTOR 10\r\n', encoding="cp1252")
    (server / "GameServer/Field/Test.spc").write_bytes(b"\0" * (100 * 504))
    return client, server


def test_monster_bundle_compiles_definition_and_patches_existing_spm(tmp_path):
    client, server = _make_roots(tmp_path)
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "test_monster",
        "bundle_type": "MONSTER",
        "payload": {
            "identity": {"id": "test_monster", "name": "Test Monster"},
            "model_file": "char/monster/test/test.ini",
            "definition": {
                "output": "GameServer/Monster/test_monster.inf",
                "fields": {"level": 50, "life": 1000, "attack_damage": [10, 20], "attack_speed": [1.0, 1.0]},
            },
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING", "weight": 250},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY"
    assert plan["visual_dependency"]["status"] == "PASS"
    assert plan["asset_count"] == 2
    assert plan["patches"][0]["preview"]["writer"]["writer"] == "SPM_PATCH_EXISTING_SOURCE_PRESERVING"
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    assert build["status"] == "PASS"
    assert build["asset_count"] == 2
    outputs = {row["logical_output"]: Path(row["output"]) for row in build["assets"]}
    definition = outputs["GameServer/Monster/test_monster.inf"].read_bytes().decode("cp949")
    assert "Test Monster" in definition
    spm = outputs["GameServer/Field/Test.spm"].read_bytes().decode("cp1252")
    assert '*ACTOR "Existing" 100' in spm
    assert '*ACTOR "Test Monster" 250' in spm
    assert "*MAX_ACTOR 10" in spm


def test_npc_bundle_builds_definition_and_inserts_source_abi_record(tmp_path):
    client, server = _make_roots(tmp_path)
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "test_npc",
        "bundle_type": "NPC",
        "payload": {
            "identity": {"id": "test_npc", "name": "Test Merchant"},
            "model_file": "char/npc/test/test.ini",
            "definition": {
                "output": "GameServer/NPC/test_npc.npc",
                "fields": {"warehouse": True, "shop": True},
                "shops": {"weapon": ["WA101"]},
            },
            "placement": {"output": "GameServer/Field/Test.spc", "mode": "PATCH_EXISTING", "x": 10, "y": 20, "z": 30},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY"
    assert plan["patches"][0]["preview"]["writer"]["slot_index"] == 0
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    outputs = {row["logical_output"]: Path(row["output"]) for row in build["assets"]}
    raw = outputs["GameServer/Field/Test.spc"].read_bytes()
    assert len(raw) == 50400
    assert struct.unpack_from("<iI", raw, 0) == (504, CURRENT_NPC_OPCODE)
    assert raw[8:40].split(b"\0", 1)[0] == b"Test Merchant"
    assert raw[104:164].split(b"\0", 1)[0] == b"GameServer\\NPC\\test_npc.npc"
    assert struct.unpack_from("<3i", raw, 476) == (10, 20, 30)


def test_bundle_blocks_missing_visual_and_duplicate_identity_or_occupied_spc_slot(tmp_path):
    client, server = _make_roots(tmp_path)
    missing = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "bad", "bundle_type": "MONSTER",
        "payload": {"identity": {"name": "Bad"}, "model_file": "char/monster/missing.ini",
                    "definition": {"fields": {}},
                    "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"}},
    }
    plan = plan_compiler_input(missing, client_root=client, server_root=server)
    assert plan["status"] == "BLOCKED"
    assert "MODEL_FILE_NOT_FOUND_IN_CLIENT_OR_BUNDLE" in plan["errors"]

    raw = bytearray((server / "GameServer/Field/Test.spc").read_bytes())
    struct.pack_into("<iI", raw, 0, 504, CURRENT_NPC_OPCODE)
    (server / "GameServer/Field/Test.spc").write_bytes(raw)
    occupied = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "npc", "bundle_type": "NPC",
        "payload": {"identity": {"name": "NPC"}, "model_file": "char/npc/test/test.ini",
                    "definition": {"fields": {}},
                    "placement": {"output": "GameServer/Field/Test.spc", "mode": "PATCH_EXISTING", "slot_index": 0}},
    }
    plan = plan_asset_bundle(occupied, client_root=client, server_root=server)
    assert plan["status"] == "BLOCKED"
    assert any("SPC_SLOT_NOT_FREE:0" in x for x in plan["errors"])


def test_item_and_field_bundles_are_source_strict(tmp_path):
    item = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "sword", "bundle_type": "ITEM",
        "payload": {"identity": {"name": "Sword"}, "definition": {"fields": {"code": "WS101", "price": 100}}},
    }
    plan = plan_asset_bundle(item)
    assert plan["status"] == "READY"
    assert "ITEM_CODE_MUST_EXIST_IN_RUNTIME_TABLE" in plan["warnings"]

    field = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "field", "bundle_type": "FIELD",
        "payload": {"outputs": {"spm": "GameServer/Field/New.spm", "spp": "GameServer/Field/New.spp", "spc": "GameServer/Field/New.spc"},
                    "spm": {"actors": [{"name": "Monster", "weight": 100}]},
                    "spp": {"records": [{"index": 0, "state": 1, "x": 1, "z": 2}]},
                    "spc": {"records": []}},
    }
    plan = plan_asset_bundle(field)
    assert plan["status"] == "READY"
    assert plan["asset_count"] == 3


def test_item_code_is_verified_against_recovered_runtime_catalog():
    good = _recipe(
        "item.definition.txt", "GameServer/OpenItem/ws101.txt",
        {"fields": {"name": "Sword", "code": "WS101", "price": 10}},
    )
    plan = plan_asset_recipe(good)
    assert plan["status"] == "READY"
    meta = plan["preview"]["writer"]
    assert meta["code_identity_status"] == "SOURCE_VERIFIED"
    assert meta["runtime_catalog_match_count"] == 1
    assert meta["runtime_numeric_codes"] == ["0x01060100"]

    bad = _recipe(
        "item.definition.txt", "GameServer/OpenItem/newcode.txt",
        {"fields": {"name": "New", "code": "ZZ999"}},
    )
    blocked = plan_asset_recipe(bad)
    assert blocked["status"] == "BLOCKED"
    assert any("ITEM_CODE_NOT_IN_RUNTIME_TABLE:ZZ999" in x for x in blocked["errors"])

    boundary = _recipe(
        "item.definition.txt", "GameServer/OpenItem/newcode.txt",
        {"fields": {"name": "New", "code": "ZZ999"}, "allow_unknown_code": True},
    )
    plan = plan_asset_recipe(boundary)
    assert plan["status"] == "READY"
    assert "CODE_ID_BOUNDARY_UNREGISTERED" in plan["warnings"]



def test_model_config_compiler_uses_source_exact_tokens_and_closes_visual_bundle(tmp_path):
    client = tmp_path / "client"
    server = tmp_path / "server"
    (client / "char/monster/new").mkdir(parents=True)
    _minimal_model062(client / "char/monster/new/new.smd")
    _minimal_model062(client / "char/monster/new/new.smb")
    (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "source_model",
        "bundle_type": "MONSTER",
        "assets": [{
            "format": "PT_ASSET_RECIPE_V1",
            "id": "model_cfg",
            "contract_id": "model.config.ini",
            "target_side": "CLIENT",
            "output": "char/monster/new/new.ini",
            "payload": {
                "model_file": "new.smd",
                "motion_file": "new.smb",
                "motions": [{"token": "*서있기동작", "start": 0, "end": 10, "repeat": True, "rate": 100}],
            },
        }],
        "payload": {
            "identity": {"id": "source_model", "name": "Source Model"},
            "model_file": "char/monster/new/new.ini",
            "definition": {"fields": {"level": 1, "life": 1, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY"
    assert plan["visual_dependency"]["status"] == "PASS"
    assert not any(x.startswith("MODEL_INX_RUNTIME_DERIVED:") for x in plan["warnings"])
    assert any(x.get("contract_id") == "model.cache.inx" for x in plan["children"])
    cfg_plan = next(x for x in plan["children"] if x.get("contract_id") == "model.config.ini")
    assert cfg_plan["preview"]["writer"]["writer"] == "MODEL_CONFIG_SOURCE_EXACT"


def test_visual_bundle_blocks_when_model_config_dependency_is_missing(tmp_path):
    client, server = _make_roots(tmp_path)
    (client / "char/monster/test/test.smd").unlink()
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "missing_mesh",
        "bundle_type": "MONSTER",
        "payload": {
            "identity": {"name": "Missing Mesh"},
            "model_file": "char/monster/test/test.ini",
            "definition": {"fields": {"level": 1, "life": 1, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "BLOCKED"
    assert plan["visual_dependency"]["reason"] == "MODEL_PACKAGE_CLOSURE_INCOMPLETE"
    assert any(x["reason"] == "MODEL_DEPENDENCY_NOT_FOUND" for x in plan["visual_dependency"]["missing"])


def test_model_cache_inx_compiler_mirrors_source_layout_and_motion_encoding(tmp_path):
    import pt_inx_motion_core_v2 as inxcore

    config_payload = {
        "model_file": "new.smd",
        "motion_file": "new.smb",
        "motion_sources": ["extra.smb"],
        "motions": [
            {
                "token": "*서있기동작", "start": 0, "end": 20, "repeat": True,
                "rate": 70, "motion_frame": 0,
                "equipped_weapons": ["WA101"],
                "applicable_jobs": ["Atalanta"],
                "location": ["FIELD"],
            },
            {
                "token": "*기술동작", "start": 20, "end": 40, "key": "K",
                "motion_frame": 1, "applicable_skills": ["ExtremeShield"],
                "location": ["TOWN"],
            },
        ],
    }
    recipe = _recipe(
        "model.cache.inx",
        "char/monster/new/new.inx",
        {
            "source_config_output": "char/monster/new/new.ini",
            "source_config_payload": config_payload,
            "logical_cache": "char/monster/new/new.inx",
        },
        side="CLIENT",
    )
    plan = plan_asset_recipe(recipe)
    assert plan["status"] == "READY"
    assert plan["preview"]["size"] == 95268
    assert plan["preview"]["writer"]["writer"] == "MODEL_CACHE_INX_SOURCE_NATIVE"
    build = compile_asset_recipe(tmp_path, recipe)
    parsed = inxcore.parse_inx(Path(build["output"]))
    assert parsed["layout"]["name"] == "MODERN_172"
    from pt_asset_tool.model_cache_compiler import canonicalize_runtime_path
    canonical = canonicalize_runtime_path("char/monster/new/new.inx")
    assert canonical == r"char\monster\new\new.inx"
    assert parsed["file_code"] == inxcore.get_speed_sum(canonical)
    assert build["writer"]["checksum_path_policy"] == "WIN32_CANONICAL"
    assert build["writer"]["semantic_roundtrip_valid"] is True
    assert parsed["motion_count"] == 12
    stand, skill = parsed["motions"][10:12]
    assert (stand["state_name"], stand["start"], stand["end"], stand["motion_frame"]) == ("STAND", 0, 20, 0)
    assert stand["item_code_count"] == 1 and stand["item_code_list"] == [0]
    assert stand["job_code_bit"] == 0x10 and stand["map_position"] == 2
    assert (skill["state_name"], skill["start"], skill["end"], skill["motion_frame"]) == ("SKILL", 20, 40, 1)
    assert skill["key_code"] == ord("K")
    assert skill["skill_code_list"] == [1]  # ExtremeShield is source index 1.
    assert skill["map_position"] == 3        # Source forces skill motions to TOWN|FIELD.


def test_bundle_auto_emits_source_native_inx_for_generated_model_config(tmp_path):
    client = tmp_path / "client"
    server = tmp_path / "server"
    (client / "char/monster/new").mkdir(parents=True)
    _minimal_model062(client / "char/monster/new/new.smd")
    _minimal_model062(client / "char/monster/new/new.smb")
    (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "native_cache",
        "bundle_type": "MONSTER",
        "assets": [{
            "format": "PT_ASSET_RECIPE_V1",
            "id": "model_cfg",
            "contract_id": "model.config.ini",
            "target_side": "CLIENT",
            "output": "char/monster/new/new.ini",
            "payload": {
                "model_file": "new.smd",
                "motion_file": "new.smb",
                "motions": [{"token": "*서있기동작", "start": 0, "end": 10, "repeat": True, "rate": 100}],
            },
        }],
        "payload": {
            "identity": {"id": "native_cache", "name": "Native Cache"},
            "model_file": "char/monster/new/new.ini",
            "definition": {"fields": {"level": 1, "life": 1, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY"
    assert plan["visual_dependency"]["derived_cache"] == "RESOLVED"
    assert not any(x.startswith("MODEL_INX_RUNTIME_DERIVED:") for x in plan["warnings"])
    cache_plan = next(x for x in plan["children"] if x.get("contract_id") == "model.cache.inx")
    assert cache_plan["preview"]["size"] == 95268
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    cache = next(x for x in build["assets"] if x.get("contract_id") == "model.cache.inx")
    assert Path(cache["output"]).is_file()
    assert cache["target_evidence"]["policy"] == "CREATE_NEW"


def test_verified_model_artifact_closure_requires_face_used_texture_and_accepts_verified_texture(tmp_path):
    from PIL import Image

    client = tmp_path / "client"
    server = tmp_path / "server"
    client.mkdir()
    (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")
    smd = _model062_with_texture(tmp_path / "artifacts/new.smd", "image/monster/new/diffuse.png")
    tex = tmp_path / "artifacts/diffuse.png"
    tex.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), (20, 40, 60, 255)).save(tex)

    def artifact(contract_id, output, source):
        return {
            "format": "PT_ASSET_RECIPE_V1", "id": output.replace("/", "_"),
            "contract_id": contract_id, "target_side": "CLIENT", "output": output,
            "payload": {"source_path": str(source), "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        }

    assets = [
        artifact("model.smd.062", "char/monster/new/new.smd", smd),
        artifact("texture.standard", "image/monster/new/diffuse.png", tex),
        {
            "format": "PT_ASSET_RECIPE_V1", "id": "cfg", "contract_id": "model.config.ini",
            "target_side": "CLIENT", "output": "char/monster/new/new.ini", "payload": {"model_file": "new.smd"},
        },
    ]
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "texture_closure", "bundle_type": "MONSTER", "assets": assets,
        "payload": {
            "identity": {"name": "Texture Closure"}, "model_file": "char/monster/new/new.ini",
            "definition": {"fields": {"level": 1, "life": 1, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY"
    texture_row = next(x for x in plan["visual_dependency"]["closure"] if x.get("role") == "model_texture")
    assert texture_row["path"] == "image/monster/new/diffuse.png"
    assert texture_row["source"] == "BUNDLE_GENERATED"
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    texture_build = next(x for x in build["assets"] if x.get("contract_id") == "texture.standard")
    assert texture_build["binding_evidence"]["status"] == "SOURCE_GRAPH_BOUND"
    assert texture_build["binding_evidence"]["role"] == "model_texture"

    missing_recipe = dict(recipe)
    missing_recipe["assets"] = [x for x in assets if x.get("contract_id") != "texture.standard"]
    blocked = plan_asset_bundle(missing_recipe, client_root=client, server_root=server)
    assert blocked["status"] == "BLOCKED"
    assert any(x.get("reason") == "MODEL_TEXTURE_DEPENDENCY_NOT_FOUND" for x in blocked["visual_dependency"]["missing"])



def test_model_cache_checksum_path_policy_matches_mingw_source_and_can_preserve_forensics():
    from pt_asset_tool.model_cache_compiler import (
        canonicalize_runtime_path, compile_model_cache, get_speed_sum, inspect_model_cache,
    )
    from pt_asset_tool.asset_contract_registry import source_registry
    config = "*모양파일 new.smd\r\n".encode("cp949")
    logical = "char//monster\\new/new.ini"
    canonical_cache = r"char\monster\new\new.inx"
    assert canonicalize_runtime_path("char//monster\\new/new.inx") == canonical_cache
    data, meta = compile_model_cache(
        logical, config,
        item_catalog=source_registry("item_catalog"),
        skill_catalog=source_registry("model_motion_skills"),
    )
    inspected = inspect_model_cache(data, logical_cache="char/monster/new/new.inx")
    assert inspected["valid"] is True
    assert inspected["encoded_file_code"] == get_speed_sum(canonical_cache)
    assert meta["checksum_cache_path"] == canonical_cache

    preserved, preserved_meta = compile_model_cache(
        "char/monster/new/new.ini", config,
        item_catalog=source_registry("item_catalog"),
        skill_catalog=source_registry("model_motion_skills"),
        checksum_path_policy="SOURCE_PRESERVE",
    )
    inspected_preserve = inspect_model_cache(
        preserved, logical_cache="char/monster/new/new.inx", checksum_path_policy="SOURCE_PRESERVE"
    )
    assert inspected_preserve["valid"] is True
    assert inspected_preserve["encoded_file_code"] == get_speed_sum("char/monster/new/new.inx")
    assert preserved_meta["checksum_path_policy"] == "SOURCE_PRESERVE"


def test_model_cache_semantic_inspector_detects_keyword_tamper():
    from pt_asset_tool.model_cache_compiler import compile_model_cache, inspect_model_cache, OFF_FILE_KEYWORD
    from pt_asset_tool.asset_contract_registry import source_registry
    config = (
        "*모양파일 new.smd\r\n"
        "*서있기동작 10 20 100 0\r\n"
    ).encode("cp949")
    data, _ = compile_model_cache(
        "char/monster/new/new.ini", config,
        item_catalog=source_registry("item_catalog"),
        skill_catalog=source_registry("model_motion_skills"),
    )
    good = inspect_model_cache(data, logical_cache="char/monster/new/new.inx")
    assert good["valid"] is True
    tampered = bytearray(data)
    tampered[OFF_FILE_KEYWORD] ^= 0x01
    bad = inspect_model_cache(bytes(tampered), logical_cache="char/monster/new/new.inx")
    assert bad["valid"] is False
    assert bad["path_code_match"] is False



def test_monster_visual_shorthand_expands_model_skeleton_textures_config_and_derived_inx(tmp_path):
    from PIL import Image
    client = tmp_path / "client"
    server = tmp_path / "server"
    client.mkdir()
    (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")

    smd = _model062_with_texture(tmp_path / "artifacts/new.smd", "image/monster/new/diffuse.png")
    smb = tmp_path / "artifacts/new.smb"
    _minimal_model062(smb)
    tex = tmp_path / "artifacts/diffuse.png"
    tex.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), (20, 30, 40, 255)).save(tex)

    def src(path):
        return {"source_path": str(path), "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "visual_shorthand",
        "bundle_type": "MONSTER",
        "payload": {
            "identity": {"name": "Visual Shorthand"},
            "visual": {
                "model": {"output": "char/monster/new/new.smd", **src(smd)},
                "skeleton": {"output": "char/monster/new/new.smb", **src(smb)},
                "textures": [{"output": "image/monster/new/diffuse.png", **src(tex)}],
                "config": {
                    "output": "char/monster/new/new.ini",
                    "payload": {
                        "motions": [{"token": "*서있기동작", "start": 0, "end": 10, "repeat": True}],
                    },
                },
            },
            "definition": {"fields": {"level": 1, "life": 1, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY", plan["errors"]
    assert plan["visual_dependency"]["status"] == "PASS"
    ids = [x.get("contract_id") for x in plan["children"]]
    assert "model.smd.062" in ids
    assert "model.smb.bone" in ids
    assert "texture.standard" in ids
    assert "model.config.ini" in ids
    assert "model.cache.inx" in ids
    definition = next(x for x in plan["children"] if x.get("contract_id") == "character.monster.inf")
    assert definition["preview"]["writer"]["writer"] == "CHARACTER_CONFIG_SOURCE_SCHEMA"

    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    outputs = {x["logical_output"] for x in build["assets"]}
    assert "char/monster/new/new.smd" in outputs
    assert "char/monster/new/new.smb" in outputs
    assert "char/monster/new/new.ini" in outputs
    assert "char/monster/new/new.inx" in outputs
    assert "image/monster/new/diffuse.png" in outputs


def test_model062_static_native_compiler_builds_textured_triangle_from_zero(tmp_path):
    from pt_asset_tool.static_roundtrip import _parse as parse_model062
    recipe = _recipe(
        "model.smd.062",
        "char/monster/native/native.smd",
        {
            "mesh": {
                "materials": [{"textures": ["image/monster/native/diffuse.png"], "two_side": True}],
                "objects": [{
                    "name": "body",
                    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                    "faces": [{
                        "vertices": [0, 1, 2], "material": 0,
                        "uv": [[0, 0], [1, 0], [0, 1]],
                    }],
                }],
            }
        },
        side="CLIENT",
    )
    plan = plan_asset_recipe(recipe)
    assert plan["status"] == "READY", plan["errors"]
    assert plan["preview"]["writer"]["writer"] == "MODEL062_SOURCE_NATIVE_STATIC_V1"
    assert plan["preview"]["writer"]["deterministic_pointer_policy"] is True
    build = compile_asset_recipe(tmp_path, recipe)
    parsed = parse_model062(Path(build["output"]).read_bytes())
    assert parsed["n"] == 1
    assert parsed["mat_count"] == 1
    obj = parsed["objects"]["body"]
    assert obj["nv"] == 3 and obj["nf"] == 1 and obj["nt"] == 1
    assert obj["vertices"][1][:3] == (256, 0, 0)
    assert obj["faces"][0]["verts"] == (0, 1, 2)
    assert obj["faces"][0]["material"] == 0
    assert obj["faces"][0]["uv_layers"] == [((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))]
    # Engine SetGNormals semantics store the normal endpoint, not a pure normal vector.
    assert obj["vertices"][0][5] > 30000


def test_monster_bundle_can_use_native_model062_without_source_artifact(tmp_path):
    from PIL import Image
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "server"; (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")
    tex = tmp_path / "new.png"; Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(tex)
    tex_sha = hashlib.sha256(tex.read_bytes()).hexdigest()
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "native_zero", "bundle_type": "MONSTER",
        "payload": {
            "identity": {"name": "Native Zero"},
            "visual": {
                "model": {
                    "output": "char/monster/native/native.smd",
                    "mesh": {
                        "materials": [{"textures": ["image/monster/native/diffuse.png"]}],
                        "objects": [{
                            "name": "body", "vertices": [[0,0,0],[1,0,0],[0,1,0]],
                            "faces": [{"vertices":[0,1,2],"material":0,"uv":[[0,0],[1,0],[0,1]]}],
                        }],
                    },
                },
                "textures": [{
                    "output": "image/monster/native/diffuse.png",
                    "source_path": str(tex), "expected_sha256": tex_sha,
                }],
                "config": {"output": "char/monster/native/native.ini", "payload": {}},
            },
            "definition": {"fields": {"level": 1, "life": 10, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY", plan["errors"]
    assert plan["visual_dependency"]["status"] == "PASS"
    model = next(x for x in plan["children"] if x.get("contract_id") == "model.smd.062")
    assert model["preview"]["writer"]["writer"] == "MODEL062_SOURCE_NATIVE_STATIC_V1"
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    assert build["status"] == "PASS"
    assert any(x["logical_output"] == "char/monster/native/native.inx" for x in build["assets"])


def test_smb_native_skeleton_compiler_builds_hierarchy_and_animation_from_zero():
    from pt_asset_tool.asset_compiler import plan_asset_recipe
    from pt_asset_tool.static_roundtrip import _parse

    recipe = _recipe(
        "model.smb.bone",
        "char/monster/native/native.smb",
        {
            "skeleton": {
                "bones": [
                    {"name": "root", "position": [0, 0, 0]},
                    {"name": "arm", "parent": "root", "position": [0, 1, 0]},
                ],
                "animations": [
                    {
                        "name": "stand",
                        "start_frame": 0,
                        "end_frame": 160,
                        "tracks": {
                            "arm": {
                                "rotation_axis_angle": [
                                    {"frame": 0, "axis": [0, 0, 1], "angle": 0.0},
                                    {"frame": 160, "axis": [0, 0, 1], "angle": 0.5},
                                ],
                                "position": [
                                    {"frame": 0, "value": [0.0, 0.0, 0.0]},
                                    {"frame": 160, "value": [0.0, 0.1, 0.0]},
                                ],
                                "scale": [
                                    {"frame": 0, "value": [1.0, 1.0, 1.0]},
                                    {"frame": 160, "value": [1.0, 1.0, 1.0]},
                                ],
                            }
                        },
                    }
                ],
            }
        },
        side="CLIENT",
    )
    plan = plan_asset_recipe(recipe)
    assert plan["status"] == "READY", plan
    writer = plan["preview"]["writer"]
    assert writer["writer"] == "MODEL062_SOURCE_NATIVE_SKELETON_V1"
    assert writer["bone_count"] == 2
    assert writer["animation_count"] == 1

    from pt_asset_tool.asset_compiler import _compiler_for
    data, _ = _compiler_for("model.smb.bone")(recipe["payload"])
    parsed = _parse(data)
    assert parsed["n"] == 2
    assert parsed["mat_count"] == 0
    assert parsed["objects"]["arm"]["nr"] == 2
    assert parsed["objects"]["arm"]["np"] == 2
    assert parsed["objects"]["arm"]["ns"] == 2
    assert parsed["objects"]["arm"]["nv"] == 0
    assert parsed["objects"]["arm"]["nf"] == 0


def test_smb_native_skeleton_blocks_parent_cycles_and_single_key_tracks():
    cycle = _recipe(
        "model.smb.bone",
        "char/test/cycle.smb",
        {"skeleton": {"bones": [{"name": "a", "parent": "b"}, {"name": "b", "parent": "a"}]}},
        side="CLIENT",
    )
    blocked = plan_asset_recipe(cycle)
    assert blocked["status"] == "BLOCKED"
    assert any("SMB_BONE_PARENT_CYCLE" in e for e in blocked["errors"])

    one_key = _recipe(
        "model.smb.bone",
        "char/test/one.smb",
        {
            "skeleton": {
                "bones": [{"name": "root"}],
                "animations": [{
                    "start_frame": 0, "end_frame": 160,
                    "tracks": {"root": {"position": [{"frame": 0, "value": [0, 0, 0]}]}},
                }],
            }
        },
        side="CLIENT",
    )
    blocked = plan_asset_recipe(one_key)
    assert blocked["status"] == "BLOCKED"
    assert any("TRACK_REQUIRES_ZERO_OR_AT_LEAST_2_KEYS" in e for e in blocked["errors"])


def test_model062_native_physique_serializes_exact_bone_names():
    from pt_asset_tool.asset_compiler import _compiler_for
    from pt_asset_tool.static_roundtrip import _parse
    payload = {
        "mesh": {
            "materials": [{"textures": ["image/test/d.png"]}],
            "objects": [{
                "name": "body",
                "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                "vertex_bones": ["root", "arm", "arm"],
                "faces": [{"vertices": [0, 1, 2], "material": 0, "uv": [[0, 0], [1, 0], [0, 1]]}],
            }],
        }
    }
    data, meta = _compiler_for("model.smd.062")(payload)
    parsed = _parse(data)
    body = parsed["objects"]["body"]
    assert body["phys"] is True
    assert body["physique_names"] == ["root", "arm", "arm"]
    assert meta["supports_physique"] is True
    assert meta["objects"][0]["bone_bindings"] == ["arm", "root"]


def test_monster_bundle_native_mesh_and_skeleton_close_physique_dependencies(tmp_path):
    from PIL import Image
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "server"; (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")
    tex = tmp_path / "new.png"; Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(tex)
    tex_sha = hashlib.sha256(tex.read_bytes()).hexdigest()
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "native_rig", "bundle_type": "MONSTER",
        "payload": {
            "identity": {"name": "Native Rig"},
            "visual": {
                "model": {
                    "output": "char/monster/native_rig/native_rig.smd",
                    "mesh": {
                        "materials": [{"textures": ["image/monster/native_rig/diffuse.png"]}],
                        "objects": [{
                            "name": "body", "vertices": [[0,0,0],[1,0,0],[0,1,0]],
                            "vertex_bones": ["root", "arm", "arm"],
                            "faces": [{"vertices":[0,1,2],"material":0,"uv":[[0,0],[1,0],[0,1]]}],
                        }],
                    },
                },
                "skeleton": {
                    "output": "char/monster/native_rig/native_rig.smb",
                    "skeleton": {
                        "bones": [{"name": "root"}, {"name": "arm", "parent": "root"}],
                        "animations": [{
                            "name": "stand", "start_frame": 0, "end_frame": 160,
                            "tracks": {"arm": {"rotation_axis_angle": [
                                {"frame": 0, "axis": [0,0,1], "angle": 0.0},
                                {"frame": 160, "axis": [0,0,1], "angle": 0.25},
                            ]}},
                        }],
                    },
                },
                "textures": [{
                    "output": "image/monster/native_rig/diffuse.png",
                    "source_path": str(tex), "expected_sha256": tex_sha,
                }],
                "config": {"output": "char/monster/native_rig/native_rig.ini", "payload": {}},
            },
            "definition": {"fields": {"level": 1, "life": 10, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY", plan
    closure = plan["visual_dependency"]["closure"]
    assert any(x.get("role") == "physique_skeleton" and x.get("status") == "PASS" for x in closure)
    skeleton = next(x for x in plan["children"] if x.get("contract_id") == "model.smb.bone")
    assert skeleton["preview"]["writer"]["writer"] == "MODEL062_SOURCE_NATIVE_SKELETON_V1"


def test_monster_bundle_blocks_native_physique_bone_missing_from_skeleton(tmp_path):
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "server"; (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT, "id": "bad_rig", "bundle_type": "MONSTER",
        "payload": {
            "identity": {"name": "Bad Rig"},
            "visual": {
                "model": {"output": "char/monster/bad/bad.smd", "mesh": {
                    "materials": [{"textures": []}],
                    "objects": [{
                        "name": "body", "vertices": [[0,0,0],[1,0,0],[0,1,0]],
                        "vertex_bones": ["missing", "missing", "missing"],
                        "faces": [{"vertices":[0,1,2],"material":0}],
                    }],
                }},
                "skeleton": {"output": "char/monster/bad/bad.smb", "skeleton": {"bones": [{"name": "root"}]}},
                "config": {"output": "char/monster/bad/bad.ini", "payload": {}},
            },
            "definition": {"fields": {"level": 1, "life": 10, "attack_speed": [1, 1]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "BLOCKED"
    assert any("MODEL_PACKAGE_CLOSURE_INCOMPLETE" in e for e in plan["errors"])
    missing = plan["visual_dependency"]["missing"]
    assert any(x.get("reason") == "MODEL_PHYSIQUE_BONES_UNRESOLVED" and "missing" in x.get("bones", []) for x in missing)
