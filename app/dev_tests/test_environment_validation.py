from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.environment_validation import run_environment_validation


def _fake_registry(client: Path):
    specs = [
        ("model.smd", "SMD_MODEL_062", ".smd", b"SMD Model data Ver 0.62\0"),
        ("stage.smd", "SMD_STAGE_072", ".smd", b"SMD Stage data Ver 0.72\0"),
        ("a.inx", "INX_MODELINFO_GROUPS", ".inx", b"inx"),
        ("a.smb", "SMB_BIPED_LIKELY", ".smb", b"SMB"),
        ("a.bmp", "BMP_PRISTON_PREFIX14", ".bmp", b"bmp"),
        ("a.tga", "TGA_UNKNOWN", ".tga", b"tga"),
    ]
    rows = []
    for name, kind, ext, data in specs:
        p = client / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        rows.append({"relative_path": name, "kind": kind, "extension": ext, "size": len(data)})
    return SimpleNamespace(records=rows, assets=rows)


def _settings(tmp_path: Path):
    project = tmp_path / "app"
    client = tmp_path / "cliente com espaço á"
    project.mkdir(); client.mkdir()
    inventory = project / "inventory.json"; inventory.write_text("{}")
    pairing = project / "pairing.csv"; pairing.write_text("a,b\n")
    return SimpleNamespace(
        project_root=project,
        client_root=client,
        inventory=inventory,
        pairing=pairing,
        blender_command=lambda: ["blender"],
    )


