from __future__ import annotations

import json
import pathlib
import struct
from types import SimpleNamespace

import pytest

from pt_asset_tool.authoring import write_workspace_manifest
from pt_asset_tool.blender_workspace import blender_edit_root
from pt_asset_tool.workspace_bundle_deploy import (
    APPLY_CONFIRMATION,
    RESTORE_CONFIRMATION,
    _build_texture_game_bytes,
    apply_workspace_bundle_transaction,
    prepare_workspace_bundle,
    restore_workspace_bundle_transaction,
    workspace_bundle_status,
    publish_workspace_bundle,
)
from pt_protected_tga_v1 import decode_bytes as decode_tga_bytes, protect_header
from pt_character_texture_v1_4 import decode_editable as decode_bmp_editable, inspect_bmp_bytes


def _bmp(width=2, height=2, seed=10):
    stride = ((width * 24 + 31) // 32) * 4
    pixels = bytearray(stride * height)
    for i in range(len(pixels)):
        pixels[i] = (seed + i) & 0xFF
    size = 54 + len(pixels)
    hdr = (
        b"BM" + struct.pack("<I", size) + b"\0\0\0\0" + struct.pack("<I", 54)
        + struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    )
    return hdr + bytes(pixels)


def _tga(width=2, height=2, seed=20):
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, width, height, 24, 0)
    pixels = bytes((seed + i) & 0xFF for i in range(width * height * 3))
    return header + pixels


class Resolver:
    def __init__(self, client): self.client = pathlib.Path(client)
    def resolve(self, value, required=True):
        p = self.client / pathlib.PurePosixPath(str(value).replace("\\", "/"))
        if required and not p.is_file(): raise FileNotFoundError(p)
        return p if p.is_file() else None


class Registry:
    def __init__(self, asset): self.asset = asset
    def resolve(self, target): return self.asset


def _fixture(tmp_path, *, texture_bytes=None, overlay_bytes=None, deps=True):
    project = tmp_path / "project"
    client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    logical = "char/npc/Test/Test.smd"
    model = client / logical
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model-baseline")
    inx = model.with_suffix(".inx"); smb = model.with_suffix(".smb")
    inx.write_bytes(b"inx-baseline"); smb.write_bytes(b"smb-baseline")
    asset = SimpleNamespace(
        asset_id="asset-test", primary_path=logical,
        family="SMD_MODEL_062_STATIC", kind="SMD_MODEL_062",
    )
    settings = SimpleNamespace(project_root=project, client_root=client)
    resolver = Resolver(client); registry = Registry(asset)
    work = blender_edit_root(project, "generic_import", logical)
    work.mkdir(parents=True)
    (work / "imported.blend").write_bytes(b"blend")
    write_workspace_manifest(work, asset, model, {"generic_build_authorized": False}, [inx, smb] if deps else [])
    (work / "workspace_info.json").write_text(json.dumps({"asset": logical}), encoding="utf-8")
    (work / "import_summary.json").write_text(json.dumps({"asset": logical, "mode": "STATIC", "lod": "default"}), encoding="utf-8")
    if texture_bytes is not None:
        tex = client / "char/npc/Test/skin.bmp"
        tex.write_bytes(texture_bytes)
        overlay = work / "texture_overlay_client" / "char/npc/Test/skin.bmp"
        overlay.parent.mkdir(parents=True)
        overlay.write_bytes(overlay_bytes if overlay_bytes is not None else texture_bytes)
        (work / "texture_overlay_report.json").write_text(json.dumps({
            "asset": logical, "entries": [{
                "logical": "char\\npc\\Test\\skin.bmp", "physical": str(tex), "prepared": str(overlay), "runtime_alias": None,
            }]
        }), encoding="utf-8")
    return settings, resolver, registry, asset, model, inx, smb, work


