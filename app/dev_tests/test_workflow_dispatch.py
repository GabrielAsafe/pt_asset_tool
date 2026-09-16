from __future__ import annotations

import pathlib

import pytest
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.workflow_dispatch import build_plan

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

pytestmark = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")


def _registry():
    s = Settings.discover(ROOT, CLIENT)
    r = ClientResolver(s.client_root)
    return AssetRegistry(s.inventory, s.pairing, resolver=r)


def test_generic_build_is_fail_closed_for_normal_fixture_asset():
    reg = _registry()
    asset = reg.resolve("char/monster/Acero/Acero.smd")
    plan = build_plan(asset)
    assert plan["authorized"] is False
    assert plan["client_write"] is False
    assert plan["output_policy"] == "PT_BUILD_ONLY"
