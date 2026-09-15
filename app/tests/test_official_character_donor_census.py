from __future__ import annotations
import json
from pathlib import Path

from pt_asset_tool.official_character_donor_census import _extract_refs, _parse_donor_spec, _compare_donors


def test_parse_donor_spec(tmp_path):
    name, p = _parse_donor_spec(f"old={tmp_path}")
    assert name == "old"
    assert p == tmp_path.resolve()


def test_extract_refs(tmp_path):
    p = tmp_path / "cdata1"
    p.write_bytes(b"junk char\\tmABCD\\foo.smd\x00 x M2Bip.inx\x00 nope")
    refs = _extract_refs(p)
    joined = "\n".join(refs).lower()
    assert "foo.smd" in joined
    assert "m2bip.inx" in joined


def test_compare_donors_changed():
    a={"rows":[{"relative_path":"x.smd","sha256":"a","extension":".smd"}],"containers":[],"embedded_character_refs":["char/x.smd"]}
    b={"rows":[{"relative_path":"x.smd","sha256":"b","extension":".smd"}],"containers":[],"embedded_character_refs":["char/x.smd","char/y.smd"]}
    r=_compare_donors(a,b)
    assert r["direct_changed_hash_count"] == 1
    assert r["embedded_character_refs_common_count"] == 1
    assert r["embedded_character_refs_only_second"] == ["char/y.smd"]
