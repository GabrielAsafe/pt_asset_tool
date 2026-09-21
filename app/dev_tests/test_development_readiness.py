from pathlib import Path
from dev_tests._runtime_context import runtime_settings, runtime_registry
from pt_asset_tool.resolver import ClientResolver

from pt_asset_tool.development_readiness import audit_development_readiness
from pt_asset_tool.profile_registry import CharacterProfileRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_readiness_is_machine_readable_and_never_promotes_candidates():
    settings = runtime_settings()
    resolver = ClientResolver(settings.client_root)
    registry = runtime_registry()
    profiles = CharacterProfileRegistry(ROOT / "dev_tests" / "fixtures" / "character_profiles")
    report = audit_development_readiness(ROOT, settings.client_root, registry, resolver, profiles, deep=False)
    assert report["status"] == "PASS"
    assert report["development_state"] == "IN_PROGRESS"
    assert report["client_modified"] is False
    assert report["policy"]["client_source_write_default"] is False
    assert report["stages"]["inx_writer"]["production_authorized"] is False
    assert report["stages"]["smb_writer"]["production_authorized"] is False
    assert report["stages"]["generic_publish_restore"]["production_authorized"] is False
    assert report["remaining_blocker_count"] > 0
    assert report["priorities"][0]["priority"] == "P0"


def test_mixed_physique_reports_synthetic_implementation_when_no_canonical_representative_exists():
    settings = runtime_settings()
    resolver = ClientResolver(settings.client_root)
    registry = runtime_registry()
    profiles = CharacterProfileRegistry(ROOT / "dev_tests" / "fixtures" / "character_profiles")
    report = audit_development_readiness(ROOT, settings.client_root, registry, resolver, profiles, deep=False)
    mixed = report["stages"]["mixed_physique"]
    assert mixed["evidence"]["mixed_count"] == 0
    assert mixed["maturity"] == "IMPLEMENTED_SYNTHETIC_AWAITING_REAL_REPRESENTATIVE"
    assert mixed["production_authorized"] is False


def test_deep_readiness_promotes_candidate_evidence_only_to_source_semantic_level(monkeypatch):
    # PT_DEEP_READINESS_SEMANTIC_PROMOTION_STUB_V1
    # This test verifies readiness promotion logic, not physical-corpus coverage.
    # Real corpus semantics (full PASS vs truncated fail-closed) are covered in
    # test_writer_corpus_audit.py.  Using pair_limit=1 against a real client is
    # intentionally incomplete and therefore cannot legitimately return PASS.
    import pt_asset_tool.development_readiness as readiness_mod

    monkeypatch.setattr(
        readiness_mod,
        "audit_motion_writer_semantic_edit_corpus",
        lambda *args, **kwargs: {
            "status": "PASS",
            "inx_semantic_edit_pass": 1,
            "smb_semantic_edit_pass": 1,
            "audited_contexts": 1,
            "registry_motion_contexts": 1,
            "corpus_complete": True,
            "selection_limited": False,
            "fail_count": 0,
            "production_authorized": False,
            "client_modified": False,
        },
    )
    settings = runtime_settings()
    resolver = ClientResolver(settings.client_root)
    registry = runtime_registry()
    profiles = CharacterProfileRegistry(ROOT / "dev_tests" / "fixtures" / "character_profiles")
    report = audit_development_readiness(
        ROOT, settings.client_root, registry, resolver, profiles,
        deep=True, animation_pair_limit=1, sample_limit=3,
    )
    semantic = report["deep_results"]["motion_writer_semantic_edit_corpus"]
    assert semantic["status"] == "PASS"
    assert report["stages"]["inx_writer"]["maturity"] == "CANDIDATE_SOURCE_SEMANTIC_EDIT_PROVEN"
    assert report["stages"]["smb_writer"]["maturity"] == "CANDIDATE_SOURCE_SEMANTIC_EDIT_PROVEN"
    assert report["stages"]["inx_writer"]["production_authorized"] is False
    assert report["stages"]["smb_writer"]["production_authorized"] is False
    assert report["stages"]["animation"]["evidence"]["candidate_writer_semantic_edit_status"] == "PASS"