def test_environment_auto_validates_real_blender_filesystem_bridge_without_client_write(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    registry = _fake_registry(settings.client_root)
    monkeypatch.setattr("pt_asset_tool.environment_validation.CERTIFIED_WRITERS", {})

    def fake_run(command, capture_output, text, timeout, check):
        expr = command[-1]
        # Pull the two pathlib.Path literals from the generated expression.
        import re, ast
        vals = re.findall(r"pathlib\.Path\(([^)]+)\)", expr)
        probe = Path(ast.literal_eval(vals[0])); client = Path(ast.literal_eval(vals[1]))
        payload = {
            "blender_version": "5.2.0",
            "probe_exists": probe.is_file(), "client_exists": client.is_file(),
            "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
            "client_sha256": hashlib.sha256(client.read_bytes()).hexdigest(),
        }
        return SimpleNamespace(returncode=0, stdout="PT_ENV_PROBE=" + json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr("pt_asset_tool.environment_validation.subprocess.run", fake_run)
    result = run_environment_validation(settings, registry, blender_timeout_seconds=5)
    assert result["status"] == "PASS"
    assert result["environment_ready"] is True
    assert result["client_modified"] is False
    assert result["policy"]["client_source_write_attempted"] is False
    assert Path(result["report"]).is_file()
    by_name = {x["name"]: x for x in result["checks"]}
    assert by_name["blender_headless_filesystem_bridge"]["status"] == "PASS"
    assert by_name["blender_headless_filesystem_bridge"]["required"] is False
    assert result["blender_ready"] is True
    assert result["policy"]["release_1_auto_may_run"] is True
    assert by_name["client_samples_unchanged"]["status"] == "PASS"


def test_environment_auto_fails_closed_on_inventory_physical_size_drift(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    registry = _fake_registry(settings.client_root)
    registry.records[0]["size"] += 1
    monkeypatch.setattr("pt_asset_tool.environment_validation.CERTIFIED_WRITERS", {})
    monkeypatch.setattr(
        "pt_asset_tool.environment_validation._blender_probe",
        lambda *a, **k: {"status": "FAIL", "error": "not relevant"},
    )
    result = run_environment_validation(settings, registry, blender_timeout_seconds=1)
    assert result["status"] == "FAIL"
    assert "physical_inventory_samples" in result["required_failures"]
    assert result["client_modified"] is False


def test_release_1_cli_does_not_start_heavy_gate_when_environment_fails(monkeypatch, tmp_path):
    from pt_asset_tool import cli
    args = SimpleNamespace(
        root=None, client_root=None, environment_blender_timeout=3.0,
        rigid_per_domain=3, static_per_domain=3, object_local_limit=4, texlink_limit=4,
        fps=30, motion_pair_limit=0, resume=True, motion_semantic_timeout=120.0,
    )
    settings = SimpleNamespace(project_root=tmp_path, client_root=tmp_path / "client")
    monkeypatch.setattr(cli, "make_context", lambda a: (settings, object(), object(), object()))
    monkeypatch.setattr(cli, "run_environment_validation", lambda *a, **k: {"status": "FAIL", "client_modified": False, "report": "env.json"})
    called = {"heavy": False}
    monkeypatch.setattr(cli, "run_release_1_automated_gate", lambda *a, **k: called.__setitem__("heavy", True) or {})
    assert cli.cmd_validate_release_1_auto(args) == 3
    assert called["heavy"] is False


def test_environment_auto_reports_missing_blender_as_optional_capability(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    registry = _fake_registry(settings.client_root)
    monkeypatch.setattr("pt_asset_tool.environment_validation.CERTIFIED_WRITERS", {})
    def boom(*a, **k):
        raise FileNotFoundError('blender missing')
    monkeypatch.setattr("pt_asset_tool.environment_validation.subprocess.run", boom)
    result = run_environment_validation(settings, registry, blender_timeout_seconds=1)
    assert result['status'] == 'PASS'
    assert result['environment_ready'] is True
    assert result['blender_ready'] is False
    assert 'blender_headless_filesystem_bridge' not in result['required_failures']
    by_name = {x['name']: x for x in result['checks']}
    assert by_name['blender_headless_filesystem_bridge']['status'] == 'SKIP'
    assert by_name['blender_headless_filesystem_bridge']['required'] is False
    assert result['policy']['release_1_auto_may_run'] is False
    assert result['blender']['error'].startswith('BLENDER_LAUNCH:FileNotFoundError')
    assert result['client_modified'] is False


def test_release_1_cli_does_not_start_heavy_gate_when_blender_is_unavailable(monkeypatch, tmp_path):
    from pt_asset_tool import cli
    args = SimpleNamespace(
        root=None, client_root=None, server_root=None, environment_blender_timeout=3.0,
        rigid_per_domain=3, static_per_domain=3, object_local_limit=4, texlink_limit=4,
        fps=30, motion_pair_limit=0, resume=True, motion_semantic_timeout=120.0,
    )
    settings = SimpleNamespace(project_root=tmp_path, client_root=tmp_path / "client", server_root=None)
    monkeypatch.setattr(cli, "make_context", lambda a: (settings, object(), object(), object()))
    monkeypatch.setattr(cli, "run_environment_validation", lambda *a, **k: {
        "status": "PASS",
        "environment_ready": True,
        "blender_ready": False,
        "policy": {"release_1_auto_may_run": False},
        "client_modified": False,
        "report": "env.json",
    })
    called = {"heavy": False}
    monkeypatch.setattr(cli, "run_release_1_automated_gate", lambda *a, **k: called.__setitem__("heavy", True) or {})
    assert cli.cmd_validate_release_1_auto(args) == 3
    assert called["heavy"] is False


def test_environment_auto_treats_flatpak_blender_not_installed_as_skip(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings.blender_command = lambda: ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]
    registry = _fake_registry(settings.client_root)
    monkeypatch.setattr("pt_asset_tool.environment_validation.CERTIFIED_WRITERS", {})

    def fake_run(command, capture_output, text, timeout, check):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="error: app/org.blender.Blender/x86_64/master not installed\n",
        )

    monkeypatch.setattr("pt_asset_tool.environment_validation.subprocess.run", fake_run)
    result = run_environment_validation(settings, registry, blender_timeout_seconds=1)
    by_name = {x["name"]: x for x in result["checks"]}
    assert result["status"] == "PASS"
    assert result["blender_ready"] is False
    assert by_name["blender_headless_filesystem_bridge"]["status"] == "SKIP"
    assert by_name["blender_headless_filesystem_bridge"]["required"] is False
    assert result["policy"]["release_1_auto_may_run"] is False
