from __future__ import annotations

import importlib.util
import pathlib
import sys
import types


def _load_entrypoint():
    here = pathlib.Path(__file__).resolve()
    app_root = here.parents[1]
    path = app_root / "pt_asset_app.py"
    spec = importlib.util.spec_from_file_location("pt_asset_app_v103_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_overlay_receives_projected_sys_argv(monkeypatch):
    mod = _load_entrypoint()
    seen = {}

    fake = types.ModuleType("pt_asset")

    def fake_main():
        seen["argv"] = list(sys.argv)
        return 17

    fake.main = fake_main
    monkeypatch.setitem(sys.modules, "pt_asset", fake)
    original = list(sys.argv)

    assert mod.main(["status", "--json"]) == 17
    assert seen["argv"][1:] == ["status", "--json"]
    assert sys.argv == original


def test_cli_prefix_is_removed_before_overlay(monkeypatch):
    mod = _load_entrypoint()
    seen = {}
    fake = types.ModuleType("pt_asset")

    def fake_main():
        seen["argv"] = list(sys.argv)
        return 0

    fake.main = fake_main
    monkeypatch.setitem(sys.modules, "pt_asset", fake)

    assert mod.main(["cli", "--version"]) == 0
    assert seen["argv"][1:] == ["--version"]


def test_spec_keeps_realesrgan_out_of_pyinstaller_binary_analysis():
    app_root = pathlib.Path(__file__).resolve().parents[1]
    text = (app_root / "pt_asset_tool_portable.spec").read_text(encoding="utf-8")
    assert 'binaries.append((str(src), str(rel_parent)))' not in text
    assert 'realesrgan_payload.tar.gz' in text
    assert 'tarfile.open(payload_archive, "w:gz")' in text
    assert 'compressed opaque payload' in text


def test_container_reports_realesrgan_host_abi_requirement():
    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / "Containerfile.portable").read_text(encoding="utf-8")
    assert "portable_realesrgan_payload=READY" in text
    assert "readelf --version-info" in text
    assert "RUN ./dist/pt-asset-tool --version" in text
