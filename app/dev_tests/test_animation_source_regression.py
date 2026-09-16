from __future__ import annotations

import pathlib

import pytest

from pt_asset_tool.animation_source_regression import audit_animation_source_regression

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

pytestmark = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")

CASES = [
    (CLIENT / "char/npc/Ahin/Ahin.inx", CLIENT / "char/npc/Ahin/Ahin.smb"),
    (CLIENT / "char/monster/Monbagon/Monbagon-A.inx", CLIENT / "char/monster/Monbagon/mbagon.smb"),
    (CLIENT / "char/monster/Acero/Acero.inx", CLIENT / "char/monster/Acero/Acero.smb"),
]


@pytest.mark.parametrize("inx,smb", CASES)
def test_source_animation_regression_core_is_finite(inx, smb):
    result = audit_animation_source_regression(ROOT, inx, smb, mode="core")
    assert result["status"] == "PASS"
    assert result["scope"] == "SOURCE_SIDE_SANITY_NOT_VISUAL_CERTIFICATION"
    assert result["visual_certification"] is False
    assert result["blender_pose_space_certification"] is False
    assert result["inx_smb_validation"]["check"] == "PASS"
    assert result["audited_motion_count"] >= 1
    assert all(m["finite"] for m in result["motions"])
    assert all(m["frames"] > 0 for m in result["motions"])
