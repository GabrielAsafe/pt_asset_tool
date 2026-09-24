from __future__ import annotations

import pathlib
import re
import sys

from pt_asset_tool import runtime_paths
from pt_asset_tool.ui_actions import build_command

APP = pathlib.Path(__file__).resolve().parents[1]
REPO = APP.parent


def test_source_mode_commands_use_current_python_not_cwd():
    cmd = runtime_paths.app_command(APP, "doctor")
    assert cmd[0] == "python3"
    assert pathlib.Path(cmd[1]).resolve() == (APP / "pt_asset.py").resolve()
    assert cmd[-1] == "doctor"
    action = build_command(APP, "doctor", None)
    assert action == cmd


def test_frozen_runtime_projects_pt_build_to_persistent_state(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    home = tmp_path / "portable-home"
    monkeypatch.setenv("PT_ASSET_HOME", str(home))
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    info = runtime_paths.prepare_runtime_layout(bundle)
    link = bundle / "pt_build"
    assert link.is_symlink()
    assert link.resolve() == (home / "state" / "pt_build").resolve()
    assert pathlib.Path(info["config_root"]) == (home / "config").resolve()
    assert pathlib.Path(info["cache_root"]) == (home / "cache").resolve()


def test_frozen_app_command_reinvokes_executable(monkeypatch):
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    cmd = runtime_paths.app_command(APP, "dependencies", "--json")
    assert pathlib.Path(cmd[0]).resolve() == pathlib.Path(sys.executable).resolve()
    assert cmd[1:] == ["dependencies", "--json"]


def test_internal_python_runner_command_has_no_system_python_dependency(tmp_path, monkeypatch):
    script = tmp_path / "worker.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    cmd = runtime_paths.python_script_command(script, "--x", "1")
    assert cmd[1:3] == ["__internal-path", str(script.resolve())]
    assert cmd[-2:] == ["--x", "1"]


def test_runtime_sources_do_not_spawn_literal_python3_scripts():
    offenders = []
    pattern = re.compile(r'[\"\']python3[\"\']\s*,\s*str\([^\n]*\.py')
    for path in (APP / "pt_asset_tool").rglob("*.py"):
        if "__pycache__" in path.parts or path.name == "runtime_paths.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(str(path.relative_to(APP)))
    assert offenders == []


def test_portable_spec_bundles_python_runtime_deps_but_excludes_blender_modules():
    spec = (APP / "pt_asset_tool_portable.spec").read_text(encoding="utf-8")
    assert 'name="pt-asset-tool"' in spec
    assert '"pyodbc"' in spec
    assert '"bpy"' in spec
    assert '"mathutils"' in spec
    assert "collect_submodules(\"pt_asset_tool\")" in spec
    assert "binaries=binaries" in spec
    assert "realesrgan_payload.tar.gz" in spec
    req = (APP / "requirements-portable-build.txt").read_text(encoding="utf-8")
    assert "PyInstaller" in req and "Pillow" in req and "numpy" in req


def test_entrypoint_defaults_to_gui_and_supports_internal_runner():
    text = (APP / "pt_asset_app.py").read_text(encoding="utf-8")
    assert 'args[0] == "__internal-path"' in text
    assert 'not args or args[0] == "gui"' in text


def test_internal_runner_exposes_script_directory_for_sibling_imports(tmp_path):
    helper = tmp_path / "helper_local.py"
    helper.write_text("VALUE = 73\n", encoding="utf-8")
    script = tmp_path / "worker.py"
    script.write_text("import helper_local\nraise SystemExit(0 if helper_local.VALUE == 73 else 9)\n", encoding="utf-8")
    assert runtime_paths.run_internal_path(script, []) == 0


def test_release_container_uses_old_glibc_baseline_and_single_file_output():
    containerfile = (REPO / "Containerfile.portable").read_text(encoding="utf-8")
    runner = (REPO / "build_portable_container.sh").read_text(encoding="utf-8")
    assert "manylinux2014_x86_64" in containerfile
    assert "dist/pt-asset-tool --version" in containerfile
    assert "podman" in runner and "docker" in runner
    assert "dist-portable/pt-asset-tool" in runner
