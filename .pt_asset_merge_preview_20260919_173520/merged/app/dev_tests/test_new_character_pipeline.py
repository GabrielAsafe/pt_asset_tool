import struct
from pathlib import Path

from pt_asset_tool.new_character_pipeline import (
    APPLY_CONFIRM, RESTORE_CONFIRM,
    plan_new_character, stage_new_character, publish_new_character,
    restore_new_character, new_character_status,
)
from pt_asset_tool.server_field_editor import SPC_ADD_NPC_CODE


def _write(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _spc_template() -> bytes:
    data = bytearray(50400)
    rec = bytearray(504)
    struct.pack_into("<iI", rec, 0, 504, SPC_ADD_NPC_CODE)
    rec[8:40] = b"DONOR\0" + b"\0" * (32 - 6)
    rec[40:104] = b"char\\npc\\donor.ini\0" + b"\0" * (64 - len(b"char\\npc\\donor.ini\0"))
    rec[104:164] = b"GameServer\\NPC\\donor.npc\0" + b"\0" * (60 - len(b"GameServer\\NPC\\donor.npc\0"))
    struct.pack_into("<8i", rec, 472, 0, 1, 2, 3, 0, 0, 0, 0)
    data[:504] = rec
    return bytes(data)


def test_npc_pipeline_stage_publish_restore_is_transactional(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "server"; server.mkdir()
    _write(client, "char/npc/newguy.inx", b"inx")
    _write(server, "GameServer/NPC/donor.npc", '*J_NAME \"Donor\"\r\n*모양파일 \"char\\npc\\donor.ini\"\r\n*공격속도 1.0 1.0\r\n'.encode('cp949'))
    spc = _write(server, "GameServer/Field/test.spc", _spc_template())
    before = spc.read_bytes()

    plan = plan_new_character(
        project, client, server, role="NPC", character_id="NewGuy", display_name="New Guy",
        model_ini="char/npc/newguy.ini", donor_definition="GameServer/NPC/donor.npc",
        field_path="GameServer/Field/test.spc",
    )
    assert plan["status"] == "PASS"
    staged = stage_new_character(
        project, client, server, role="NPC", character_id="NewGuy", display_name="New Guy",
        model_ini="char/npc/newguy.ini", donor_definition="GameServer/NPC/donor.npc",
        field_path="GameServer/Field/test.spc", x=100, z=200, slot_index=1,
    )
    assert staged["stage_status"] == "READY_FOR_PUBLISH"
    target_def_draft = Path(staged["draft_root"]) / "server/GameServer/NPC/NewGuy.npc"
    text = target_def_draft.read_text(encoding="cp949")
    assert '"New Guy"' in text
    assert "char\\npc\\newguy.ini" in text
    assert not (server / "GameServer/NPC/NewGuy.npc").exists()
    assert spc.read_bytes() == before

    tx = publish_new_character(project, client, server, "NewGuy", confirm=APPLY_CONFIRM)
    assert tx["state"] == "APPLIED_VERIFIED"
    assert (server / "GameServer/NPC/NewGuy.npc").is_file()
    assert spc.read_bytes() != before
    status = new_character_status(project, "NewGuy")
    assert status["can_restore"] is True

    restored = restore_new_character(project, client, server, "NewGuy", confirm=RESTORE_CONFIRM)
    assert restored["state"] == "RESTORED_VERIFIED"
    assert not (server / "GameServer/NPC/NewGuy.npc").exists()
    assert spc.read_bytes() == before


def test_player_visual_pipeline_stops_at_code_boundary(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    _write(client, "char/tmABCD/newclass.inx", b"inx")
    plan = plan_new_character(
        project, client, None, role="PLAYER_VISUAL", character_id="NewClass", display_name="New Class",
        model_ini="char/tmABCD/newclass.ini",
    )
    assert plan["status"] == "PASS"
    assert any(x["check"] == "PLAYER_CODE_BOUNDARY" and x["status"] == "REVIEW" for x in plan["checks"])
    assert any("class/job" in x for x in plan["code_boundary"])


def test_character_definition_requires_source_proven_name_model_and_attack_speed_contract(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "server"; server.mkdir()
    _write(client, "char/monster/new.inx", b"inx")
    _write(server, "GameServer/Monster/donor.inf", '*J_NAME "Donor"\r\n*모양파일 "char\\monster\\old.ini"\r\n*공격속도 1.0\r\n'.encode('cp949'))
    _write(server, "GameServer/Field/a.spm", b'*MAX_ACTOR 1\r\n')
    import pytest
    with pytest.raises(ValueError, match="DEFINITION_ROUNDTRIP_CONTRACT_FAILED"):
        stage_new_character(
            project, client, server, role="MONSTER", character_id="New", display_name="New",
            model_ini="char/monster/new.ini", donor_definition="GameServer/Monster/donor.inf",
            field_path="GameServer/Field/a.spm",
        )


def test_model_cache_freshness_blocks_changed_ini_with_opaque_inx(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "server"; server.mkdir()
    overlay = tmp_path / "overlay"
    _write(overlay, "char/npc/new.ini", b"config")
    _write(overlay, "char/npc/new.inx", b"opaque-cache")
    _write(server, "GameServer/NPC/donor.npc", '*J_NAME "Donor"\r\n*모양파일 "char\\npc\\donor.ini"\r\n'.encode('cp949'))
    _write(server, "GameServer/Field/a.spc", bytes(50400))
    plan = plan_new_character(
        project, client, server, role="NPC", character_id="New", display_name="New",
        model_ini="char/npc/new.ini", donor_definition="GameServer/NPC/donor.npc",
        field_path="GameServer/Field/a.spc", client_overlay=overlay,
    )
    assert plan["status"] == "BLOCKED"
    freshness = next(x for x in plan["checks"] if x["check"] == "MODEL_CACHE_FRESHNESS")
    assert freshness["detail"]["policy"] == "CACHE_FRESHNESS_UNPROVEN"
