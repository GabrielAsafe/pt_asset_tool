"""Offline checks for V20 sequential Blender visual review (no Blender needed)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

MODULE = Path(__file__).resolve().parents[1] / "pt_stage072_review_sequencial.py"
spec = importlib.util.spec_from_file_location("etervale_v20_review", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def sample_project(tmp_path: Path, names=("Field/Ricarten/village-2.smd", "Field/Boss/dark_boss.smd")):
    root = tmp_path / "pt_asset_tool"
    app = root / "app"
    (app / "pt_asset_tool/blender").mkdir(parents=True)
    (app / "pt_asset.py").write_text("# fake for offline test\n")
    (app / "pt_asset_tool/blender/open_stage072_preview.py").write_text("# helper\n")
    assets = tmp_path / "Etervale/assets"
    out = app / "pt_build/etervale/stage072_all_maps"
    out.mkdir(parents=True)
    rows = []
    for i, name in enumerate(names):
        src = assets / name
        src.parent.mkdir(parents=True, exist_ok=True)
        data = b"SMD fake test bytes " + name.encode()
        src.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        preview_dir = out / "preview_work" / ("STG-BATCH-" + hashlib.sha256(name.encode()).hexdigest()[:16].upper()) / "stage072_preview"
        preview_dir.mkdir(parents=True)
        blend = preview_dir / "stage072_preview.blend"
        blend.write_bytes(b"CERTIFIED ORIGINAL BLEND " + name.encode())
        rows.append({"asset": name, "status": "REVIEW_REQUIRED" if i == 1 else "PASS_STATIC",
                     "blender": mod.VALID_WORKER_STATUS, "source_sha256": sha,
                     "missing_count": i, "known_missing_count": 0, "invalid_reference_count": 0,
                     "blender_evidence": {"preview_blend": str(blend)}})
    report_path = out / "stage_0_summary.json"
    report_path.write_text(json.dumps({"format": "PT_ETERVALE_STAGE072_ALL_MAPS_V13", "stage": 0,
                                       "client_root": str(assets), "blender_executed": True,
                                       "limited_scan": False, "stage_files_discovered": len(rows),
                                       "rows": rows}), encoding="utf-8")
    launcher = tmp_path / "fake_blender.py"
    launcher.write_text('''import json, os, pathlib, sys
blend = pathlib.Path(sys.argv[1]); assert blend.is_file()
assert blend.name != 'stage072_preview.blend'
assert blend.parent.joinpath('stage072_preview.blend').is_file()
assert sys.argv[2] == '--python'
log = pathlib.Path(os.environ['TEST_LAUNCH_LOG'])
with log.open('a', encoding='utf-8') as f:
    f.write(json.dumps({'blend': str(blend), 'original': str(blend.parent / 'stage072_preview.blend')}) + '\\n')
''')
    return root, report_path, rows, launcher


def test_opens_in_sequence_and_resumes(tmp_path, monkeypatch, capsys):
    root, report, rows, launcher = sample_project(tmp_path)
    log = tmp_path / "launches.jsonl"
    monkeypatch.setenv("TEST_LAUNCH_LOG", str(log))
    cmd = [sys.executable, str(launcher)]
    assert mod.run_review(project_root=root, report_path=report, blender_command=cmd) == 0
    launches = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(launches) == 2
    assert rows[0]["source_sha256"] == mod._file_sha256(tmp_path / "Etervale/assets" / rows[0]["asset"])
    assert "7B2330423265DCB4" in launches[0]["original"]
    assert "67B3DB803D8B5E45" in launches[1]["original"]
    assert all(not Path(x["blend"]).exists() for x in launches)
    assert all(Path(x["original"]).read_bytes().startswith(b"CERTIFIED ORIGINAL BLEND") for x in launches)
    assert mod.run_review(project_root=root, report_path=report, blender_command=cmd) == 0
    assert len(log.read_text().splitlines()) == 2
    summary_path = root / "app/pt_build/etervale/stage072_visual_review/stage_0_avaliacoes_summary.json"
    assert json.loads(summary_path.read_text())["counts"] == {"VISTO_SEM_AVALIACAO": 2}


def test_limit_and_resume(tmp_path, monkeypatch):
    root, report, rows, launcher = sample_project(tmp_path)
    log = tmp_path / "launches.jsonl"
    monkeypatch.setenv("TEST_LAUNCH_LOG", str(log))
    cmd = [sys.executable, str(launcher)]
    assert mod.run_review(project_root=root, report_path=report, blender_command=cmd, limit=1) == 0
    assert len(log.read_text().splitlines()) == 1
    assert mod.run_review(project_root=root, report_path=report, blender_command=cmd) == 0
    assert len(log.read_text().splitlines()) == 2


def test_dry_run_does_not_write_reports_or_launch(tmp_path, monkeypatch):
    root, report, rows, launcher = sample_project(tmp_path)
    log = tmp_path / "launches.jsonl"
    monkeypatch.setenv("TEST_LAUNCH_LOG", str(log))
    assert mod.run_review(project_root=root, report_path=report, dry_run=True) == 0
    assert not log.exists()
    assert not (root / "app/pt_build/etervale/stage072_visual_review").exists()


def test_source_drift_blocks_open_and_marks_not_visited(tmp_path, monkeypatch):
    root, report, rows, launcher = sample_project(tmp_path, ("Field/Ricarten/village-2.smd",))
    src = tmp_path / "Etervale/assets/Field/Ricarten/village-2.smd"
    src.write_bytes(b"modified")
    log = tmp_path / "launches.jsonl"
    monkeypatch.setenv("TEST_LAUNCH_LOG", str(log))
    cmd = [sys.executable, str(launcher)]
    assert mod.run_review(project_root=root, report_path=report, blender_command=cmd) == 3
    assert not log.exists()
    events = mod._load_events(root / "app/pt_build/etervale/stage072_visual_review/stage_0_events.jsonl")
    assert events[-1]["result"] == "FONTE_ALTERADA"


def test_requires_validated_blender_map(tmp_path):
    root, report, rows, launcher = sample_project(tmp_path)
    data = json.loads(report.read_text())
    data["rows"][0]["blender"] = "FAIL_BLENDER_WORKER"
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="MAP_NOT_VALIDATED_IN_BLENDER"):
        mod.load_validated_maps(root, report)


def test_reabrir_works_after_visiting(tmp_path, monkeypatch):
    root, report, rows, launcher = sample_project(tmp_path)
    log = tmp_path / "launches.jsonl"
    monkeypatch.setenv("TEST_LAUNCH_LOG", str(log))
    cmd = [sys.executable, str(launcher)]
    mod.run_review(project_root=root, report_path=report, blender_command=cmd)
    assert mod.run_review(project_root=root, report_path=report, blender_command=cmd,
                          reabrir=rows[1]["asset"]) == 0
    assert len(log.read_text().splitlines()) == 3


def test_approvals_are_only_explicit(tmp_path, monkeypatch):
    root, report, rows, launcher = sample_project(tmp_path, ("Field/Ricarten/village-2.smd",))
    log = tmp_path / "launches.jsonl"
    monkeypatch.setenv("TEST_LAUNCH_LOG", str(log))
    monkeypatch.setattr("builtins.input", lambda _: "a")
    assert mod.run_review(project_root=root, report_path=report,
                          blender_command=[sys.executable, str(launcher)], avaliar=True) == 0
    events = mod._load_events(root / "app/pt_build/etervale/stage072_visual_review/stage_0_events.jsonl")
    assert events[-1]["result"] == "APROVADO_VISUALMENTE"


def test_blender_failure_is_not_counted_as_seen(tmp_path, monkeypatch):
    root, report, rows, launcher = sample_project(tmp_path, ("Field/Ricarten/village-2.smd",))
    launcher.write_text("import sys; sys.exit(17)\n")
    assert mod.run_review(project_root=root, report_path=report, blender_command=[sys.executable, str(launcher)]) == 3
    events = mod._load_events(root / "app/pt_build/etervale/stage072_visual_review/stage_0_events.jsonl")
    assert events[-1]["result"] == "ERRO_ABERTURA"
    assert events[-1]["blender_returncode"] == 17
