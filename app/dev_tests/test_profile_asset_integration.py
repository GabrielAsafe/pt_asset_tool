from pathlib import Path

from pt_asset_tool.profile_registry import CharacterProfileRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_profile_component_paths_map_to_roles():
    reg = CharacterProfileRegistry(ROOT / "data" / "character_profiles")
    hits = reg.match_asset("char/tmABCD/m4.smb")
    assert hits and hits[0]["profile_id"] == "pikeman_c01_m4"
    assert "SKELETON" in hits[0]["roles"]
