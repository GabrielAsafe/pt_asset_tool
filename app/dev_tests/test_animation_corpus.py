from __future__ import annotations

from pathlib import Path

import pytest
from pt_asset_tool.animation_corpus import audit_animation_corpus
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

pytestmark = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")


def _registry():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    return settings, resolver, AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)


def test_animation_corpus_is_deduplicated_and_diagnostic():
    settings, resolver, reg = _registry()
    report = audit_animation_corpus(settings.project_root, reg, resolver, mode="core", pair_limit=3)
    assert report["status"] == "PASS"
    assert report["scope"] == "SOURCE_SIDE_CORPUS_SANITY_NOT_VISUAL_CERTIFICATION"
    assert report["visual_certification"] is False
    assert report["blender_pose_space_certification"] is False
    assert report["binding_promotion"] is False
    assert report["client_modified"] is False
    assert 1 <= report["audited_contexts"] <= 3
    assert report["failed_contexts"] == 0
    assert report["total_audited_motions"] >= report["audited_contexts"]
    assert all(row["status"] == "PASS" for row in report["rows"])


def test_animation_corpus_category_filter_preserves_fail_closed_semantics():
    settings, resolver, reg = _registry()
    report = audit_animation_corpus(settings.project_root, reg, resolver, category="MONSTER", mode="core", pair_limit=2)
    assert report["status"] == "PASS"
    assert report["category_filter"] == "MONSTER"
    assert all("MONSTER" in row["categories"] for row in report["rows"])
