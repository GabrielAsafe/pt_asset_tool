import hashlib
import struct
from pathlib import Path

from pt_asset_tool.server_field_editor import (
    SPC_ADD_NPC_CODE,
    inspect_field_metadata,
    stage_spc_clone,
    stage_spm_text,
    stage_spp_records,
)


def _write(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_spm_inspect_and_stage_preserves_server_source(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    source = _write(server, "GameServer/Field/test.spm", '*MAX_ACTOR 3\r\n*ACTOR "Goblin" 100\r\n'.encode("cp949"))
    before = source.read_bytes()
    report = inspect_field_metadata(project, server, "gameserver/field/TEST.SPM")
    assert report["type"] == "SPM"
    assert report["detail"]["actors"] == [{"name": "Goblin", "weight": 100}]
    draft = stage_spm_text(project, server, "GameServer/Field/test.spm", '*MAX_ACTOR 4\n*ACTOR "Goblin" 90\n', expected_sha256=report["source_sha256"])
    assert source.read_bytes() == before
    assert Path(draft["draft"]).is_file()
    assert b"\r\n" in Path(draft["draft"]).read_bytes()
    assert draft["server_write_authorized"] is False


def test_spp_structured_record_stage_is_2400_and_source_unchanged(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    raw = bytearray(2400)
    struct.pack_into("<iii", raw, 0, 1, 10, 20)
    source = _write(server, "GameServer/Field/a.spp", bytes(raw))
    before = source.read_bytes()
    report = inspect_field_metadata(project, server, "GameServer/Field/a.spp")
    assert report["detail"]["record_count"] == 200
    draft = stage_spp_records(project, server, "GameServer/Field/a.spp", [{"index": 0, "state": 2, "x": 30, "z": 40}], expected_sha256=report["source_sha256"])
    assert source.read_bytes() == before
    out = Path(draft["draft"]).read_bytes()
    assert len(out) == 2400
    assert struct.unpack_from("<iii", out, 0) == (2, 30, 40)


def _spc_template() -> bytes:
    data = bytearray(50400)
    rec = bytearray(504)
    struct.pack_into("<iI", rec, 0, 504, SPC_ADD_NPC_CODE)
    rec[8:40] = b"DONOR\0" + b"\0" * (32 - 6)
    rec[40:104] = b"char\\npc\\donor.ini\0" + b"\0" * (64 - len(b"char\\npc\\donor.ini\0"))
    rec[104:164] = b"GameServer\\NPC\\donor.npc\0" + b"\0" * (60 - len(b"GameServer\\NPC\\donor.npc\0"))
    struct.pack_into("<8i", rec, 472, 12345, 1, 2, 3, 4, 5, 6, 7)
    data[:504] = rec
    return bytes(data)


def test_spc_clone_patch_uses_known_add_npc_and_blank_slot_only(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    source = _write(server, "GameServer/Field/a.spc", _spc_template())
    before_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    report = inspect_field_metadata(project, server, "GameServer/Field/a.spc")
    assert report["detail"]["standard_add_npc_count"] == 1
    draft = stage_spc_clone(
        project, server, "GameServer/Field/a.spc",
        template_index=0, slot_index=1,
        record_name="Merchant", model_ini="char/npc/shop.ini", server_npc="GameServer/NPC/shop.npc",
        x=100, y=0, z=200, ay=90, expected_sha256=report["source_sha256"],
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_sha
    out = Path(draft["draft"]).read_bytes()
    size, code = struct.unpack_from("<iI", out, 504)
    assert size == 504 and code == SPC_ADD_NPC_CODE
    tail = struct.unpack_from("<8i", out, 504 + 472)
    assert tail == (0, 100, 0, 200, 0, 90, 0, 0)
    assert draft["detail"]["synthetic_from_zero_authoring"].startswith("BLOCKED")
