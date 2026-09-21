from pathlib import Path
from types import SimpleNamespace

import pytest
pytest.importorskip("PIL.Image")

from pt_asset_tool.texture_upscale import capability_status
from pt_asset_tool.ui_actions import ACTION_SPECS, build_command
from pt_asset_tool.ui_capabilities import capabilities_for_asset


def test_texture_ui_capability_and_action_are_registered(tmp_path: Path):
    asset = SimpleNamespace(
        family="",
        kind="PNG_STANDARD",
        primary_path="Image/Character/hero.png",
    )
    caps, _ = capabilities_for_asset(asset, None)
    assert "upscale_texture" in caps
    assert ACTION_SPECS["upscale_texture"].mutates_build is True


def test_texture_ui_action_builds_scoped_safe_command(tmp_path: Path):
    (tmp_path / "pt_asset.py").write_text("# stub\n", encoding="utf-8")
    cmd = build_command(tmp_path, "upscale_texture", "Image/Character/hero.tga", {
        "scale": "3",
        "backend": "lanczos",
    })
    assert cmd[2:] == [
        "texture-upscale", "run", "--include-exact", "Image/Character/hero.tga",
        "--scale", "3", "--backend", "lanczos",
    ]


def test_texture_ui_action_can_explicitly_include_ui_risk(tmp_path: Path):
    (tmp_path / "pt_asset.py").write_text("# stub\n", encoding="utf-8")
    cmd = build_command(tmp_path, "upscale_texture", "game/Login/button.png", {
        "scale": 2,
        "backend": "lanczos",
        "include_ui": True,
    })
    assert cmd[-1] == "--include-ui"


def test_texture_capability_status_is_optional_and_structured():
    status = capability_status()
    assert "lanczos_ready" in status
    assert "realesrgan_ready" in status
    assert ".tga" in status["supported_suffixes"]


def test_texture_action_is_hidden_when_pillow_is_unavailable(monkeypatch):
    import pt_asset_tool.ui_capabilities as caps_mod
    monkeypatch.setattr(caps_mod, "PILLOW_AVAILABLE", False)
    asset = SimpleNamespace(family="", kind="PNG_STANDARD", primary_path="Image/Character/hero.png")
    caps, _ = caps_mod.capabilities_for_asset(asset, None)
    assert "upscale_texture" not in caps


def test_texture_ui_action_passes_explicit_quality_profile(tmp_path: Path):
    (tmp_path / "pt_asset.py").write_text("# stub\n", encoding="utf-8")
    cmd = build_command(tmp_path, "upscale_texture", "Image/Character/hero.tga", {
        "scale": 4,
        "backend": "auto",
        "profile": "detail",
    })
    assert cmd[-4:] == ["--backend", "auto", "--profile", "detail"]
