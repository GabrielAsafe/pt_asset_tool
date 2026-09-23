from __future__ import annotations

import os
from pathlib import Path

import pytest

from pt_asset_tool.app_config import (
    clear_blender_executable,
    configured_blender_executable,
    save_blender_executable,
)
from pt_asset_tool import dependencies


def _fake_blender(path: Path, version: str = "3.6.23") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ] || [ \"$2\" = \"--version\" ]; then\n"
        f"  echo 'Blender {version}'\n"
        "  exit 0\n"
        "fi\n"
        f"echo 'Blender {version}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path.resolve()


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PT_BLENDER_EXE", "PT_BLENDER_COMMAND", "PT_ASSET_BLENDER_COMMAND"):
        monkeypatch.delenv(name, raising=False)
    dependencies._BLENDER_VERSION_CACHE.clear()


def test_pt_blender_exe_has_highest_precedence_and_reports_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _clean_env(monkeypatch)
    project = tmp_path / "app"
    project.mkdir()
    exe = _fake_blender(tmp_path / "portable blender" / "blender", "3.6.23")
    other = _fake_blender(tmp_path / "other" / "blender", "5.0.1")
    save_blender_executable(project, other)
    monkeypatch.setenv("PT_BLENDER_COMMAND", str(other))
    monkeypatch.setenv("PT_BLENDER_EXE", str(exe))

    info = dependencies.blender_runtime_info(project, probe_version=True)
    assert info["ready"] is True
    assert info["source"] == "PT_BLENDER_EXE"
    assert info["command"] == [str(exe)]
    assert info["version"] == "3.6.23"


def test_invalid_explicit_exe_is_fail_closed_even_when_path_has_blender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _clean_env(monkeypatch)
    project = tmp_path / "app"
    project.mkdir()
    bindir = tmp_path / "bin"
    _fake_blender(bindir / "blender", "5.1.0")
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("PT_BLENDER_EXE", str(tmp_path / "missing" / "blender"))

    info = dependencies.blender_runtime_info(project, probe_version=True)
    assert info["ready"] is False
    assert info["source"] == "PT_BLENDER_EXE"
    assert "was not found" in info["detail"]


def test_persistent_config_is_used_before_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _clean_env(monkeypatch)
    project = tmp_path / "app"
    project.mkdir()
    configured = _fake_blender(tmp_path / "configured" / "blender", "3.6.23")
    path_blender = _fake_blender(tmp_path / "bin" / "blender", "5.2.0")
    save_blender_executable(project, configured)
    monkeypatch.setenv("PATH", str(path_blender.parent) + os.pathsep + os.environ.get("PATH", ""))

    info = dependencies.blender_runtime_info(project, probe_version=True)
    assert info["ready"] is True
    assert info["source"] == "PERSISTENT_CONFIG"
    assert info["command"] == [str(configured)]
    assert info["version"] == "3.6.23"
    assert configured_blender_executable(project) == str(configured)


def test_legacy_command_with_arguments_remains_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _clean_env(monkeypatch)
    project = tmp_path / "app"
    project.mkdir()
    exe = _fake_blender(tmp_path / "wrapper" / "blender", "4.3.2")
    monkeypatch.setenv("PT_BLENDER_COMMAND", f"'{exe}' --factory-startup")

    info = dependencies.blender_runtime_info(project, probe_version=True)
    assert info["ready"] is True
    assert info["source"] == "PT_BLENDER_COMMAND"
    assert info["command"][:2] == [str(exe), "--factory-startup"]
    assert info["version"] == "4.3.2"


def test_save_and_clear_blender_executable_are_machine_local(tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir()
    exe = _fake_blender(tmp_path / "Blender 3.6" / "blender")
    config = save_blender_executable(project, exe)
    assert config == project / "pt_build" / "state" / "pt_asset_app_config.json"
    assert configured_blender_executable(project) == str(exe)
    clear_blender_executable(project)
    assert configured_blender_executable(project) is None


def test_save_blender_executable_rejects_missing_or_non_executable(tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir()
    with pytest.raises(FileNotFoundError):
        save_blender_executable(project, tmp_path / "missing")
    bad = tmp_path / "not-executable"
    bad.write_text("x", encoding="utf-8")
    bad.chmod(0o644)
    with pytest.raises(PermissionError):
        save_blender_executable(project, bad)


def test_dependencies_report_includes_runtime_source_version_and_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _clean_env(monkeypatch)
    project = tmp_path / "app"
    project.mkdir()
    exe = _fake_blender(tmp_path / "portable" / "blender", "3.6.23")
    monkeypatch.setenv("PT_BLENDER_EXE", str(exe))

    report = dependencies.dependency_report(project)
    row = next(x for x in report["dependencies"] if x["id"] == "blender")
    assert row["status"] == "READY"
    assert "source=PT_BLENDER_EXE" in row["detail"]
    assert "version=3.6.23" in row["detail"]
    assert str(exe) in row["detail"]