def test_protected_bmp_workspace_edit_rebuilds_runtime_container(tmp_path):
    std = _bmp(seed=1)
    protected = b"PTPROTECTED!!!" + std[14:]
    info = inspect_bmp_bytes(protected)
    editable = bytearray(decode_bmp_editable(protected, info)); editable[-1] ^= 0x3F
    src = tmp_path / "x.bmp"; edit = tmp_path / "edit.bmp"
    src.write_bytes(protected); edit.write_bytes(bytes(editable))
    built, meta = _build_texture_game_bytes(src, edit)
    assert meta["status"] == "MODIFIED"
    assert built[:14] == protected[:14]
    assert decode_bmp_editable(built, inspect_bmp_bytes(built)) == bytes(editable)


def test_protected_tga_workspace_edit_preserves_protection_mode(tmp_path):
    std = _tga(seed=4)
    protected = protect_header(std[:18], "FULL18") + std[18:]
    decoded, info = decode_tga_bytes(protected)
    edited = bytearray(decoded); edited[-1] ^= 0x55
    src = tmp_path / "x.tga"; edit = tmp_path / "edit.tga"
    src.write_bytes(protected); edit.write_bytes(bytes(edited))
    built, meta = _build_texture_game_bytes(src, edit)
    rebuilt, rinfo = decode_tga_bytes(built)
    assert meta["status"] == "MODIFIED"
    assert rinfo["protection_mode"] == info["protection_mode"] == "FULL18"
    assert rebuilt == bytes(edited)


def test_prepare_apply_restore_texture_bundle_is_transactional(tmp_path):
    original = _bmp(seed=30); edited = bytearray(original); edited[-2] ^= 0x7A
    settings, resolver, registry, asset, model, inx, smb, work = _fixture(
        tmp_path, texture_bytes=original, overlay_bytes=bytes(edited)
    )
    result = prepare_workspace_bundle(settings, resolver, registry, asset.primary_path, include_model=False)
    assert result["status"] == "READY"
    assert result["summary"]["changed_texture_count"] == 1
    assert result["summary"]["tracked_file_count"] == 4  # model + INX + SMB + texture
    assert model.read_bytes() == b"model-baseline"
    assert inx.read_bytes() == b"inx-baseline"
    assert smb.read_bytes() == b"smb-baseline"
    tex = settings.client_root / "char/npc/Test/skin.bmp"
    assert tex.read_bytes() == original

    applied = apply_workspace_bundle_transaction(result["manifest"], confirm=APPLY_CONFIRMATION)
    assert applied["status"] == "PASS"
    assert applied["written_file_count"] == 1
    assert tex.read_bytes() == bytes(edited)
    state = workspace_bundle_status(result["manifest"])
    assert state["status"] == "PASS" and state["deployed_count"] == 1 and state["drift_count"] == 0

    restored = restore_workspace_bundle_transaction(result["manifest"], confirm=RESTORE_CONFIRMATION)
    assert restored["status"] == "PASS"
    assert tex.read_bytes() == original
    assert model.read_bytes() == b"model-baseline"
    assert inx.read_bytes() == b"inx-baseline"
    assert smb.read_bytes() == b"smb-baseline"


def test_apply_refuses_context_drift_before_any_write(tmp_path):
    original = _bmp(seed=50); edited = bytearray(original); edited[-1] ^= 1
    settings, resolver, registry, asset, model, inx, smb, work = _fixture(
        tmp_path, texture_bytes=original, overlay_bytes=bytes(edited)
    )
    result = prepare_workspace_bundle(settings, resolver, registry, asset.primary_path, include_model=False)
    tex = settings.client_root / "char/npc/Test/skin.bmp"
    inx.write_bytes(b"external-drift")
    with pytest.raises(RuntimeError, match="prewrite verification failed"):
        apply_workspace_bundle_transaction(result["manifest"], confirm=APPLY_CONFIRMATION)
    assert tex.read_bytes() == original


