from __future__ import annotations

import time
from pathlib import Path

from pt_asset_tool.ui_jobs import JobManager
from pt_asset_tool.ui_actions import ACTION_SPECS, public_action_specs
from pt_asset_tool.ui_capabilities import capabilities_for_asset
from pt_asset_tool.registry import Asset


def _asset(*, family: str, binding: str = "NONE", motions=None) -> Asset:
    rigid = family == "SMD_MODEL_062_RIGID_PHYSIQUE"
    return Asset(
        asset_id="AST-I", primary_path="char/test/body.smd", basename="body.smd",
        extension=".smd", category="CHARACTER", family=family, kind="SMD_MODEL_062",
        compatibility_tier="TEST", size=1, issues=[],
        configs=[{"inx":"char/test/body.inx", "motion_smb":"char/test/body.smb" if rigid else ""}],
        motions=list(motions or (["char/test/body.smb"] if rigid else [])),
        binding_mode=binding, binding_source="TEST",
        binding_skeleton_smb="char/test/body.smb" if rigid else "",
        source_record={"object_count":1, "physique_objects":1 if rigid else 0},
    )


def test_interactive_actions_are_public_and_family_gated():
    public = {x["key"]: x for x in public_action_specs()}
    assert public["validate_visual"]["interactive"] is True
    assert public["validate_animation"]["interactive"] is True

    static = _asset(family="SMD_MODEL_062_STATIC")
    caps, _ = capabilities_for_asset(static, None)
    assert {"validate_visual", "validate_roundtrip"} <= set(caps)
    assert "validate_object_local" not in caps  # requires a physical animated static preflight
    assert "validate_animation" not in caps

    rigid = _asset(family="SMD_MODEL_062_RIGID_PHYSIQUE", binding="ROOT_SKELETON_BOUND")
    caps, _ = capabilities_for_asset(rigid, None)
    assert {"validate_visual", "validate_animation", "diagnose_animation"} <= set(caps)
    assert "validate_roundtrip" not in caps


def test_job_manager_constrained_interactive_stdin(tmp_path: Path):
    script = tmp_path / "ask.py"
    script.write_text(
        "import sys\n"
        "print('Geometry okay? [y]es / [n]o / [s]kip: ', flush=True)\n"
        "ans=input().strip()\n"
        "print('ANSWER='+ans, flush=True)\n"
        "raise SystemExit(0 if ans=='y' else 3)\n",
        encoding="utf-8",
    )
    jm = JobManager(tmp_path, max_concurrent=1)
    job = jm.submit("validate_visual", "char/test/body.smd", ["python3", str(script)], interactive=True)
    deadline = time.time() + 5
    current = None
    while time.time() < deadline:
        current = jm.get(job.id)
        if current and current["accepts_input"] and "[y]es" in (current.get("tail") or ""):
            break
        time.sleep(0.03)
    assert current and current["accepts_input"] is True
    assert current["awaiting_input"] is True
    assert current["input_prompt"] == "Geometry okay?"
    assert jm.send_input(job.id, "arbitrary shell text") is False
    assert jm.send_input(job.id, "PASS") is True
    assert jm.send_input(job.id, "PASS") is False  # one answer per emitted prompt
    deadline = time.time() + 5
    while time.time() < deadline:
        current = jm.get(job.id)
        if current and current["status"] not in {"QUEUED", "RUNNING", "CANCELLING"}:
            break
        time.sleep(0.03)
    assert current["status"] == "PASS"
    assert "ANSWER=y" in current["tail"]

def test_animation_ui_command_carries_review_options(tmp_path: Path):
    (tmp_path / 'pt_asset.py').write_text('# x', encoding='utf-8')
    from pt_asset_tool.ui_actions import build_command
    cmd = build_command(tmp_path, 'validate_animation', 'char/test/body.smd', {
        'motion':'attack', 'load_actions':'all', 'head':'char/test/head.smd', 'head_tier':'b'
    })
    assert cmd[-9:] == [
        'char/test/body.smd', '--motion', 'ATTACK', '--load-actions', 'all',
        '--head', 'char/test/head.smd', '--head-tier', 'b'
    ]


def test_interactive_job_rejects_input_before_prompt(tmp_path: Path):
    script = tmp_path / "delayed_ask.py"
    script.write_text(
        "import time\n"
        "time.sleep(0.4)\n"
        "ans=input('Ready? [y]es / [n]o / [s]kip: ').strip()\n"
        "raise SystemExit(0 if ans=='y' else 3)\n",
        encoding="utf-8",
    )
    jm = JobManager(tmp_path, max_concurrent=1)
    job = jm.submit("validate_visual", None, ["python3", str(script)], interactive=True)
    deadline = time.time() + 2
    while time.time() < deadline:
        current = jm.get(job.id)
        if current and current["status"] == "RUNNING":
            break
        time.sleep(0.01)
    assert jm.send_input(job.id, "PASS") is False
    deadline = time.time() + 3
    while time.time() < deadline:
        current = jm.get(job.id)
        if current and current.get("awaiting_input"):
            break
        time.sleep(0.02)
    assert current and current["awaiting_input"] is True
    assert jm.send_input(job.id, "PASS") is True
