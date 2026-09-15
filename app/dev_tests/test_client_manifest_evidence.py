from __future__ import annotations

import struct
from pathlib import Path

from pt_asset_tool.client_manifest_evidence import MAGIC, RECORD_SIZE, parse_fixed_manifest


def _record(path: bytes, *, flag: int = 0, size: int = 123, final: int = 77) -> bytes:
    field = path[:64].ljust(64, b"\0")
    return struct.pack("<I", flag) + field + struct.pack("<IIQI", size, 0, 0, final)


def test_fixed_manifest_parses_exact_and_boundary_paths_without_claiming_final_field(tmp_path):
    p = tmp_path / "setfile.lst"
    exact = b"Effect\\Particle\\Script\\DarkBolt.part"
    boundary = b"A" * 63
    payload = struct.pack("<II", MAGIC, 2) + _record(exact, flag=1) + _record(boundary) + (b"\0" * 20)
    assert len(_record(exact)) == RECORD_SIZE
    p.write_bytes(payload)

    result = parse_fixed_manifest(p)
    assert result["status"] == "PASS"
    assert result["record_count"] == 2
    assert result["canonical_20_byte_trailer"] is True
    assert result["boundary_count"] == 1
    assert result["records"][0]["path"] == "Effect/Particle/Script/DarkBolt.part"
    assert result["records"][0]["evidence_strength"] == "MANIFEST_EXACT"
    assert result["records"][1]["evidence_strength"] == "TRUNCATED_PREFIX_REVIEW"
    assert result["records"][1]["path_boundary_risk"] is True
    assert result["records"][0]["final_u32_unknown"] == 77
    assert result["policy"]["final_u32_semantics_claimed"] is False