def test_apply_rolls_back_texture_when_post_validation_fails(tmp_path, monkeypatch):
    original = _bmp(seed=70); edited = bytearray(original); edited[-3] ^= 0x23
    settings, resolver, registry, asset, model, inx, smb, work = _fixture(
        tmp_path, texture_bytes=original, overlay_bytes=bytes(edited)
    )
    result = prepare_workspace_bundle(settings, resolver, registry, asset.primary_path, include_model=False)
    # Force a model post-validator failure after the texture has been written.
    p = pathlib.Path(result["manifest"])
    data = json.loads(p.read_text())
    data["model_build"] = {"status": "MODIFIED", "kind": "UNSUPPORTED"}
    p.write_text(json.dumps(data), encoding="utf-8")
    tex = settings.client_root / "char/npc/Test/skin.bmp"
    applied = apply_workspace_bundle_transaction(p, confirm=APPLY_CONFIRMATION)
    assert applied["status"] == "FAIL"
    assert applied["state"] == "ROLLED_BACK"
    assert applied["rollback_performed"] is True and applied["rollback_pass"] is True
    assert tex.read_bytes() == original


def test_prepare_full_bundle_tracks_model_and_preserve_dependencies(tmp_path, monkeypatch):
    original = _bmp(seed=90); edited = bytearray(original); edited[-4] ^= 0x11
    settings, resolver, registry, asset, model, inx, smb, work = _fixture(
        tmp_path, texture_bytes=original, overlay_bytes=bytes(edited)
    )
    import pt_asset_tool.workspace_bundle_deploy as mod
    def fake_build(settings, resolver, asset, txroot, **kwargs):
        candidate = txroot / "evidence/model/Test.smd"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"model-edited")
        return {
            "status": "MODIFIED", "kind": "STATIC", "candidate": str(candidate),
            "candidate_sha256": mod._sha256(candidate), "candidate_size": candidate.stat().st_size,
            "target_object": "Test", "verification": {"status": "PASS", "edit_observed": True},
        }
    monkeypatch.setattr(mod, "_build_model_candidate", fake_build)
    result = prepare_workspace_bundle(settings, resolver, registry, asset.primary_path, include_model=True)
    assert result["status"] == "READY"
    assert result["summary"]["changed_model_count"] == 1
    assert result["summary"]["changed_texture_count"] == 1
    by_role = {x["role"]: x for x in result["entries"]}
    assert by_role["MODEL"]["state"] == "MODIFIED"
    assert by_role["MODEL_INFO_INX"]["state"] == "PRESERVE_ONLY"
    assert by_role["SKELETON_OR_MOTION_SMB"]["state"] == "PRESERVE_ONLY"


def test_exact_confirmation_is_required(tmp_path):
    original = _bmp(seed=110); edited = bytearray(original); edited[-1] ^= 1
    settings, resolver, registry, asset, *_ = _fixture(tmp_path, texture_bytes=original, overlay_bytes=bytes(edited))
    result = prepare_workspace_bundle(settings, resolver, registry, asset.primary_path, include_model=False)
    with pytest.raises(RuntimeError, match="exact confirmation"):
        apply_workspace_bundle_transaction(result["manifest"], confirm="yes")




def test_prepare_passes_strict_rigid_weight_policy_to_model_build(tmp_path, monkeypatch):
    original = _bmp(seed=126)
    settings, resolver, registry, asset, *_ = _fixture(tmp_path, texture_bytes=original, overlay_bytes=original)
    import pt_asset_tool.workspace_bundle_deploy as mod

    seen = {}
    def fake_build(*args, **kwargs):
        seen.update(kwargs)
        return {"status": "UNCHANGED", "kind": "RIGID", "verification": {"status": "PASS", "edit_observed": False}}
    monkeypatch.setattr(mod, "_build_model_candidate", fake_build)
    result = prepare_workspace_bundle(
        settings, resolver, registry, asset.primary_path, include_model=True,
        auto_rigid_weight_repair=False,
    )
    assert result["status"] == "NO_CHANGES"
    assert seen["auto_rigid_weight_repair"] is False
    assert result["policy"]["rigid_weight_policy"] == "STRICT"

