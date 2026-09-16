from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

requires_fixture = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")
CORE = ROOT / "pt_asset_core_v0_8_9.py"
APP = ROOT / "pt_asset.py"


def _run(*args):
    env = dict(os.environ)
    env["PT_CLIENT_ROOT"] = str(CLIENT)
    return subprocess.run(
        [sys.executable, str(CORE), *args], cwd=ROOT, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


@requires_fixture
def test_binding_coverage_cli_contract():
    r = _run("audit", "binding-coverage", "--category", "MONSTER", "--sample-limit", "1")
    assert r.returncode == 0, r.stdout
    d = json.loads(r.stdout)
    assert d["format"] == "PT_BINDING_COVERAGE_AUDIT_V1"
    assert d["policy"]["folder_identity_is_binding_evidence"] is False


@requires_fixture
def test_profile_verify_cli_fails_closed_on_partial_fixture():
    r = _run("profiles", "verify", "pikeman_c01_m4")
    assert r.returncode == 3, r.stdout
    d = json.loads(r.stdout)
    assert d["format"] == "PT_CHARACTER_PROFILE_VERIFY_BATCH_V1"
    assert d["status"] == "FAIL"
    assert d["results"][0]["authoring_authorized"] is False


@requires_fixture
def test_entities_cli_exposes_registry_evidence_without_runtime_promotion():
    r = _run("entities", "inspect", "NPC", "Ahin")
    assert r.returncode == 0, r.stdout
    d = json.loads(r.stdout)
    e = d["entity"]
    assert d["format"] == "PT_LIVE_ENTITY_DETAIL_V1"
    assert e["display_name"] == "Ahin"
    assert e["registry_evidence"] is True
    assert e["rigid_binding_ready_count"] >= 1
    assert e["runtime_status"] == "UNPROVEN"
    assert e["writer_status"] == "UNAUTHORIZED"
    assert d["policy"]["registry_binding_is_runtime_certification"] is False


def test_consolidated_help_surfaces_new_normal_commands():
    r = subprocess.run(
        [sys.executable, str(APP), "--help"], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    assert r.returncode == 0, r.stdout
    assert "audit binding-coverage" in r.stdout
    assert "entities list" in r.stdout
    assert "profiles list | inspect | lod | verify" in r.stdout
    assert "import ASSET" in r.stdout and "build ASSET --plan" in r.stdout


@requires_fixture
def test_candidate_writer_corpus_audit_cli_contracts():
    for audit_name in ("inx-writer-corpus", "smb-writer-corpus"):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "pt_asset.py"), "--client-root", str(CLIENT), "audit", audit_name, "--sample-limit", "2"],
            cwd=ROOT, text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        data = json.loads(proc.stdout)
        assert data["status"] == "PASS"
        assert data["client_modified"] is False
        assert data["production_authorized"] is False


def _run_app(*args):
    env = dict(os.environ)
    env["PT_CLIENT_ROOT"] = str(CLIENT)
    return subprocess.run(
        [sys.executable, str(APP), *args], cwd=ROOT, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


@requires_fixture
def test_assets_list_default_is_catalog_focused_and_gates_are_opt_in():
    plain = _run_app("assets", "list", "--limit", "1")
    assert plain.returncode == 0, plain.stdout
    header = plain.stdout.splitlines()[0]
    assert "BINDING" in header and "PATH" in header
    assert "STRUCT" not in header and "VISUAL" not in header and "ANIM" not in header
    assert "--gates" in plain.stdout

    gated = _run_app("assets", "list", "--limit", "1", "--gates")
    assert gated.returncode == 0, gated.stdout
    gated_header = gated.stdout.splitlines()[0]
    assert "STRUCT" in gated_header and "VISUAL" in gated_header and "ANIM" in gated_header
    assert "PENDING = this certification/gate has not been completed yet" in gated.stdout
    assert "N/A     = the check does not apply" in gated.stdout
    assert "ROOT_SKELETON_BOUND" in gated.stdout


def test_explain_topics_are_user_facing_and_available_without_client():
    expected = {
        "statuses": "PENDING",
        "bindings": "ROOT_SKELETON_BOUND",
        "structural": "Structural validation",
        "visual": "Visual validation",
        "roundtrip": "Roundtrip",
        "object-local": "Object-local",
        "texlinks": "TexLink",
        "desktop-entry": "desktop",
    }
    for topic, marker in expected.items():
        proc = subprocess.run(
            [sys.executable, str(APP), "explain", topic], cwd=ROOT,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        assert proc.returncode == 0, f"{topic}: {proc.stdout}"
        assert marker.lower() in proc.stdout.lower(), (topic, proc.stdout)


def test_candidate_require_edit_policy_distinguishes_noop_from_controlled_edit():
    from pt_asset_tool.cli import _enforce_candidate_edit_requirement

    noop = _enforce_candidate_edit_requirement(
        "RIGID", {"status":"PASS", "errors":[], "edit_observed":False}, True
    )
    assert noop["status"] == "FAIL"
    assert "TARGET_EDIT_NOT_OBSERVED" in noop["errors"]
    assert noop["edit_required"] is True

    edited = _enforce_candidate_edit_requirement(
        "RIGID", {"status":"PASS", "errors":[], "edit_observed":True}, True
    )
    assert edited["status"] == "PASS"
    assert edited["errors"] == []
    assert edited["edit_required"] is True

    legacy_noop = _enforce_candidate_edit_requirement(
        "RIGID", {"status":"PASS", "errors":[], "edit_observed":False}, False
    )
    assert legacy_noop["status"] == "PASS"
    assert legacy_noop["edit_required"] is False
