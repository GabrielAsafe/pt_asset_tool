from pathlib import Path
from dev_tests._runtime_context import runtime_registry

from pt_asset_tool.profile_candidates import discover_profile_candidates
from pt_asset_tool.profile_registry import CharacterProfileRegistry

ROOT = Path(__file__).resolve().parents[1]


def _context():
    registry = runtime_registry()
    profiles = CharacterProfileRegistry(ROOT / "dev_tests" / "fixtures" / "character_profiles")
    return registry, profiles


def test_profile_candidate_discovery_is_fail_closed_and_uses_real_lod_nodes():
    registry, profiles = _context()
    report = discover_profile_candidates(registry, limit=0, profile_registry=profiles)
    assert report["status"] == "PASS"
    assert report["candidate_count"] > 0
    assert report["policy"]["folder_or_basename_guessing"] is False
    assert report["policy"]["discovery_authorizes_writer"] is False
    assert all(row["authoring_authorized"] is False for row in report["candidates"])
    m5 = [row for row in report["candidates"] if row["asset"].casefold() == "char/tmabcd/mfbc01.smd" and row["inx"].casefold().endswith("/m5bip.inx")]
    assert len(m5) == 1
    row = m5[0]
    assert row["lod_nodes_present_in_smd"] is True
    assert row["all_three_lod_tiers_present"] is True
    assert row["binding_ready"] is True
    assert any(p["profile_id"] == "priestess_c01_m5" for p in row["canonical_profiles"])
    assert row["runtime_proven"] is True
    assert row["state"] == "CANONICAL_RUNTIME_PROVEN"


def test_profile_candidate_discovery_category_filter_uses_semantic_group():
    registry, profiles = _context()
    report = discover_profile_candidates(registry, category="NPC", limit=20, profile_registry=profiles)
    assert report["category_filter"] == "NPC"
    assert all(row["semantic_group"] == "NPC" for row in report["candidates"])
    assert report["shown_count"] <= 20


def test_profile_discovery_marks_ambiguous_multi_inx_contexts_without_promoting_authoring():
    from types import SimpleNamespace
    ambiguous = SimpleNamespace(
        family="SMD_MODEL_062_RIGID_PHYSIQUE", primary_path="char/test/body.smd", category="CHARACTER",
        asset_id="AST-AMB", configs=[
            {"inx":"char/test/a.inx","motion_smb":"char/test/body.smb","lod_groups":{"high":["HiA"],"default":["Body"],"low":["Lo"]}},
            {"inx":"char/test/b.inx","motion_smb":"char/test/body.smb","lod_groups":{"high":["HiB"],"default":["Body"],"low":["Lo"]}},
        ],
        source_record={"object_names":["HiA","HiB","Body","Lo"]},
        rigid_binding_ready=True, binding_skeleton_smb="char/test/body.smb",
        binding_mode="ROOT_SKELETON_BOUND", binding_source="TEST",
    )
    report=discover_profile_candidates(SimpleNamespace(assets=[ambiguous]), limit=0)
    assert report["model_info_context_state_counts"]["AMBIGUOUS_MODEL_INFO_CONFIG"] == 1
    assert len(report["candidates"]) == 2
    assert all(row["requires_explicit_model_info"] is True for row in report["candidates"])
    assert len({row["semantic_context_id"] for row in report["candidates"]}) == 2
    assert all(row["authoring_authorized"] is False for row in report["candidates"])
