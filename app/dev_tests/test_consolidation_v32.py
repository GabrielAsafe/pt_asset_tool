from __future__ import annotations

import importlib.util
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from pt_asset_tool import particle_service
from pt_asset_tool.ui_app import UIContext, UIHandler

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _part_bytes(*, balanced: bool = True) -> bytes:
    close = "}\r\n" if balanced else ""
    return (
        "ParticleSystem Test {\r\n"
        "Position xyz(0,0,0)\r\n"
        "EventSequence Spawn {\r\n"
        "NumParticles 3\r\n"
        "EmitRate 1\r\n"
        "Lifetime 30\r\n"
        "Texture \"Effect/Particle/Texture/test.tga\"\r\n"
        "}\r\n"
        + close
    ).encode("ascii")


def test_smoke_human_size_and_texture_upscale_is_valid_capability():
    entry = _load_module(APP_ROOT / "pt_asset.py", "pt_asset_entry_v32")
    assert entry._human_size_bytes(34_654_717_867) == "32.27 GiB"
    asset = SimpleNamespace(extension=".bmp", primary_path="char/Flag/wow.bmp")
    assert entry._texture_capability_violation(asset, ["inspect", "upscale_texture"]) is None
    violation = entry._texture_capability_violation(asset, ["inspect", "motions"])
    assert violation and violation["unexpected_actions"] == ["motions"]


def test_particle_plan_does_not_require_blender_and_reports_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = tmp_path / "client"
    part = client / "Effect/Particle/Script/Test.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(_part_bytes())
    build = tmp_path / "build"
    monkeypatch.setattr(
        particle_service,
        "resolve_blender_command",
        lambda _root=None: (["missing-blender"], False, "launcher not installed"),
    )
    result = particle_service.build_effect_preview(client, build, APP_ROOT, "Effect/Particle/Script/Test.part")
    assert result["status"] == "PASS"
    assert result["event_count"] == 1
    assert result["blender_ready"] is False
    assert result["plan_path"]
    assert Path(result["plan_path"]).is_file()


def test_particle_preview_plan_recovers_unbalanced_legacy_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = tmp_path / "client"
    part = client / "Effect/Particle/Script/Legacy.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(_part_bytes(balanced=False))
    build = tmp_path / "build"
    monkeypatch.setattr(
        particle_service,
        "resolve_blender_command",
        lambda _root=None: (["missing-blender"], False, "launcher not installed"),
    )
    result = particle_service.build_effect_preview(client, build, APP_ROOT, "Effect/Particle/Script/Legacy.part")
    assert result["status"] == "PASS"
    assert result["plan_parse_status"] == "REVIEW_UNBALANCED_BRACES"
    assert result["semantic_warning_count"] >= 1


def test_integrated_particle_preview_plan_http_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "project"
    project.mkdir()
    # UIContext asks the backend for a version. A minimal entrypoint is enough;
    # particle parsing itself uses the installed first-party modules.
    (project / "pt_asset.py").write_text(
        '#!/usr/bin/env python3\nimport sys\nprint("1.0-test")\n', encoding="utf-8"
    )
    client = tmp_path / "client"
    part = client / "Effect/Particle/Script/Test.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(_part_bytes())
    monkeypatch.setattr(
        particle_service,
        "resolve_blender_command",
        lambda _root=None: (["missing-blender"], False, "launcher not installed"),
    )
    ctx = UIContext(project, client)
    server = ThreadingHTTPServer(("127.0.0.1", 0), UIHandler)
    server.ctx = ctx
    ctx.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/particles/preview-plan"
        body = json.dumps({"asset": "Effect/Particle/Script/Test.part"}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-PT-UI-Token": ctx.token},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode())
        assert payload["ok"] is True
        assert payload["result"]["status"] == "PASS"
        assert payload["result"]["blender_ready"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_ready_to_deploy_never_deletes_runtime_user_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ready = _load_module(REPO_ROOT / "READY_TO_DEPLOY.py", "ready_to_deploy_v32")
    monkeypatch.setattr(ready, "ROOT", tmp_path)
    monkeypatch.setattr(ready, "APP", tmp_path / "app")
    runtime_file = tmp_path / "app/pt_build/texture_upscale/runs/run-1/image.tga"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_bytes(b"user-upscale")
    legacy_file = tmp_path / "enhancement/runs/run-old/image.tga"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(b"legacy-upscale")
    runtime_cache = tmp_path / "app/pt_build/runtime/__pycache__/sentinel.pyc"
    runtime_cache.parent.mkdir(parents=True)
    runtime_cache.write_bytes(b"runtime-cache-is-user-state")
    cache = tmp_path / "app/__pycache__"
    cache.mkdir(parents=True)
    (cache / "x.pyc").write_bytes(b"cache")

    rows = ready.generated_paths()
    paths = {p for p, _ in rows}
    assert runtime_file.parent not in paths
    assert not any((tmp_path / "app/pt_build") == p or (tmp_path / "enhancement") == p for p in paths)
    ready.clean_generated(dry_run=False)
    assert runtime_file.read_bytes() == b"user-upscale"
    assert legacy_file.read_bytes() == b"legacy-upscale"
    assert runtime_cache.read_bytes() == b"runtime-cache-is-user-state"
    assert not cache.exists()
