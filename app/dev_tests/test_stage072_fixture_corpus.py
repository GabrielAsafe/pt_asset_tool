from __future__ import annotations

import os
import pathlib

import pytest

from pt_asset_tool.stage072_corpus import parse_stage072

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"


def _stage_files():
    out = []
    for path in CLIENT.rglob("*.smd"):
        try:
            head = path.read_bytes()[:64]
        except OSError:
            continue
        if head.startswith(b"SMD Stage data Ver 0.72"):
            out.append(path)
    return sorted(out)


def _parse(rel: str):
    path = CLIENT / rel
    assert path.is_file(), rel
    row = parse_stage072(path, include_payload=True)
    assert row.get("full_parse") == "PASS", (rel, row.get("parse_error"))
    return row


def test_supplied_stage072_representatives_cover_known_layouts_fast():
    # Smallest known fixture for each layout plus one depth-3 TexLink sample.
    dword = _parse("Field/Room/office.smd")
    trailing = _parse("cSelect/select.smd")
    word16 = _parse("Field/Lost/lost.smd")
    depth3 = _parse("Field/endless/dun-7.smd")

    assert (dword.get("area") or {}).get("encoding") == "DWORD32"
    assert (trailing.get("area") or {}).get("encoding") == "DWORD32_TRAILING_OPAQUE"
    assert (word16.get("area") or {}).get("encoding") == "WORD16"
    assert int(depth3.get("max_texlink_depth") or 0) >= 3


@pytest.mark.skipif(os.environ.get("PT_RUN_SLOW_FIXTURE_TESTS") != "1", reason="full 188MB Stage0.72 corpus is opt-in")
def test_all_supplied_stage072_fixtures_parse_fully_slow():
    files = _stage_files()
    assert len(files) >= 30
    parsed = [parse_stage072(path, include_payload=True) for path in files]
    failures = [(str(path), row.get("parse_error")) for path, row in zip(files, parsed) if row.get("full_parse") != "PASS"]
    assert failures == []
    assert max(int(row.get("max_texlink_depth") or 0) for row in parsed) >= 3
    area_encodings = {(row.get("area") or {}).get("encoding") for row in parsed}
    assert {"DWORD32", "DWORD32_TRAILING_OPAQUE", "WORD16"} <= area_encodings
