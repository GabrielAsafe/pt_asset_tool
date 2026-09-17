from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


APP_ROOT = Path(__file__).resolve().parents[1]


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("pt_asset_entrypoint_for_test", APP_ROOT / "pt_asset.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flatpak_launcher_requires_blender_app_to_be_installed(monkeypatch):
    module = _load_entrypoint()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/flatpak" if name == "flatpak" else None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="error: app/org.blender.Blender/x86_64/master not installed\n"),
    )
    available, reason = module._blender_launcher_status(
        ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]
    )
    assert available is False
    assert reason.startswith("FLATPAK_APP_UNAVAILABLE:org.blender.Blender:")
    assert "not installed" in reason


def test_flatpak_launcher_passes_when_blender_app_is_installed(monkeypatch):
    module = _load_entrypoint()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/flatpak" if name == "flatpak" else None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=""),
    )
    available, reason = module._blender_launcher_status(
        ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]
    )
    assert available is True
    assert reason == "FLATPAK_APP_INSTALLED:org.blender.Blender"