def test_ui_publish_and_restore_commands_are_explicit_client_mutations(tmp_path):
    from pt_asset_tool.ui_actions import ACTION_SPECS, build_command, public_action_specs
    publish = ACTION_SPECS["publish_bundle"]
    restore = ACTION_SPECS["restore_bundle"]
    check = ACTION_SPECS["check_bundle"]
    assert publish.mutates_client is True
    assert restore.mutates_client is True
    assert check.mutates_client is False
    public = {x["key"]: x for x in public_action_specs()}
    assert public["publish_bundle"]["mutates_client"] is True
    (tmp_path / "pt_asset.py").write_text("# test entrypoint\n", encoding="utf-8")
    cmd = build_command(tmp_path, "publish_bundle", "char/npc/Test/Test.smd", {})
    assert cmd[-4:] == ["workspace-publish", "char/npc/Test/Test.smd", "--confirm", "APPLY CLIENT BUNDLE"]
    tcmd = build_command(tmp_path, "publish_bundle", "char/npc/Test/Test.smd", {"textures_only": True})
    assert tcmd[-1] == "--textures-only"
    strict_cmd = build_command(tmp_path, "publish_bundle", "char/npc/Test/Test.smd", {"no_auto_rigid_weight_repair": True})
    assert strict_cmd[-1] == "--no-auto-rigid-weight-repair"
    ccmd = build_command(tmp_path, "check_bundle", "char/npc/Test/Test.smd", {})
    assert ccmd[-3:] == ["deploy", "workspace-check", "char/npc/Test/Test.smd"]
    rcmd = build_command(tmp_path, "restore_bundle", "char/npc/Test/Test.smd", {})
    assert rcmd[-4:] == ["workspace-restore-latest", "char/npc/Test/Test.smd", "--confirm", "RESTORE CLIENT BUNDLE"]


