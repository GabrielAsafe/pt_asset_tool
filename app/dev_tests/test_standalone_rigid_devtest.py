from pathlib import Path

from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.release_1_coverage import content_domain
from pt_asset_tool.standalone_rigid_devtest import (
    choose_standalone_rigid_representatives,
    sibling_smb_candidates,
    standalone_rigid_context_eligible,
)

ROOT = Path(__file__).resolve().parents[1]


def _registry():
    return AssetRegistry(ROOT / "data/asset_registry/asset_inventory.json", ROOT / "data/asset_registry/inx_physical_pairing.csv")


def test_unbound_effect_and_map_rigid_assets_have_deterministic_sibling_hypotheses():
    reg = _registry()
    for domain, expected in (("EFFECT", 27), ("MAP", 36)):
        assets = [a for a in reg.assets if a.family == "SMD_MODEL_062_RIGID_PHYSIQUE" and content_domain(a) == domain]
        assert len(assets) == expected
        assert all(not a.rigid_binding_ready for a in assets)
        probes = [sibling_smb_candidates(reg, a) for a in assets]
        assert all(p["candidate_available"] for p in probes)
        assert all(p["binding_proven"] is False for p in probes)
        assert all(p["requires_structural_gate"] is True for p in probes)


def test_map_rigid_assets_use_exact_sibling_stem_hypotheses():
    reg = _registry()
    reps = choose_standalone_rigid_representatives(reg, "MAP", limit=3)
    assert len(reps) == 3
    assert all(r["candidate_basis"] == "EXACT_SIBLING_STEM" for r in reps)
    assert all(Path(r["asset"]).stem.casefold() == Path(r["skeleton_smb"]).stem.casefold() for r in reps)


def test_effect_representatives_include_exact_and_unique_directory_hypotheses():
    reg = _registry()
    reps = choose_standalone_rigid_representatives(reg, "EFFECT", limit=4)
    assert reps
    assert any(r["candidate_basis"] == "EXACT_SIBLING_STEM" for r in reps)
    # The corpus also contains Pet-style models whose single sibling is Pet_motion.smb.
    all_effect = choose_standalone_rigid_representatives(reg, "EFFECT", limit=100)
    assert any(r["candidate_basis"] == "UNIQUE_DIRECTORY_SMB" for r in all_effect)


def test_player_equipment_inx_without_motion_smb_remains_standalone_eligible():
    reg = _registry()
    reps = choose_standalone_rigid_representatives(reg, "PLAYER", limit=10)
    assert reps
    # These class/equipment models really do carry INX rows, but no usable
    # motion_smb context.  Presence of configs must not block structural SMB
    # authoring.
    for row in reps:
        asset = reg.resolve(row["asset"])
        assert asset.configs
        assert standalone_rigid_context_eligible(asset) is True
