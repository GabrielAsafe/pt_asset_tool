from __future__ import annotations

import io
import pathlib
import tarfile

from pt_asset_tool import app_config, dependencies, runtime_paths
import pt_asset

APP = pathlib.Path(__file__).resolve().parents[1]


def test_external_process_env_restores_original_loader_path(monkeypatch):
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123:/bundled")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/host/lib:/usr/local/lib")
    env = runtime_paths.external_process_env()
    assert env["LD_LIBRARY_PATH"] == "/host/lib:/usr/local/lib"


def test_external_process_env_removes_injected_loader_path_without_original(monkeypatch):
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    env = runtime_paths.external_process_env()
    assert "LD_LIBRARY_PATH" not in env


def test_frozen_client_discovery_never_uses_mei_parent_or_sibling_scan(tmp_path, monkeypatch):
    bundle = tmp_path / "tmp" / "_MEIabc"
    bundle.mkdir(parents=True)
    exe_dir = tmp_path / "portable"
    exe_dir.mkdir()
    monkeypatch.setattr(app_config, "is_frozen", lambda: True)
    monkeypatch.setattr(app_config, "executable_dir", lambda: exe_dir)
    monkeypatch.setattr(app_config, "load_config", lambda _root: {})
    rows = app_config.candidate_client_roots_with_source(bundle)
    sources = {source for _path, source in rows}
    assert sources == {
        "EXECUTABLE_DIR_CLIENTE", "EXECUTABLE_DIR_CLIENT",
        "EXECUTABLE_PARENT_CLIENTE", "EXECUTABLE_PARENT_CLIENT",
    }
    assert not any("SIBLING" in source or "PROJECT" in source for source in sources)


def test_frozen_server_discovery_never_uses_mei_parent_or_sibling_scan(tmp_path, monkeypatch):
    bundle = tmp_path / "tmp" / "_MEIabc"
    bundle.mkdir(parents=True)
    exe_dir = tmp_path / "portable"
    exe_dir.mkdir()
    monkeypatch.setattr(app_config, "is_frozen", lambda: True)
    monkeypatch.setattr(app_config, "executable_dir", lambda: exe_dir)
    monkeypatch.setattr(app_config, "load_config", lambda _root: {})
    rows = app_config.candidate_server_roots_with_source(bundle)
    sources = {source for _path, source in rows}
    assert sources == {
        "EXECUTABLE_DIR_SERVIDOR", "EXECUTABLE_DIR_SERVER",
        "EXECUTABLE_PARENT_SERVIDOR", "EXECUTABLE_PARENT_SERVER",
    }


def test_resolve_client_skips_inaccessible_candidate(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    good = tmp_path / "cliente"
    good.mkdir()
    monkeypatch.setattr(
        app_config,
        "candidate_client_roots_with_source",
        lambda _root: [(blocked, "BLOCKED"), (good, "GOOD")],
    )
    original = app_config._safe_is_dir
    monkeypatch.setattr(app_config, "_safe_is_dir", lambda p: False if p == blocked else original(p))
    path, source = app_config.resolve_client_root(tmp_path)
    assert path == good
    assert source == "GOOD"


def test_blender_probe_uses_sanitized_external_environment():
    text = (APP / "pt_asset_tool" / "dependencies.py").read_text(encoding="utf-8")
    assert "env=external_process_env()" in text
    assert "external_process_command(raw_command)" in text


def test_realesrgan_is_archived_and_materialized_to_cache():
    spec = (APP / "pt_asset_tool_portable.spec").read_text(encoding="utf-8")
    deps = (APP / "pt_asset_tool" / "dependencies.py").read_text(encoding="utf-8")
    assert "realesrgan_payload.tar.gz" in spec
    assert "_materialize_realesrgan_payload" in deps
    assert "cache_root()" in deps
    assert "_BUNDLED_REALESRGAN_GLIBC_FLOOR = (2, 29)" in deps


def test_portable_doctor_has_fresh_install_preflight():
    text = (APP / "pt_asset.py").read_text(encoding="utf-8")
    assert "doctor_check=SETUP_REQUIRED" in text
    assert "ASSET_REGISTRY_MISSING" in text
    assert "CLIENT_ROOT_NOT_CONFIGURED" in text


def test_realesrgan_payload_materializes_outside_mei(tmp_path, monkeypatch):
    project = tmp_path / "_MEIxyz"
    payloads = project / "payloads"
    payloads.mkdir(parents=True)
    archive = payloads / "realesrgan_payload.tar.gz"
    data = b"#!/bin/sh\nexit 0\n"
    info = tarfile.TarInfo("realesrgan/realesrgan-ncnn-vulkan")
    info.mode = 0o755
    info.size = len(data)
    with tarfile.open(archive, "w:gz") as tf:
        tf.addfile(info, io.BytesIO(data))
    cache = tmp_path / "cache"
    monkeypatch.setattr(dependencies, "is_frozen", lambda: True)
    monkeypatch.setattr(dependencies, "cache_root", lambda: cache)
    monkeypatch.setattr(dependencies, "_bundled_realesrgan_host_compatible", lambda: (True, "test"))
    found = dependencies.bundled_realesrgan(project)
    assert found is not None and found.is_file()
    assert str(found).startswith(str(cache))
    assert found.read_bytes() == data


def test_blender_command_is_child_safe_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    monkeypatch.setattr(dependencies, "_which", lambda name: "/usr/bin/blender" if name == "blender" else None)
    monkeypatch.delenv("PT_BLENDER_EXE", raising=False)
    monkeypatch.delenv("PT_BLENDER_COMMAND", raising=False)
    monkeypatch.delenv("PT_ASSET_BLENDER_COMMAND", raising=False)
    monkeypatch.setattr(dependencies, "_configured_blender_executable", lambda _root: None)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIabc")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    info = dependencies.blender_runtime_info(tmp_path, probe_version=False)
    assert info["raw_command"] == ["/usr/bin/blender"]
    assert info["command"][-1] == "/usr/bin/blender"
    assert "-u" in info["command"] and "LD_LIBRARY_PATH" in info["command"]


def test_portable_doctor_reports_fresh_install_instead_of_crashing(tmp_path, monkeypatch, capsys):
    missing_state = tmp_path / "state"
    monkeypatch.setattr(pt_asset, "is_frozen", lambda: True)
    monkeypatch.setattr(pt_asset, "persistent_pt_build", lambda: missing_state)
    monkeypatch.setattr(app_config, "resolve_client_root", lambda _root: (_ for _ in ()).throw(FileNotFoundError("missing")))
    assert pt_asset._portable_doctor_setup_preflight() == 0
    out = capsys.readouterr().out
    assert "doctor_check=SETUP_REQUIRED" in out
    assert "reason=CLIENT_ROOT_NOT_CONFIGURED" in out