def test_publish_blocks_partial_runtime_lod_coverage_by_default(monkeypatch):
    import pt_asset_tool.workspace_bundle_deploy as mod

    prepared = {
        "status": "READY",
        "asset": "char/npc/Test/Test.smd",
        "manifest": "/tmp/transaction.json",
        "summary": {"changed_file_count": 1},
        "errors": [],
        "model_build": {
            "status": "MODIFIED",
            "kind": "RIGID",
            "available_lods": ["high", "default"],
            "changed_lods": ["default"],
            "uncovered_lods": ["high"],
            "runtime_lod_coverage_complete": False,
        },
    }
    monkeypatch.setattr(mod, "prepare_workspace_bundle", lambda *a, **k: prepared)
    monkeypatch.setattr(mod, "apply_workspace_bundle_transaction", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write")))
    result = publish_workspace_bundle(object(), object(), object(), prepared["asset"], confirm=APPLY_CONFIRMATION)
    assert result["status"] == "FAIL"
    assert result["state"] == "RUNTIME_LOD_COVERAGE_INCOMPLETE"
    assert result["client_modified"] is False


def test_publish_partial_runtime_lod_requires_explicit_override(monkeypatch):
    import pt_asset_tool.workspace_bundle_deploy as mod

    prepared = {
        "status": "READY",
        "asset": "char/npc/Test/Test.smd",
        "manifest": "/tmp/transaction.json",
        "summary": {"changed_file_count": 1},
        "errors": [],
        "model_build": {
            "status": "MODIFIED",
            "kind": "RIGID",
            "available_lods": ["high", "default"],
            "changed_lods": ["default"],
            "uncovered_lods": ["high"],
            "runtime_lod_coverage_complete": False,
        },
    }
    monkeypatch.setattr(mod, "prepare_workspace_bundle", lambda *a, **k: prepared)
    monkeypatch.setattr(mod, "apply_workspace_bundle_transaction", lambda *a, **k: {
        "status": "PASS", "state": "APPLIED_VERIFIED", "client_modified": True,
    })
    result = publish_workspace_bundle(
        object(), object(), object(), prepared["asset"], confirm=APPLY_CONFIRMATION, allow_partial_lod=True
    )
    assert result["status"] == "PASS"
    assert result["state"] == "APPLIED_VERIFIED"
    assert result["client_modified"] is True


def test_rigid_model_build_probes_all_saved_lods_and_tracks_visibility_coverage(tmp_path, monkeypatch):
    import pt_asset_tool.workspace_bundle_deploy as mod

    project = tmp_path / "project"; project.mkdir()
    source = tmp_path / "client" / "char/npc/Test/Test.smd"
    source.parent.mkdir(parents=True); source.write_bytes(b"source-model")
    skeleton = source.with_suffix(".smb"); skeleton.write_bytes(b"skeleton")
    asset = SimpleNamespace(
        family="SMD_MODEL_062_RIGID_PHYSIQUE",
        primary_path="char/npc/Test/Test.smd",
    )
    settings = SimpleNamespace(project_root=project)

    class R:
        def resolve(self, logical, required=True):
            if str(logical).lower().endswith(".smb"):
                return skeleton
            return source

    workspace = blender_edit_root(project, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True)
    (workspace / "authoring_manifest.json").write_text("{}", encoding="utf-8")
    (workspace / "pristine_import.blend").write_bytes(b"pristine-blend")
    (workspace / "imported.blend").write_bytes(b"edited-blend")
    context = {
        "lod": "default",
        "lod_groups": {"high": ["BodyH"], "default": ["BodyL"], "low": []},
        "selected_lod_nodes": ["BodyL"],
        "skeleton_smb": {"path": str(skeleton), "logical": "char/npc/Test/Test.smb"},
    }
    monkeypatch.setattr(mod, "verify_workspace_manifest", lambda p: {"status": "PASS", "selected_context": context})
    monkeypatch.setattr(mod, "authoring_plan", lambda asset, src: {"source_analysis": {"objects": [
        {"name": "BodyH", "physique": True, "has_object_local_animation": False, "faces": 2, "vertices": 4, "texlink_min_layers": 1, "texlink_max_layers": 1},
        {"name": "BodyL", "physique": True, "has_object_local_animation": False, "faces": 2, "vertices": 4, "texlink_min_layers": 1, "texlink_max_layers": 1},
    ]}})

    def fake_plan(project_root, resolver, asset, *, object_name=None, output=None, lod_scope="selected"):
        return {
            "status": "READY", "object": object_name, "output": str(output),
            "source": str(source), "source_sha256": mod._sha256(source),
            "skeleton": str(skeleton), "selected_context": context,
            "blend": str(workspace / "imported.blend"),
        }
    monkeypatch.setattr(mod, "plan_rigid_saved_blender_candidate", fake_plan)
    seen_policies = []
    seen_blends = []
    def fake_cmd(settings, plan, report):
        seen_policies.append(plan.get("physique_policy"))
        seen_blends.append(pathlib.Path(plan["blend"]).name)
        return ["FAKE", str(plan["object"]), str(plan["output"])]
    monkeypatch.setattr(mod, "build_rigid_candidate_blender_command", fake_cmd)

    def fake_run(cmd, log):
        out = pathlib.Path(cmd[2]); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(("candidate-" + cmd[1]).encode())
        pathlib.Path(log).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(log).write_text("ok\n", encoding="utf-8")
    monkeypatch.setattr(mod, "run_logged", fake_run)
    monkeypatch.setattr(mod, "validate_rigid_candidate_output", lambda root, src, out, skel, obj: {
        "status": "PASS", "edit_observed": True, "byte_edit_observed": True,
    })
    monkeypatch.setattr(mod, "compare_rigid_candidate_semantics", lambda baseline, edited, obj: {
        "status": "PASS", "edit_observed": obj == "BodyH",
        "vertex_payload_changed": obj == "BodyH",
        "face_uv_material_changed": False,
        "physique_assignment_changed": False,
    })
    monkeypatch.setattr(mod, "validate_rigid_profile_stress_output", lambda *a, **k: {"status": "PASS", "all_target_edits_observed": True})

    result = mod._build_model_candidate(settings, R(), asset, project / "pt_build" / "tx")
    assert result["status"] == "MODIFIED"
    assert [x["object"] for x in result["probes"]] == ["BodyH", "BodyL"]
    assert result["target_objects"] == ["BodyH"]
    assert result["selected_lod"] == "default"
    assert result["changed_lods"] == ["high"]
    assert result["unmodified_lods"] == ["default"]
    assert result["uncovered_lods"] == []
    assert result["runtime_lod_coverage_complete"] is True
    assert result["physique_policy"] == "AUTO_REPAIR"
    assert result["physique_probe_policy"] == "PRISTINE_VS_EDITED_AUTO_REPAIR"
    # Two probes (pristine + edited) and one final changed-object build all use AUTO.
    assert seen_policies == ["auto", "auto", "auto", "auto", "auto"]
    assert seen_blends[:4] == ["pristine_import.blend", "imported.blend", "pristine_import.blend", "imported.blend"]


def test_rigid_workspace_semantic_compare_ignores_equal_import_normalization(tmp_path, monkeypatch):
    import pt_asset_tool.rigid_authoring_candidate as mod

    baseline = tmp_path / "baseline.smd"; baseline.write_bytes(b"baseline")
    edited = tmp_path / "edited.smd"; edited.write_bytes(b"edited")
    obj = {
        "nv": 3, "nf": 1, "nt": 1, "phys": True,
        "vertices": [(1, 2, 3), (4, 5, 6), (7, 8, 9)],
        "faces": [{"verts": (0, 1, 2), "material": 0, "uv_layers": [[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]]}],
    }
    monkeypatch.setattr(mod, "_physique_names", lambda row: ["Bone"] * int(row["nv"]))
    monkeypatch.setattr(mod, "parse_model062_bytes", lambda raw: {"objects": {"BodyH": dict(obj)}})
    result = mod.compare_rigid_candidate_semantics(baseline, edited, "BodyH")
    assert result["status"] == "PASS"
    assert result["edit_observed"] is False


def test_rigid_candidate_command_physique_policy_is_explicit(tmp_path):
    from types import SimpleNamespace
    from pt_asset_tool.rigid_authoring_candidate import build_rigid_candidate_blender_command

    writer = tmp_path / "pt_blender_to_smd_free_mesh_v3.py"
    writer.write_text("# writer\n", encoding="utf-8")
    blend = tmp_path / "edit.blend"; blend.write_bytes(b"blend")
    source = tmp_path / "model.smd"; source.write_bytes(b"source")
    skeleton = tmp_path / "model.smb"; skeleton.write_bytes(b"skeleton")
    output = tmp_path / "out.smd"
    report = tmp_path / "writer.json"

    settings = SimpleNamespace(
        project_root=tmp_path,
        blender_command=lambda: ["blender"],
    )
    plan = {
        "status": "READY",
        "blend": str(blend),
        "source": str(source),
        "source_sha256": "a" * 64,
        "skeleton": str(skeleton),
        "object": "BodyH",
        "output": str(output),
    }
    cmd = build_rigid_candidate_blender_command(settings, plan, report=report)
    assert cmd[-2:] == ["--physique-policy", "auto"]
    plan["physique_policy"] = "strict"
    assert build_rigid_candidate_blender_command(settings, plan, report=report)[-2:] == ["--physique-policy", "strict"]
    plan["physique_policy"] = "source"
    assert build_rigid_candidate_blender_command(settings, plan, report=report)[-2:] == ["--physique-policy", "source"]


def test_prepare_warns_when_rigid_weights_are_auto_repaired(tmp_path, monkeypatch):
    original = _bmp(seed=125)
    settings, resolver, registry, asset, *_ = _fixture(tmp_path, texture_bytes=original, overlay_bytes=original)
    import pt_asset_tool.workspace_bundle_deploy as mod

    candidate = settings.project_root / "pt_build" / "candidate.smd"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"candidate")

    monkeypatch.setattr(mod, "_build_model_candidate", lambda *a, **k: {
        "status": "MODIFIED",
        "kind": "RIGID",
        "candidate": str(candidate),
        "candidate_sha256": mod._sha256(candidate),
        "candidate_size": candidate.stat().st_size,
        "target_objects": ["BodyL"],
        "available_lods": ["high", "default"],
        "changed_lods": ["default"],
        "unmodified_lods": ["high"],
        "partial_lods": [],
        "uncovered_lods": [],
        "runtime_lod_coverage_complete": True,
        "physique_policy": "AUTO_REPAIR",
        "physique_preserve_objects": ["BodyH"],
        "blender_weight_mismatch_count": 1,
        "auto_rigid_weight_repair_enabled": True,
        "blender_weight_repair_count": 1,
        "blender_weight_repairs": [{"object": "BodyL", "vertex": 7, "selected_bone": "Bip01", "serialized_weight": 1.0}],
        "verification": {"status": "PASS", "edit_observed": True},
    })
    result = prepare_workspace_bundle(settings, resolver, registry, asset.primary_path, include_model=True)
    assert result["status"] == "READY"
    assert result["summary"]["unmodified_model_lods"] == ["high"]
    assert result["summary"]["blender_weight_mismatch_count"] == 1
    assert result["summary"]["blender_weight_repair_count"] == 1
    assert result["summary"]["auto_rigid_weight_repair_enabled"] is True
    assert result["summary"]["physique_preserve_objects"] == ["BodyH"]
    assert any(x.startswith("AUTO_RIGID_WEIGHT_REPAIR:") for x in result["warnings"])
    assert any(x == "RUNTIME_LODS_UNMODIFIED:high" for x in result["warnings"])


