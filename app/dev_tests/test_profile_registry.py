from __future__ import annotations

import pathlib

from pt_asset_tool.profile_registry import CharacterProfileRegistry

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_canonical_profile_registry_has_corrected_identity_and_lods():
    reg = CharacterProfileRegistry(ROOT / "data" / "character_profiles")
    ids = {p.profile_id for p in reg.list()}
    assert ids == {"pikeman_c01_m4", "priestess_c01_m5"}
    priestess = reg.get("priestess_c01_m5")
    assert priestess.owner_name == "Priestess"
    assert priestess.profile_version == 3
    assert priestess.lod("high") == ["MbhC01", "MshC01", "MlhC01"]
    assert priestess.geometry_status["all_lods_runtime_proven"] is True
    pikeman = reg.get("pikeman_c01_m4")
    assert pikeman.geometry_status["all_lods_runtime_proven"] is False


def test_lod_all_is_stable_unique_order():
    reg = CharacterProfileRegistry(ROOT / "data" / "character_profiles")
    p = reg.get("priestess_c01_m5")
    all_objects = p.lod("all")
    assert all_objects[:3] == p.lod("high")
    assert len(all_objects) == len(set(all_objects))


def test_profile_verify_detects_required_components_on_fixture_client():
    from pt_asset_tool.resolver import ClientResolver
    root = ROOT
    client = root.parent / "fixture_client"
    reg = CharacterProfileRegistry(root / "data" / "character_profiles")
    # The partial fixture client is not expected to contain the canonical player
    # profiles; verification must fail cleanly rather than authorize anything.
    result = reg.verify("pikeman_c01_m4", ClientResolver(client))
    assert result["status"] in {"PASS", "FAIL"}
    assert result["authoring_authorized"] is False
    assert result["client_modified"] is False
    assert result["components"]
    if result["status"] == "FAIL":
        assert result["failures"]


def test_profile_match_asset_uses_exact_path_evidence_only():
    reg = CharacterProfileRegistry(ROOT / "data" / "character_profiles")
    hits = reg.match_asset("char/tmABCD/TmbC01.smd")
    assert len(hits) == 1
    assert hits[0]["profile_id"] == "pikeman_c01_m4"
    assert "PROFILE_MODEL" in hits[0]["roles"]
    assert hits[0]["evidence"] == "EXACT_PROFILE_PATH"
    # Same basename in a different tree is not enough to claim the profile.
    assert reg.match_asset("char/other/TmbC01.smd") == []
