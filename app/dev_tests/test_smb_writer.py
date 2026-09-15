from __future__ import annotations

import pathlib
import tempfile

import pytest

from pt_asset_tool.motion_core import load_smb_evaluator
from pt_asset_tool.smb_writer import patch_key, validate_track_roundtrip

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"
AHIN_FULL = ROOT.parent / "fixtures/Ahin/Ahin/Ahinf.smb"
SMBS = [
    CLIENT / "char/npc/Ahin/Ahin.smb",
    CLIENT / "char/monster/Monbagon/mbagon.smb",
    CLIENT / "char/monster/Acero/Acero.smb",
]


@pytest.mark.parametrize("path", SMBS)
def test_smb_track_roundtrip_is_byte_identical(path):
    r = validate_track_roundtrip(ROOT, path)
    assert r["status"] == "PASS"
    assert r["byte_identical"] is True
    assert r["changed_byte_count"] == 0


def test_smb_candidate_position_key_edit_reparses_and_preserves_source():
    source = CLIENT / "char/monster/Acero/Acero.smb"
    evaluator = load_smb_evaluator(ROOT)
    parsed = evaluator.parse_smb(source)
    bone = next(b for b in parsed["bones"] if b["pos"])
    old = bone["pos"][0]
    before = source.read_bytes()
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "Acero_edit.smb"
        r = patch_key(ROOT, source, out, bone=bone["name"], track="pos", key_index=0, x=old[1] + 0.25)
        assert r["status"] == "PASS"
        assert r["production_authorized"] is False
        assert r["allowed_offsets_only"] is True
        assert r["file_size_preserved"] is True
        assert source.read_bytes() == before
        edited = evaluator.parse_smb(out)
        got = next(b for b in edited["bones"] if b["name"] == bone["name"])["pos"][0]
        assert got[1] != old[1]


def test_smb_writer_rejects_key_insertion_and_noop_shape_by_api():
    source = CLIENT / "char/npc/Ahin/Ahin.smb"
    evaluator = load_smb_evaluator(ROOT)
    parsed = evaluator.parse_smb(source)
    bone = next(b for b in parsed["bones"] if b["pos"])
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "x.smb"
        with pytest.raises(IndexError):
            patch_key(ROOT, source, out, bone=bone["name"], track="pos", key_index=999999, x=1)
        with pytest.raises(ValueError, match="no key component"):
            patch_key(ROOT, source, out, bone=bone["name"], track="pos", key_index=0)


@pytest.mark.skipif(not AHIN_FULL.exists(), reason="Ahin external-parent SMB fixture not available")
def test_smb_writer_roundtrip_does_not_require_closed_animation_hierarchy():
    r = validate_track_roundtrip(ROOT, AHIN_FULL)
    assert r["status"] == "PASS"
    assert r["byte_identical"] is True
    assert r["hierarchy_closed"] is False
    assert "Bip01 Head" in r["missing_parent_names"]