def test_writer_auto_rigid_weight_repair_is_stable_and_serializes_one_bone(tmp_path):
    import ast
    from types import SimpleNamespace

    writer = pathlib.Path(__file__).resolve().parents[1] / "pt_blender_to_smd_free_mesh_v3.py"
    tree = ast.parse(writer.read_text(encoding="utf-8"))
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module or ""]
            if any(name == "hashlib" for name in names):
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"rigid_bone_rows", "auto_rigid_bone"}:
            keep.append(node)
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(writer), "exec"), ns)

    groups = [SimpleNamespace(name="Bip01 Spine1"), SimpleNamespace(name="Bip01 L Clavicle")]
    vertex = SimpleNamespace(groups=[SimpleNamespace(group=0, weight=0.5), SimpleNamespace(group=1, weight=0.5)])
    obj = SimpleNamespace(data=SimpleNamespace(vertices=[vertex]), vertex_groups=groups)
    skeleton = {"Bip01 Spine1": object(), "Bip01 L Clavicle": object()}

    bone1, repair1 = ns["auto_rigid_bone"](
        obj, 0, seed_material="same-source|BodyH", skeleton=skeleton, conflict_keys=set(), source_bone="Bip01 Spine1"
    )
    bone2, repair2 = ns["auto_rigid_bone"](
        obj, 0, seed_material="same-source|BodyH", skeleton=skeleton, conflict_keys=set(), source_bone="Bip01 Spine1"
    )
    assert bone1 == bone2
    assert bone1 in skeleton
    assert repair1 == repair2
    assert repair1["serialized_weight"] == 1.0
    assert repair1["strategy"] == "stable_pseudorandom_group"
    assert repair1["original_weights"] == [["Bip01 Spine1", 0.5], ["Bip01 L Clavicle", 0.5]]


