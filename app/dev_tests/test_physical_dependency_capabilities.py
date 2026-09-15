from pathlib import Path

from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.ui_app import UIContext

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"


def test_physical_dependency_status_is_explicit_for_fixture_assets():
    settings = Settings.discover(ROOT, CLIENT)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=ClientResolver(CLIENT))
    asset = reg.resolve("char/monster/Acero/Acero.smd")
    status = reg.physical_dependency_status(asset)
    assert status["status"] == "PASS"
    assert status["rigid_binding_ready_physical"] is True
    assert status["animation_binding_ready_physical"] is True


def test_ui_exposes_physical_readiness_fields():
    ctx = UIContext(ROOT, CLIENT)
    detail = ctx.asset_detail("char/monster/Acero/Acero.smd")
    assert detail is not None
    assert detail["rigid_binding_ready_physical"] is True
    assert detail["animation_binding_ready_physical"] is True
