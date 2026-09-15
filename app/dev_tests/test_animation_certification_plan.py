from pathlib import Path

from pt_asset_tool.animation_certification import build_animation_certification_plan
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"


def _ctx():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    return registry, resolver


def test_animation_certification_plan_is_review_queue_not_auto_certification():
    registry, resolver = _ctx()
    report = build_animation_certification_plan(
        ROOT, registry, resolver, context_limit=4, motions_per_context=2
    )
    assert report["status"] in {"PASS", "PARTIAL"}
    assert report["planned_context_count"] <= 4
    assert report["review_count"] >= 1
    assert report["automatic_visual_certification"] is False
    assert report["automatic_runtime_certification"] is False
    assert report["client_modified"] is False
    for row in report["queue"]:
        assert row["client_write"] is False
        assert row["motion_state"]
        assert "validate animation" in row["command"]
        assert row["human_gates"] == ["VISUAL_RIG", "VISUAL_ANIMATION", "VISUAL_TEXTURE_MATERIAL"]


def test_animation_certification_plan_category_filter_is_semantic():
    registry, resolver = _ctx()
    report = build_animation_certification_plan(
        ROOT, registry, resolver, category="MONSTER", context_limit=4, motions_per_context=1
    )
    assert report["category_filter"] == "MONSTER"
    assert all(row["semantic_group"] == "MONSTER" for row in report["queue"])
