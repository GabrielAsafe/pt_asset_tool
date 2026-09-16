from __future__ import annotations

from pathlib import Path

import pytest

from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver

ROOT = Path(__file__).resolve().parents[1]


def runtime_settings() -> Settings:
    """Return settings backed by a real client, or skip corpus-only tests.

    Fresh source checkouts intentionally do not ship a generated asset registry.
    Corpus/integration tests therefore consume the configured client and the
    registry generated under ``pt_build/state``.  Unit tests remain synthetic
    and do not use this helper.
    """
    try:
        settings = Settings.discover(ROOT)
    except Exception as exc:  # no configured/discoverable client in static CI
        pytest.skip(f"real client required for corpus test: {exc}")
    if not settings.client_root.is_dir():
        pytest.skip(f"real client required for corpus test: {settings.client_root}")
    return settings


def runtime_registry() -> AssetRegistry:
    settings = runtime_settings()
    return AssetRegistry(
        settings.inventory,
        settings.pairing,
        resolver=ClientResolver(settings.client_root),
    )
