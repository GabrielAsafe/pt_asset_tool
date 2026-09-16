from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pt_asset_tool.authoring import authoring_plan, write_workspace_manifest
from pt_asset_tool.blender_workspace import blender_edit_root
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.stage072_authoring_candidate import (
    apply_stage072_candidate_witness,
    build_stage072_edit_extract_command,
    plan_stage072_saved_blender_candidate,
)
from pt_asset_tool.stage072_corpus import parse_stage072

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

pytestmark = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")
TARGET = "Field/AncientW/ancientW.smd"


def _ctx():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    return settings, resolver, registry, registry.resolve(TARGET)


def test_stage072_authoring_plan_exposes_strict_candidate_not_production():
    _settings, resolver, _registry, asset = _ctx()
    plan = authoring_plan(asset, resolver.resolve(asset.primary_path))
    saved = plan["channels"]["saved_blender_build"]
    assert saved["maturity"] == "CANDIDATE_STRICT_EDIT_SET"
    assert saved["accepted_edit_modes"] == ["UV_ONLY", "GEOMETRY_GRID_MULTI"]
    assert plan["client_write_authorized"] is False


def test_stage072_candidate_requires_workspace_and_manifest(tmp_path):
    _settings, resolver, _registry, asset = _ctx()
    plan = plan_stage072_saved_blender_candidate(tmp_path, resolver, asset)
    assert plan["status"] == "BLOCKED"
    assert "GENERIC_IMPORT_WORKSPACE_MISSING" in plan["blockers"]
    assert "AUTHORING_MANIFEST_MISSING" in plan["blockers"]
    assert plan["production_authorized"] is False


def test_stage072_candidate_ready_with_verified_workspace_and_command(tmp_path):
    _settings, resolver, _registry, asset = _ctx()
    source = resolver.resolve(asset.primary_path)
    workspace = blender_edit_root(tmp_path, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True)
    (workspace / "imported.blend").write_bytes(b"blend")
    write_workspace_manifest(workspace, asset, source, authoring_plan(asset, source), [])
    candidate = plan_stage072_saved_blender_candidate(tmp_path, resolver, asset)
    assert candidate["status"] == "READY"
    assert Path(candidate["output"]).is_relative_to(tmp_path / "pt_build")
    helper = tmp_path / "pt_asset_tool" / "blender" / "extract_stage072_saved_edit.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# helper")
    fake = SimpleNamespace(project_root=tmp_path, blender_command=lambda: ["blender-test"])
    cmd = build_stage072_edit_extract_command(fake, candidate, witness=tmp_path/"w.json", report=tmp_path/"r.json")
    assert cmd[0] == "blender-test"
    assert "--background" in cmd and "--python-exit-code" in cmd
    assert str(helper.resolve()) in cmd
    assert cmd[cmd.index("--expected-source-sha256") + 1] == candidate["source_sha256"]


def test_stage072_candidate_host_applies_uv_witness_with_strict_compare(tmp_path):
    _settings, resolver, _registry, asset = _ctx()
    source = Path(resolver.resolve(asset.primary_path))
    workspace = blender_edit_root(tmp_path, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True)
    (workspace / "imported.blend").write_bytes(b"blend")
    write_workspace_manifest(workspace, asset, source, authoring_plan(asset, source), [])
    candidate = plan_stage072_saved_blender_candidate(tmp_path, resolver, asset)
    parsed = parse_stage072(source, include_payload=True)
    face_index = next(i for i, f in enumerate(parsed["payload"]["faces"]) if f.get("texlink_chain"))
    face = parsed["payload"]["faces"][face_index]
    ti = int(face["texlink_chain"][0])
    before = float(parsed["payload"]["texlinks"][ti]["u"][0])
    witness = tmp_path / "saved_edit.json"
    witness.write_text(json.dumps({
        "format": "PT_STAGE072_SAVED_EDIT_WITNESS_V1",
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "edit_mode": "UV_ONLY",
        "uv_edits": [{
            "face_index": face_index,
            "material_id": int(face["material"]),
            "stage_index": 0,
            "corner": 0,
            "component": "u",
            "before": before,
            "after": before + 0.03125,
            "texlink_index": ti,
        }],
    }, indent=2) + "\n")
    result = apply_stage072_candidate_witness(candidate, witness)
    assert result["status"] == "PASS"
    assert result["edit_mode"] == "UV_ONLY"
    assert result["compare"]["check"] == "PASS"
    assert result["production_authorized"] is False
    assert result["client_write_authorized"] is False
    assert Path(result["output"]).is_file()