def test_writer_auto_rigid_weight_repair_uses_source_only_when_no_valid_group(tmp_path):
    import ast
    from types import SimpleNamespace

    writer = pathlib.Path(__file__).resolve().parents[1] / "pt_blender_to_smd_free_mesh_v3.py"
    tree = ast.parse(writer.read_text(encoding="utf-8"))
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if "hashlib" in names:
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"rigid_bone_rows", "auto_rigid_bone"}:
            keep.append(node)
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(writer), "exec"), ns)

    groups = [SimpleNamespace(name="UnknownBone")]
    vertex = SimpleNamespace(groups=[SimpleNamespace(group=0, weight=0.25)])
    obj = SimpleNamespace(data=SimpleNamespace(vertices=[vertex]), vertex_groups=groups)
    skeleton = {"Bip01 Spine1": object()}
    bone, repair = ns["auto_rigid_bone"](
        obj, 0, seed_material="x", skeleton=skeleton, conflict_keys=set(), source_bone="Bip01 Spine1"
    )
    assert bone == "Bip01 Spine1"
    assert repair["strategy"] == "source_fallback_no_valid_blender_group"
    assert repair["serialized_weight"] == 1.0


def test_missing_pristine_is_rebuilt_from_verified_rigid_context_without_touching_edited_blend(tmp_path, monkeypatch):
    import pt_asset_tool.workspace_bundle_deploy as mod

    project = tmp_path / "project"; project.mkdir()
    importer = project / "pt_asset_tool" / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py"
    importer.parent.mkdir(parents=True); importer.write_text("# importer\n", encoding="utf-8")
    client = tmp_path / "client"; client.mkdir()
    source = client / "char/npc/Test/Test.smd"; source.parent.mkdir(parents=True); source.write_bytes(b"source")
    skeleton = source.with_suffix(".smb"); skeleton.write_bytes(b"skeleton")
    inx = source.with_suffix(".inx"); inx.write_bytes(b"inx")
    workspace = mod.blender_edit_root(project, "generic_import", "char/npc/Test/Test.smd")
    workspace.mkdir(parents=True)
    edited = workspace / "imported.blend"; edited.write_bytes(b"artist-edit")
    overlay = workspace / "texture_overlay_client"; overlay.mkdir()

    class Settings:
        project_root = project
        client_root = client
        @staticmethod
        def blender_command():
            return ["BLENDER"]

    class R:
        def resolve(self, logical, required=True):
            low = str(logical).lower()
            if low.endswith(".smb"):
                return skeleton
            if low.endswith(".inx"):
                return inx
            return source

    seen = {}
    def fake_run(cmd, log):
        seen["cmd"] = list(cmd); seen["log"] = pathlib.Path(log)
        out = pathlib.Path(cmd[cmd.index("--out") + 1])
        out.write_bytes(b"rebuilt-pristine")
        pathlib.Path(log).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(log).write_text("ok\n", encoding="utf-8")
    monkeypatch.setattr(mod, "run_logged", fake_run)

    context = {
        "lod": "default",
        "lod_selection_mode": "MODEL_GROUP_KEYS",
        "model_info_inx": {"logical": "char/npc/Test/Test.inx", "path": str(inx)},
        "skeleton_smb": {"logical": "char/npc/Test/Test.smb", "path": str(skeleton)},
    }
    asset = SimpleNamespace(primary_path="char/npc/Test/Test.smd")
    result = mod._ensure_pristine_rigid_blend(Settings(), R(), asset, workspace, context, tmp_path / "evidence")

    assert result["status"] == "PASS"
    assert result["rebuilt"] is True
    assert result["source"] == "REBUILT_FROM_VERIFIED_SOURCE_CONTEXT"
    assert (workspace / "pristine_import.blend").read_bytes() == b"rebuilt-pristine"
    assert edited.read_bytes() == b"artist-edit"
    assert seen["cmd"][0] == "BLENDER"
    assert "--model-info" in seen["cmd"]
    assert "--lod" in seen["cmd"]
    assert str(overlay) == seen["cmd"][seen["cmd"].index("--client-root") + 1]
