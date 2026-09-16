from pathlib import Path

import pytest
from pt_asset_tool.binding_coverage import audit_binding_coverage
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

pytestmark = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")


def test_binding_coverage_is_diagnostic_and_fail_closed():
    settings = Settings.discover(ROOT, CLIENT)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=ClientResolver(CLIENT))
    report = audit_binding_coverage(reg, category="MONSTER", sample_limit=10)
    assert report["status"] == "PASS"
    assert report["scope"] == "DIAGNOSTIC_ONLY_NO_BINDING_PROMOTION"
    assert report["policy"]["folder_identity_is_binding_evidence"] is False
    assert report["policy"]["registry_binding_rules_unchanged"] is True
    assert report["rigid_asset_count"] >= report["rigid_binding_ready_count"]
    assert report["unresolved_binding_count"] == report["rigid_asset_count"] - report["rigid_binding_ready_count"]
    assert len(report["unresolved_sample"]) <= 10


def test_binding_coverage_distinguishes_semantic_from_physical_readiness():
    settings = Settings.discover(ROOT, CLIENT)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=ClientResolver(CLIENT))
    report = audit_binding_coverage(reg, category="MONSTER", sample_limit=0)
    assert report["rigid_binding_ready_count"] >= report["physical_rigid_binding_ready_count"]
    assert report["animation_binding_ready_count"] >= report["physical_animation_binding_ready_count"]
