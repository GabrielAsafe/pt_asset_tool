from __future__ import annotations

import pathlib
import tempfile

import pytest

import pt_inx_motion_core_v2 as core
from pt_asset_tool.inx_writer import encode_end, encode_start, patch_motion, validate_noop_roundtrip

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE_CLIENT = ROOT.parent / "fixture_client"

requires_fixture = pytest.mark.skipif(not FIXTURE_CLIENT.is_dir(), reason="external fixture_client is not packaged")
ENTITY_INX_ROOT = ROOT.parent / "fixtures/entity_inx/pt_entity_catalog/files"
NONCANONICAL_FIXTURE = ENTITY_INX_ROOT / "char/monster/AncientGolem/AncientGolem.inx"

FIXTURES = [
    FIXTURE_CLIENT / "char/npc/Ahin/Ahin.inx",
    FIXTURE_CLIENT / "char/monster/Monbagon/Monbagon-A.inx",
    FIXTURE_CLIENT / "char/monster/Monbagon/Monbagon-C.inx",  # LEGACY_120
    FIXTURE_CLIENT / "char/monster/Acero/Acero.inx",
]


@pytest.mark.parametrize("path", FIXTURES)
@requires_fixture
def test_inx_noop_roundtrip_is_byte_identical(path):
    result = validate_noop_roundtrip(path)
    assert result["status"] == "PASS"
    assert result["byte_identical"] is True
    assert result["changed_byte_count"] == 0


@pytest.mark.parametrize("path", FIXTURES)
@requires_fixture
def test_keyword_encoder_is_exact_inverse_of_fixture_records(path):
    data = path.read_bytes()
    parsed = core.parse_inx(path)
    lay = parsed["layout"]
    for motion in parsed["motions"]:
        if motion["encoding"] != "KEYWORD_ENCODED":
            continue
        off = core.OFF_MOTIONINFO + motion["index"] * lay["motion_size"]
        assert encode_start(motion["start"], parsed["file_code"]) == (
            core.u32(data, off + 4), core.u32(data, off + 8)
        )
        assert encode_end(motion["end"], parsed["file_code"]) == (
            core.u32(data, off + 12), core.u32(data, off + 16)
        )


@pytest.mark.parametrize("path,state", [
    (FIXTURE_CLIENT / "char/npc/Ahin/Ahin.inx", "STAND"),
    (FIXTURE_CLIENT / "char/monster/Monbagon/Monbagon-A.inx", "ATTACK"),
    (FIXTURE_CLIENT / "char/monster/Monbagon/Monbagon-C.inx", "DAMAGE"),
    (FIXTURE_CLIENT / "char/monster/Acero/Acero.inx", "SKILL"),
])
@requires_fixture
def test_inx_candidate_edit_reparses_and_touches_only_allowlisted_bytes(path, state):
    parsed = core.parse_inx(path)
    motion = next(m for m in parsed["motions"] if m["state_name"] == state)
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / path.name
        result = patch_motion(
            path,
            out,
            motion=state,
            end=motion["end"] + 1,
            repeat=motion["repeat"] ^ 1,
        )
        assert result["status"] == "PASS"
        assert result["production_authorized"] is False
        assert result["client_modified"] is False
        assert result["file_size_preserved"] is True
        assert result["allowed_offsets_only"] is True
        reparsed = core.parse_inx(out)
        got = next(m for m in reparsed["motions"] if m["index"] == motion["index"])
        assert got["end"] == motion["end"] + 1
        assert got["repeat"] == (motion["repeat"] ^ 1)
        assert path.read_bytes() != out.read_bytes()


@requires_fixture
def test_inx_writer_rejects_noop_and_bad_ranges():
    path = FIXTURE_CLIENT / "char/npc/Ahin/Ahin.inx"
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "x.inx"
        with pytest.raises(ValueError, match="no MotionInfo edit requested"):
            patch_motion(path, out, motion="STAND")
        with pytest.raises(ValueError, match="end must be >= start"):
            patch_motion(path, out, motion="STAND", start=200, end=100)


@pytest.mark.skipif(not NONCANONICAL_FIXTURE.exists(), reason="entity INX corpus fixture not available")
def test_inx_noop_preserves_valid_noncanonical_encoded_frames():
    result = validate_noop_roundtrip(NONCANONICAL_FIXTURE)
    assert result["status"] == "PASS"
    assert result["byte_identical"] is True
    assert result["changed_byte_count"] == 0
    assert result["semantic_variant_record_count"] >= 1
    assert result["noncanonical_start_encoding_count"] >= 1


@pytest.mark.skipif(not NONCANONICAL_FIXTURE.exists(), reason="entity INX corpus fixture not available")
def test_inx_edit_preserves_untouched_noncanonical_frame_pair():
    parsed = core.parse_inx(NONCANONICAL_FIXTURE)
    motion = next(
        m for m in parsed["motions"]
        if m["encoding"] == "KEYWORD_ENCODED" and m["start"] == 0 and m["end"] < 0xFFFFFFFF
    )
    before = NONCANONICAL_FIXTURE.read_bytes()
    lay = parsed["layout"]
    off = core.OFF_MOTIONINFO + motion["index"] * lay["motion_size"]
    raw_start_before = before[off + 4:off + 12]
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / NONCANONICAL_FIXTURE.name
        result = patch_motion(
            NONCANONICAL_FIXTURE,
            out,
            motion=motion["index"],
            start=motion["start"],  # explicitly supplied but semantically unchanged
            end=motion["end"] + 1,
        )
        after = out.read_bytes()
        assert result["status"] == "PASS"
        assert "start" in result["semantic_noop_fields_ignored"]
        assert after[off + 4:off + 12] == raw_start_before
        assert after[off + 12:off + 20] != before[off + 12:off + 20]
