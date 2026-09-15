from __future__ import annotations

import json
from types import SimpleNamespace

import pt_asset_tool.rigid_profile_devtest as auto


def test_auto_work_root_is_isolated_from_artist_generic_import(tmp_path):
    root = auto._work_root(tmp_path, "priestess_c01_m5")
    assert root == tmp_path / "pt_build" / "devtest" / "rigid_profile_auto" / "priestess_c01_m5"
    assert "blender_edits/generic_import" not in root.as_posix()


def test_auto_batch_aggregates_profiles_without_promoting(monkeypatch, tmp_path):
    def fake_run(settings, asset_registry, resolver, certifications, profile_registry, profile_id, *, amplitude):
        return {
            "format": auto.FORMAT,
            "status": "PASS",
            "profile_id": profile_id,
            "asset": f"char/{profile_id}.smd",
            "automatic_devtest_pass": True,
            "runtime_authorized": False,
            "production_authorized": False,
            "client_write_authorized": False,
            "client_modified": False,
        }
    monkeypatch.setattr(auto, "run_rigid_profile_automated_devtest", fake_run)
    settings = SimpleNamespace(project_root=tmp_path)
    result = auto.run_rigid_profile_automated_devtest_batch(
        settings, object(), object(), object(), object(), ["p1", "p2"], amplitude=0.2
    )
    assert result["status"] == "PASS"
    assert result["passed_profiles"] == ["p1", "p2"]
    assert result["failed_profiles"] == []
    assert result["automatic_only"] is True
    assert result["production_authorized"] is False
    assert result["client_write_authorized"] is False
    assert (tmp_path / "pt_build" / "devtest" / "rigid_profile_auto" / "batch_result.json").is_file()


def test_cli_rigid_profile_auto_all_is_one_command(monkeypatch, capsys, tmp_path):
    import pt_asset_tool.cli as cli

    settings = SimpleNamespace(project_root=tmp_path)
    monkeypatch.setattr(cli, "make_context", lambda a: (settings, object(), object(), object()))
    profiles = SimpleNamespace(list=lambda: [SimpleNamespace(profile_id="p1"), SimpleNamespace(profile_id="p2")])
    monkeypatch.setattr(cli, "_profile_registry", lambda s: profiles)
    monkeypatch.setattr(cli, "run_rigid_profile_automated_devtest_batch", lambda *a, **k: {
        "format": auto.BATCH_FORMAT,
        "status": "PASS",
        "profile_count": 2,
        "passed_profiles": ["p1", "p2"],
        "failed_profiles": [],
        "results": [
            {"profile_id":"p1","status":"PASS","asset":"a1","automatic_edit":{"status":"PASS"},"candidate":{"status":"PASS"},"reimport":{"high":{"status":"PASS"},"default":{"status":"PASS"},"low":{"status":"PASS"}},"report":"r1"},
            {"profile_id":"p2","status":"PASS","asset":"a2","automatic_edit":{"status":"PASS"},"candidate":{"status":"PASS"},"reimport":{"high":{"status":"PASS"},"default":{"status":"PASS"},"low":{"status":"PASS"}},"report":"r2"},
        ],
        "report": "batch.json",
    })
    parser = cli.build_parser()
    args = parser.parse_args(["validate", "rigid-profile-auto", "--all"])
    assert args.func(args) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["status"] == "PASS"
    assert shown["automatic_only"] is True
    assert len(shown["profiles"]) == 2
    assert shown["production_authorized"] is False
    assert shown["client_modified"] is False
