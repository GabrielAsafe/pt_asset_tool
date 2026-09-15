from __future__ import annotations

import pathlib

import pt_asset_tool.integration_regression_auto as mod


class Settings:
    def __init__(self, root: pathlib.Path):
        self.project_root = root
        self.client_root = root / "client"
        self.server_root = root / "server"
        self.client_root.mkdir()
        self.server_root.mkdir()


class Registry:
    pass


class Resolver:
    pass


def _patch_common(monkeypatch, *, affine_status="PASS"):
    monkeypatch.setattr(mod, "run_environment_validation", lambda *a, **k: {"status": "PASS", "client_modified": False})
    monkeypatch.setattr(mod, "run_server_environment_validation", lambda *a, **k: {"status": "PASS", "server_modified": False})
    monkeypatch.setattr(mod, "run_affine_animation_selftest", lambda *a, **k: {"status": affine_status, "client_modified": False, "server_modified": False})
    monkeypatch.setattr(mod, "choose_animation_pose_physical_representatives", lambda registry, resolver, domain, limit=1: [{"asset": f"{domain}.smd", "domain": domain}])
    monkeypatch.setattr(mod, "run_animation_pose_automated_devtest_batch", lambda *a, **k: {"status": "PASS", "client_modified": False})
    monkeypatch.setattr(mod, "choose_standalone_animation_representatives", lambda *a, **k: {"PLAYER": [{"asset": "standalone.smd", "domain": "PLAYER"}]})
    monkeypatch.setattr(mod, "run_standalone_animation_pose_devtest_batch", lambda *a, **k: {"status": "PASS", "client_modified": False})
    monkeypatch.setattr(mod, "audit_smb_animation_corpus", lambda *a, **k: {"status": "PASS", "smb_file_count": 957, "client_modified": False})
    monkeypatch.setattr(mod, "audit_smb_writer_corpus", lambda *a, **k: {"status": "PASS", "client_modified": False})
    monkeypatch.setattr(mod, "audit_smb_writer_edit_corpus", lambda *a, **k: {"status": "PASS", "client_modified": False})
    monkeypatch.setattr(mod, "audit_proprietary_texture_exact_regressions", lambda *a, **k: {"status": "PASS", "client_modified": False})
    monkeypatch.setattr(mod, "audit_proprietary_texture_codecs", lambda *a, **k: {"status": "PASS", "client_modified": False})
    monkeypatch.setattr(mod, "audit_server_entity_bundles", lambda *a, **k: {"status": "PASS", "definition_count": 100})
    monkeypatch.setattr(mod, "audit_server_field_bundles", lambda *a, **k: {"status": "PASS", "field_bundle_count": 68, "rows": [{"selected_stage": "Field/test.smd"}]})
    monkeypatch.setattr(mod, "audit_server_item_bundles", lambda *a, **k: {"status": "PASS", "item_definition_count": 1924, "identity_parsed_count": 1800})


def test_integration_regression_pass_requires_real_parser_signals(monkeypatch, tmp_path):
    _patch_common(monkeypatch)
    result = mod.run_integration_regression_auto(Settings(tmp_path), Registry(), Resolver(), object())
    assert result["status"] == "PASS"
    assert result["required_failures"] == []
    assert result["gates"]["server_parser_regression"]["status"] == "PASS"
    assert result["next_gate"] == "PHYSICAL_REGRESSION_AUTO"
    assert result["client_write_authorized"] is False
    assert result["server_write_authorized"] is False


def test_integration_regression_fails_closed_when_affine_blender_proof_fails(monkeypatch, tmp_path):
    _patch_common(monkeypatch, affine_status="FAIL")
    progress = []
    result = mod.run_integration_regression_auto(
        Settings(tmp_path), Registry(), Resolver(), object(), progress=progress.append
    )
    assert result["status"] == "FAIL"
    assert "affine_animation_selftest" in result["required_failures"]
    assert result["failure_summary"]["affine_animation_selftest"]["status"] == "FAIL"
    assert pathlib.Path(result["failure_summary_report"]).is_file()
    assert any(line.startswith("FAILURE affine_animation_selftest ") for line in progress)
    assert result["next_gate"] == "FIX_REPORTED_INTEGRATION_REGRESSIONS"


def test_integration_regression_stops_on_environment_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "run_environment_validation", lambda *a, **k: {"status": "FAIL", "client_modified": False, "error": "synthetic"})
    monkeypatch.setattr(mod, "run_server_environment_validation", lambda *a, **k: {"status": "PASS", "server_modified": False})
    progress = []
    result = mod.run_integration_regression_auto(
        Settings(tmp_path), Registry(), Resolver(), object(), progress=progress.append
    )
    assert result["status"] == "FAIL"
    assert result["required_failures"] == ["client_environment"]
    assert result["failure_summary"]["client_environment"]["error"] == "synthetic"
    assert pathlib.Path(result["failure_summary_report"]).is_file()
    assert any(line.startswith("FAILURE client_environment ") for line in progress)
    assert result["next_gate"] == "FIX_ENVIRONMENT"


def test_cli_integration_regression_prints_compact_terminal_summary(monkeypatch, capsys):
    import json
    from types import SimpleNamespace
    import pt_asset_tool.cli as cli

    monkeypatch.setattr(cli, "make_context", lambda a: (object(), object(), object(), object()))
    result = {
        "format": mod.FORMAT,
        "status": "FAIL",
        "integration_regression_ready": False,
        "required_failures": ["affine_animation_selftest"],
        "failure_summary": {"affine_animation_selftest": {"gate": "affine_animation_selftest", "status": "FAIL"}},
        "failure_summary_report": "/tmp/failure_summary.json",
        "gates": {
            "affine_animation_selftest": {"status": "FAIL", "rows": [{"payload": "x" * 20000}]},
            "server_item_bundles": {"status": "PASS", "rows": [{"definition": "one"}] * 2000},
        },
        "selection": {"known_smb_outliers": ["Phoenix.smb"]},
        "next_gate": "FIX_REPORTED_INTEGRATION_REGRESSIONS",
        "client_modified": False,
        "server_modified": False,
        "report": "/tmp/result.json",
    }
    monkeypatch.setattr(cli, "run_integration_regression_auto", lambda *a, **k: result)
    args = SimpleNamespace(fps=30, environment_blender_timeout=60.0, affine_blender_timeout=90.0)
    rc = cli.cmd_validate_integration_regression_auto(args)
    raw = capsys.readouterr().out
    shown = json.loads(raw)
    assert rc == 3
    assert "gates" not in shown
    assert shown["required_failures"] == ["affine_animation_selftest"]
    assert shown["gate_statuses"]["server_item_bundles"] == "PASS"
    assert "payload" not in raw
    assert len(raw) < 10000
