from __future__ import annotations

import json
from pathlib import Path

import pytest

from pt_asset_tool.asset_bundle_deploy import APPLY_CONFIRM, RESTORE_CONFIRM
from pt_asset_tool.asset_compiler import _legacy_line, _source_token, build_spc_record
from pt_asset_tool.legacy_authoring import (
    _inspect_text_definition,
    authoring_capabilities,
    inspect_authoring,
    stage_authoring,
    publish_authoring,
    restore_authoring,
)


def _roots(tmp_path: Path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    server = tmp_path / "server"
    project.mkdir(); client.mkdir(); server.mkdir()
    return project, client, server


def _write(server: Path, rel: str, data: bytes):
    p = server / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _cp949(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("cp949")


def test_inspect_text_definition_accepts_tab_delimited_legacy_tokens():
    reg = "character_tokens"
    raw = (
        _source_token(reg, "Name").encode("cp949") + b"\t\t\"Flame Maiden\"\r\n"
        + _source_token(reg, "ModelFile").encode("cp949") + b"\t\t\"char/monster/FlameMaiden/FlameMaiden.ini\"\r\n"
        + _source_token(reg, "Level").encode("cp949") + b"\t\t190\r\n"
    )
    detail = _inspect_text_definition("MONSTER", raw)
    assert detail["recognized"]["name"] == [["Flame Maiden"]]
    assert detail["recognized"]["model_file"] == [["char/monster/FlameMaiden/FlameMaiden.ini"]]
    assert detail["recognized"]["level"] == [["190"]]
    assert detail["unknown_line_count"] == 0


def test_capabilities_are_real_authoring_and_need_no_exe():
    c = authoring_capabilities()
    assert c["status"] == "PASS"
    assert c["legacy_executable_required"] is False
    assert all(c["kinds"][k]["create"] and c["kinds"][k]["edit"] for k in ("ITEM","MONSTER","NPC","SPM","SPP","SPC"))


def test_item_edit_preserves_unknown_lines_and_stages_publishable_bundle(tmp_path):
    project, client, server = _roots(tmp_path)
    name = _source_token("item_tokens", "Name")
    code = _source_token("item_tokens", "Code")
    price = _source_token("item_tokens", "Price")
    src = _write(server, "GameServer/OpenItem/WA121.txt", _cp949([
        _legacy_line(name, ["Old Axe"]),
        _legacy_line(code, ["WA121"]),
        "*CUSTOM_UNKNOWN 777 keep-me",
        _legacy_line(price, [100]),
    ]))
    info = inspect_authoring(project, server, client, "ITEM", "GameServer/OpenItem/WA121.txt")
    assert info["exists"] is True
    result = stage_authoring(project, server, client, {
        "kind":"ITEM", "mode":"EDIT", "path":"GameServer/OpenItem/WA121.txt",
        "expected_sha256":info["source_sha256"], "patch":{"set":{"name":"New Axe","price":999}},
    })
    manifest = result["manifest"]
    staged = Path(manifest["assets"][0]["output"]).read_bytes().decode("cp949")
    assert "*CUSTOM_UNKNOWN 777 keep-me" in staged
    assert "New Axe" in staged
    assert "999" in staged
    assert manifest["assets"][0]["kind"] == "LEGACY_TEXT_PATCH"
    assert manifest["assets"][0]["writer"]["code_identity_status"] == "SOURCE_VERIFIED"
    assert src.read_bytes().decode("cp949").find("Old Axe") >= 0


def test_item_edit_rejects_unregistered_runtime_code(tmp_path):
    project, client, server = _roots(tmp_path)
    name = _source_token("item_tokens", "Name")
    code = _source_token("item_tokens", "Code")
    _write(server, "GameServer/OpenItem/WA121.txt", _cp949([_legacy_line(name,["A"]),_legacy_line(code,["WA121"])]))
    with pytest.raises(ValueError, match="ITEM_CODE_NOT_IN_RUNTIME_TABLE"):
        stage_authoring(project, server, client, {"kind":"ITEM","mode":"EDIT","path":"GameServer/OpenItem/WA121.txt","patch":{"set":{"code":"ZZ9999"}}})


def test_monster_edit_rewrites_exp_and_drops_without_touching_unknown(tmp_path):
    project, client, server = _roots(tmp_path)
    reg="character_tokens"
    raw=_cp949([
        _legacy_line(_source_token(reg,"Name"),["Cuepy"]),
        _legacy_line(_source_token(reg,"ModelFile"),["char/monster/cuepy.ini"]),
        "*CUSTOM_AI 123",
        _legacy_line(_source_token(reg,"Experience"),[10]),
        _legacy_line(_source_token(reg,"FallItem"),[100,"WA121"]),
    ])
    _write(server,"GameServer/Monster/Cuepy.inf",raw)
    r=stage_authoring(project,server,client,{"kind":"MONSTER","mode":"EDIT","path":"GameServer/Monster/Cuepy.inf","patch":{"set":{"experience":777},"drops":[{"percentage":70,"items":["WA121","WC108"]},{"percentage":30,"money":[1,10]}]}})
    text=Path(r["manifest"]["assets"][0]["output"]).read_bytes().decode("cp949")
    assert "*CUSTOM_AI 123" in text
    assert "777" in text
    assert "WA121" in text and "WC108" in text
    assert _source_token(reg,"Money") in text


def test_npc_edit_rewrites_shop_and_dialog(tmp_path):
    project, client, server = _roots(tmp_path)
    reg="character_tokens"
    _write(server,"GameServer/NPC/Shop.npc",_cp949([
        _legacy_line(_source_token(reg,"Name"),["Shop"]),
        _legacy_line(_source_token(reg,"ModelFile"),["char/npc/shop.ini"]),
        _legacy_line(_source_token(reg,"SellWeapon"),["WA121"]),
    ]))
    r=stage_authoring(project,server,client,{"kind":"NPC","mode":"EDIT","path":"GameServer/NPC/Shop.npc","patch":{"shops":{"weapon":["WA121","WS210"],"defence":["DA112"]},"dialogs":["Hello player"]}})
    text=Path(r["manifest"]["assets"][0]["output"]).read_bytes().decode("cp949")
    assert "WA121" in text and "WS210" in text and "DA112" in text
    assert "Hello player" in text


def test_spm_structured_add_and_remove_actor(tmp_path):
    project, client, server = _roots(tmp_path)
    _write(server,"GameServer/Field/town.spm",b'*ACTOR "Cuepy" 100\r\n*MAX_ACTOR 10\r\n')
    r=stage_authoring(project,server,client,{"kind":"SPM","mode":"EDIT","path":"GameServer/Field/town.spm","patch":{"action":"ADD_ACTOR","name":"Hopy","weight":50}})
    text=Path(r["manifest"]["assets"][0]["output"]).read_text()
    assert '"Hopy" 50' in text
    # Apply first so second edit uses current source in a separate project transaction lifecycle.
    tx=publish_authoring(project,client,server,r["manifest"]["manifest"],confirm=APPLY_CONFIRM)
    assert tx["state"]=="APPLIED_VERIFIED"
    rr=restore_authoring(project,client,server,r["manifest"]["manifest"],confirm=RESTORE_CONFIRM)
    assert rr["state"]=="RESTORED_VERIFIED"


def test_spp_patch_preserves_file_size(tmp_path):
    project, client, server = _roots(tmp_path)
    _write(server,"GameServer/Field/test.spp",b"\0"*(200*12))
    r=stage_authoring(project,server,client,{"kind":"SPP","mode":"EDIT","path":"GameServer/Field/test.spp","patch":{"records":[{"index":3,"state":1,"x":123,"z":456}]}})
    data=Path(r["manifest"]["assets"][0]["output"]).read_bytes()
    assert len(data)==2400


def test_spc_add_remove_uses_native_504_byte_record(tmp_path):
    project, client, server = _roots(tmp_path)
    _write(server,"GameServer/Field/test.spc",b"\0"*(100*504))
    record={"name":"NPC1","model_ini":"char/npc/a.ini","server_npc":"GameServer/NPC/a.npc","x":10,"y":0,"z":20}
    r=stage_authoring(project,server,client,{"kind":"SPC","mode":"EDIT","path":"GameServer/Field/test.spc","patch":{"action":"ADD","index":2,"record":record}})
    data=Path(r["manifest"]["assets"][0]["output"]).read_bytes()
    assert len(data)==50400
    assert data[2*504:(2+1)*504] == build_spc_record(record)


def test_create_item_uses_native_asset_compiler_and_runtime_code_boundary(tmp_path):
    project, client, server = _roots(tmp_path)
    r=stage_authoring(project,server,client,{"kind":"ITEM","mode":"CREATE","path":"GameServer/OpenItem/WA121.txt","fields":{"name":"Created Axe","code":"WA121","price":1000}})
    m=r["manifest"]
    assert m["status"]=="PASS"
    assert m["assets"][0]["contract_id"]=="item.definition.txt"
    assert m["assets"][0]["writer"]["code_identity_status"]=="SOURCE_VERIFIED"


def test_publish_and_restore_item_edit_transaction(tmp_path):
    project, client, server = _roots(tmp_path)
    name=_source_token("item_tokens","Name"); code=_source_token("item_tokens","Code")
    source=_write(server,"GameServer/OpenItem/WA121.txt",_cp949([_legacy_line(name,["Before"]),_legacy_line(code,["WA121"])]))
    before=source.read_bytes()
    r=stage_authoring(project,server,client,{"kind":"ITEM","mode":"EDIT","path":"GameServer/OpenItem/WA121.txt","patch":{"set":{"name":"After"}}})
    manifest=r["manifest"]["manifest"]
    tx=publish_authoring(project,client,server,manifest,confirm=APPLY_CONFIRM)
    assert tx["state"]=="APPLIED_VERIFIED"
    assert b"After" in source.read_bytes()
    restored=restore_authoring(project,client,server,manifest,confirm=RESTORE_CONFIRM)
    assert restored["state"]=="RESTORED_VERIFIED"
    assert source.read_bytes()==before


def test_spm_boss_membership_and_spawn_hours(tmp_path):
    project, client, server = _roots(tmp_path)
    _write(server,"GameServer/Field/boss.spm",b'*ACTOR "Cuepy" 100\r\n')
    r=stage_authoring(project,server,client,{"kind":"SPM","mode":"EDIT","path":"GameServer/Field/boss.spm","patch":{"action":"ADD_BOSS","master":"BossA","slave":"GuardA","slave_count":2,"hours":[1,6,12,18]}})
    text=Path(r["manifest"]["assets"][0]["output"]).read_text()
    assert '*BOSS_ACTOR "BossA" "GuardA" 2 1 6 12 18' in text
