from pathlib import Path

import pytest

from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.ui_actions import build_command

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CLIENT = ROOT.parent / "fixture_client"

requires_fixture = pytest.mark.skipif(not FIXTURE_CLIENT.is_dir(), reason="external fixture_client is not packaged")


def _registry():
    settings = Settings.discover(ROOT, FIXTURE_CLIENT)
    resolver = ClientResolver(settings.client_root)
    return AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)


@requires_fixture
def test_real_fixture_rigid_bindings_and_motion_contexts():
    reg = _registry()
    expected = {
        "char/monster/Monbagon/Monbagon-A.smd": {"WALK", "STAND", "ATTACK", "DAMAGE"},
        "char/npc/Ahin/Ahin.smd": {"WALK", "STAND"},
        "char/monster/Acero/Acero.smd": {"WALK", "STAND", "ATTACK", "DAMAGE"},
    }
    for logical in expected:
        asset = reg.resolve(logical)
        assert asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE"
        assert asset.rigid_binding_ready
        assert asset.animation_binding_ready
        assert asset.binding_skeleton_smb.lower().endswith(".smb")
        assert len(asset.motions) == 1


def test_stage072_gui_allows_backend_supported_stages():
    for stage in range(8):
        cmd = build_command(ROOT, "paint_stage072", "Field/Iron/iron-1.smd", {"stage": stage})
        assert cmd[-2:] == ["--stage", str(stage)]


def test_stage072_gui_rejects_out_of_range_stage():
    with pytest.raises(ValueError, match="INVALID_STAGE"):
        build_command(ROOT, "paint_stage072", "Field/Iron/iron-1.smd", {"stage": 8})
