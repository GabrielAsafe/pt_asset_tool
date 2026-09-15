from pathlib import Path

from pt_asset_tool.config import Settings
from pt_asset_tool.development_readiness import audit_development_readiness
from pt_asset_tool.profile_registry import CharacterProfileRegistry
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"


def test_readiness_is_machine_readable_and_never_promotes_candidates():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    profiles = CharacterProfileRegistry(ROOT / "data" / "character_profiles")
    report = audit_development_readiness(ROOT, CLIENT, registry, resolver, profiles, deep=False)
    assert report["status"] == "PASS"
    assert report["development_state"] == "IN_PROGRESS"
    assert report["client_modified"] is False
    assert report["policy"]["client_source_write_default"] is False
    assert report["stages"]["inx_writer"]["production_authorized"] is False
    assert report["stages"]["smb_writer"]["production_authorized"] is False
    assert report["stages"]["generic_publish_restore"]["production_authorized"] is False
    assert report["remaining_blocker_count"] > 0
    assert report["priorities"][0]["priority"] == "P0"


def test_mixed_physique_is_deferred_when_no_canonical_representative_exists():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    profiles = CharacterProfileRegistry(ROOT / "data" / "character_profiles")
    report = audit_development_readiness(ROOT, CLIENT, registry, resolver, profiles, deep=False)
    mixed = report["stages"]["mixed_physique"]
    assert mixed["evidence"]["mixed_count"] == 0
    assert mixed["maturity"] == "DEFERRED_NO_REPRESENTATIVE"
    assert mixed["production_authorized"] is False


def test_deep_readiness_promotes_candidate_evidence_only_to_source_semantic_level():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    profiles = CharacterProfileRegistry(ROOT / "data" / "character_profiles")
    report = audit_development_readiness(
        ROOT, CLIENT, registry, resolver, profiles,
        deep=True, animation_pair_limit=1, sample_limit=3,
    )
    semantic = report["deep_results"]["motion_writer_semantic_edit_corpus"]
    assert semantic["status"] == "PASS"
    assert report["stages"]["inx_writer"]["maturity"] == "CANDIDATE_SOURCE_SEMANTIC_EDIT_PROVEN"
    assert report["stages"]["smb_writer"]["maturity"] == "CANDIDATE_SOURCE_SEMANTIC_EDIT_PROVEN"
    assert report["stages"]["inx_writer"]["production_authorized"] is False
    assert report["stages"]["smb_writer"]["production_authorized"] is False
    assert report["stages"]["animation"]["evidence"]["candidate_writer_semantic_edit_status"] == "PASS"
