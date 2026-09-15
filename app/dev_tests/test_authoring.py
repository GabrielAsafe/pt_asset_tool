from __future__ import annotations

import pathlib
import struct
from types import SimpleNamespace

from pt_asset_tool.authoring import (
    authoring_plan,
    audit_model062_authoring,
    verify_workspace_manifest,
    write_workspace_manifest,
)
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import Asset, AssetRegistry
from pt_asset_tool.resolver import ClientResolver

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"


def _static_smd(path: pathlib.Path, *, local_keys=False, multilayer=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    SH, SI, SO, SV, SF, ST = 556, 40, 2236, 24, 36, 32
    start = SH + SI
    nv, nf = 3, 1
    nt = 2 if multilayer else 1
    nr = 1 if local_keys else 0
    SR, SM = 20, 64
    length = SO + nv * SV + nf * SF + nt * ST + nr * SR + nr * SM
    b = bytearray(start + length)
    b[:23] = b"SMD Model data Ver 0.62"
    struct.pack_into("<i", b, 24, 1)
    struct.pack_into("<i", b, 28, 0)
    struct.pack_into("<i", b, 32, start)
    struct.pack_into("<i", b, 36, start)
    b[SH:SH+4] = b"obj\0"
    struct.pack_into("<i", b, SH + 32, length)
    struct.pack_into("<i", b, SH + 36, start)
    raw = start
    texbase = 0x100000
    struct.pack_into("<I", b, raw + 12, texbase)
    struct.pack_into("<I", b, raw + 16, 0)
    struct.pack_into("<iii", b, raw + 84, nv, nf, nt)
    b[raw+172:raw+176] = b"obj\0"
    struct.pack_into("<iii", b, raw + 684, nr, 0, 0)
    vo = raw + SO
    for i, xyz in enumerate(((0,0,0),(256,0,0),(0,256,0))):
        struct.pack_into("<6i", b, vo + i*SV, *(xyz + (0,0,256)))
    fo = vo + nv*SV
    struct.pack_into("<4H", b, fo, 0,1,2,0)
    struct.pack_into("<I", b, fo + 32, texbase)
    to = fo + SF
    # First layer UVs, optional pointer to second layer.
    struct.pack_into("<3f", b, to, 0.0,1.0,0.0)
    struct.pack_into("<3f", b, to+12, 0.0,0.0,1.0)
    struct.pack_into("<I", b, to+28, texbase + ST if multilayer else 0)
    if multilayer:
        struct.pack_into("<3f", b, to+ST, 0.0,1.0,0.0)
        struct.pack_into("<3f", b, to+ST+12, 0.0,0.0,1.0)
        struct.pack_into("<I", b, to+ST+28, 0)
    path.write_bytes(b)
    return path


def _asset_static(path="char/test/static.smd"):
    return Asset(
        asset_id="AST-STATIC", primary_path=path, basename="static.smd", extension=".smd",
        category="CHARACTER", family="SMD_MODEL_062_STATIC", kind="SMD_MODEL_062",
        compatibility_tier="TEST", size=1, issues=[], configs=[], motions=[],
        source_record={"object_count":1,"physique_objects":0},
    )


def test_static_authoring_preflight_distinguishes_writer_contract(tmp_path):
    src = _static_smd(tmp_path / "static.smd")
    plan = authoring_plan(_asset_static(), src)
    geometry = plan["channels"]["geometry"]
    assert geometry["maturity"] == "CANDIDATE_PER_OBJECT"
    assert geometry["eligible_objects"] == ["obj"]
    assert plan["generic_build_authorized"] is False
    assert plan["client_write_authorized"] is False
    assert "STATIC_SAVED_BLENDER_WRITER_NOT_PRODUCTION_PROMOTED" in plan["blockers"]


def test_static_authoring_preflight_blocks_local_animation_and_multilayer(tmp_path):
    src = _static_smd(tmp_path / "complex.smd", local_keys=True, multilayer=True)
    plan = authoring_plan(_asset_static(), src)
    assert plan["channels"]["geometry"]["maturity"] == "BLOCKED_BY_SOURCE_FEATURES"
    assert "OBJECT_LOCAL_ROT_POS_SCALE_WRITER_CANDIDATE_NOT_PRODUCTION_PROMOTED" in plan["blockers"]
    assert "OBJECT_LOCAL_ROTATION_WRITER_NOT_IMPLEMENTED" not in plan["blockers"]
    assert "MULTILAYER_TEXLINK_REQUIRES_SPECIALIZED_WRITER" in plan["blockers"]


def test_authoring_workspace_manifest_detects_source_and_dependency_drift(tmp_path):
    src = tmp_path / "source.smd"; src.write_bytes(b"source-v1")
    dep = tmp_path / "motion.inx"; dep.write_bytes(b"dep-v1")
    workspace = tmp_path / "pt_build" / "blender_edits" / "generic_import" / "x"
    workspace.mkdir(parents=True)
    asset = _asset_static()
    plan = {"generic_build_authorized": False}
    manifest = write_workspace_manifest(workspace, asset, src, plan, [dep])
    assert verify_workspace_manifest(manifest)["status"] == "PASS"
    dep.write_bytes(b"dep-v2")
    broken = verify_workspace_manifest(manifest)
    assert broken["status"] == "FAIL"
    assert "DEPENDENCY_DRIFT" in broken["errors"]
    assert broken["client_write_authorized"] is False


def test_fixture_rigid_authoring_reports_explicit_candidate_contract():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    asset = registry.resolve("char/monster/Acero/Acero.smd")
    plan = authoring_plan(asset, resolver.resolve(asset.primary_path))
    assert plan["channels"]["geometry"]["maturity"] == "CANDIDATE_PER_OBJECT"
    assert plan["channels"]["geometry"]["eligible_objects"] == ["Acero"]
    assert plan["channels"]["saved_blender_build"]["maturity"] == "CANDIDATE_NOT_PROMOTED"
    assert plan["channels"]["saved_blender_build"]["writer"] == "pt_blender_to_smd_free_mesh_v3.py"
    assert "GENERIC_RIGID_SAVED_BLENDER_WRITER_NOT_PRODUCTION_PROMOTED" in plan["blockers"]
    assert plan["client_write_authorized"] is False


def test_model062_authoring_audit_is_read_only_on_fixture_client():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    report = audit_model062_authoring(registry, resolver, sample_limit=3)
    assert report["status"] == "PASS"
    assert report["assets_audited"] >= 1
    assert report["client_modified"] is False
    assert report["policy"]["candidate_does_not_imply_production_authorization"] is True
    assert report["candidate_asset_count"] >= 1
    assert report["candidate_object_count"] >= report["candidate_asset_count"]
    assert any(row["candidate_objects"] for row in report["samples"])


def test_static_candidate_requires_imported_workspace_and_manifest(tmp_path):
    from pt_asset_tool.static_authoring_candidate import plan_static_saved_blender_candidate
    src = _static_smd(tmp_path / "client" / "static.smd")
    class Resolver:
        def resolve(self, logical, required=True): return src
    asset = _asset_static()
    plan = plan_static_saved_blender_candidate(tmp_path, Resolver(), asset)
    assert plan["status"] == "BLOCKED"
    assert "GENERIC_IMPORT_WORKSPACE_MISSING" in plan["blockers"]
    assert "AUTHORING_MANIFEST_MISSING" in plan["blockers"]
    assert plan["client_write_authorized"] is False


def test_static_candidate_plan_ready_only_with_verified_workspace(tmp_path):
    from pt_asset_tool.static_authoring_candidate import plan_static_saved_blender_candidate
    from pt_asset_tool.blender_workspace import blender_edit_root
    src = _static_smd(tmp_path / "client" / "static.smd")
    class Resolver:
        def resolve(self, logical, required=True): return src
    asset = _asset_static()
    workspace = blender_edit_root(tmp_path, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True)
    (workspace / "imported.blend").write_bytes(b"blend")
    plan = authoring_plan(asset, src)
    write_workspace_manifest(workspace, asset, src, plan, [])
    candidate = plan_static_saved_blender_candidate(tmp_path, Resolver(), asset)
    assert candidate["status"] == "READY"
    assert candidate["object"] == "obj"
    assert pathlib.Path(candidate["output"]).is_relative_to(tmp_path / "pt_build")
    assert candidate["production_authorized"] is False


def test_static_candidate_output_verifier_accepts_noop_container(tmp_path):
    from pt_asset_tool.static_authoring_candidate import validate_static_candidate_output
    src = _static_smd(tmp_path / "source.smd")
    out = tmp_path / "out.smd"; out.write_bytes(src.read_bytes())
    result = validate_static_candidate_output(src, out, "obj")
    assert result["status"] == "PASS"
    assert result["target"]["target_block_byte_identical"] is True
    assert result["edit_observed"] is False
    assert result["production_authorized"] is False


def test_static_candidate_blender_command_is_background_and_hash_pinned(tmp_path):
    from pt_asset_tool.static_authoring_candidate import build_static_candidate_blender_command
    writer = tmp_path / "pt_blender_to_smd_static_v1.py"; writer.write_text("# writer")
    blend = tmp_path / "edit.blend"; blend.write_bytes(b"blend")
    source = tmp_path / "source.smd"; source.write_bytes(b"src")
    output = tmp_path / "pt_build" / "out.smd"
    candidate = {
        "status":"READY", "blockers":[], "blend":str(blend), "source":str(source),
        "object":"obj", "output":str(output), "source_sha256":"abc123",
    }
    settings = SimpleNamespace(project_root=tmp_path, blender_command=lambda:["blender-test"])
    cmd = build_static_candidate_blender_command(settings, candidate, report=tmp_path/"report.json")
    assert cmd[0] == "blender-test"
    assert "--background" in cmd and "--python-exit-code" in cmd
    assert str(writer.resolve()) in cmd
    assert cmd[cmd.index("--expected-source-sha256")+1] == "abc123"


def test_rigid_candidate_plan_and_noop_verifier_on_acero(tmp_path):
    from pt_asset_tool.rigid_authoring_candidate import (
        plan_rigid_saved_blender_candidate,
        validate_rigid_candidate_output,
        build_rigid_candidate_blender_command,
    )
    from pt_asset_tool.blender_workspace import blender_edit_root
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    asset = registry.resolve("char/monster/Acero/Acero.smd")
    src = resolver.resolve(asset.primary_path)
    skel = resolver.resolve(asset.binding_skeleton_smb)
    workspace = blender_edit_root(tmp_path, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True)
    blend = workspace / "imported.blend"; blend.write_bytes(b"blend")
    plan = authoring_plan(asset, src)
    write_workspace_manifest(workspace, asset, src, plan, [skel])

    class TmpResolver:
        def resolve(self, logical, required=True):
            if logical == asset.primary_path: return src
            if logical == asset.binding_skeleton_smb: return skel
            return resolver.resolve(logical, required=required)

    candidate = plan_rigid_saved_blender_candidate(tmp_path, TmpResolver(), asset)
    assert candidate["status"] == "READY"
    assert candidate["object"] == "Acero"
    writer = tmp_path / "pt_blender_to_smd_free_mesh_v3.py"; writer.write_text("# writer")
    fake_settings = SimpleNamespace(project_root=tmp_path, blender_command=lambda:["blender-test"])
    cmd = build_rigid_candidate_blender_command(fake_settings, candidate, report=tmp_path/"report.json")
    assert "--skeleton" in cmd and str(skel.resolve()) in cmd
    out = tmp_path / "out.smd"; out.write_bytes(src.read_bytes())
    verify = validate_rigid_candidate_output(ROOT, src, out, skel, "Acero")
    assert verify["status"] == "PASS"
    assert verify["target"]["unique_physique_bones"]
    assert verify["unknown_physique_bones"] == []
    assert verify["edit_observed"] is False
    assert verify["production_authorized"] is False


def test_rigid_workspace_selected_context_is_identity_bound_and_fail_closed(tmp_path):
    from pt_asset_tool.authoring import (
        build_selected_authoring_context,
        verify_selected_context_for_asset,
    )
    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    inx = tmp_path / "client" / "body-a.inx"; inx.write_bytes(b"inx-a")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    asset = SimpleNamespace(
        asset_id="AST-RIGID", primary_path="char/test/body.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062",
        binding_skeleton_smb="char/test/body.smb",
        configs=[{
            "inx":"char/test/body-a.inx", "motion_smb":"char/test/body.smb",
            "lod_groups":{"high":["BodyHi"], "default":["Body"], "low":[]},
        }],
    )
    context = build_selected_authoring_context(
        model_info_logical="char/test/body-a.inx", model_info_path=inx,
        skeleton_logical="char/test/body.smb", skeleton_path=smb,
        lod="default", lod_groups=asset.configs[0]["lod_groups"],
    )
    workspace = tmp_path / "workspace"; workspace.mkdir()
    manifest = write_workspace_manifest(
        workspace, asset, source, {"generic_build_authorized":False}, [inx, smb],
        selected_context=context,
    )
    verified = verify_workspace_manifest(manifest)
    assert verified["status"] == "PASS"
    assert verified["selected_context"]["model_info_inx"]["logical"] == "char/test/body-a.inx"

    class Resolver:
        def resolve(self, logical, required=True):
            return {
                "char/test/body-a.inx": inx,
                "char/test/body.smb": smb,
            }[str(logical).replace("\\", "/")]
    asset_verified = verify_selected_context_for_asset(context, asset, Resolver())
    assert asset_verified["status"] == "PASS"

    asset.configs[0]["lod_groups"]["default"] = ["DifferentBody"]
    drift = verify_selected_context_for_asset(context, asset, Resolver())
    assert drift["status"] == "FAIL"
    assert "LOD_GROUPS_REGISTRY_DRIFT" in drift["errors"]

    inx.write_bytes(b"inx-b")
    manifest_drift = verify_workspace_manifest(manifest)
    assert manifest_drift["status"] == "FAIL"
    assert "SELECTED_CONTEXT_DRIFT" in manifest_drift["errors"]


def test_rigid_workspace_without_selected_context_is_not_build_provenance_ready(tmp_path):
    source = tmp_path / "body.smd"; source.write_bytes(b"smd")
    asset = SimpleNamespace(
        asset_id="AST-RIGID", primary_path="char/test/body.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062",
    )
    workspace = tmp_path / "workspace"; workspace.mkdir()
    manifest = write_workspace_manifest(workspace, asset, source, {"generic_build_authorized":False}, [])
    verified = verify_workspace_manifest(manifest)
    assert verified["status"] == "FAIL"
    assert "SELECTED_CONTEXT_MISSING" in verified["errors"]


def test_rigid_candidate_plan_uses_manifest_selected_context_and_blocks_registry_drift(monkeypatch, tmp_path):
    import pt_asset_tool.rigid_authoring_candidate as rigid_candidate_mod
    from pt_asset_tool.authoring import build_selected_authoring_context
    from pt_asset_tool.blender_workspace import blender_edit_root

    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    inx = tmp_path / "client" / "body.inx"; inx.write_bytes(b"inx")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    asset = SimpleNamespace(
        asset_id="AST-RIGID", primary_path="char/test/body.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062",
        rigid_binding_ready=True, binding_mode="ROOT_SKELETON_BOUND", binding_source="TEST",
        binding_skeleton_smb="char/test/body.smb",
        configs=[{
            "inx":"char/test/body.inx", "motion_smb":"char/test/body.smb",
            "lod_groups":{"default":["Body"]},
        }],
    )
    context = build_selected_authoring_context(
        model_info_logical="char/test/body.inx", model_info_path=inx,
        skeleton_logical="char/test/body.smb", skeleton_path=smb,
        lod="default", lod_groups=asset.configs[0]["lod_groups"],
    )
    workspace = blender_edit_root(tmp_path, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True)
    (workspace / "imported.blend").write_bytes(b"blend")
    write_workspace_manifest(
        workspace, asset, source, {"generic_build_authorized":False}, [inx, smb],
        selected_context=context,
    )

    class Resolver:
        def resolve(self, logical, required=True):
            logical=str(logical).replace("\\", "/")
            return {
                "char/test/body.smd":source,
                "char/test/body.inx":inx,
                "char/test/body.smb":smb,
            }[logical]

    monkeypatch.setattr(rigid_candidate_mod, "authoring_plan", lambda asset, source: {
        "source_analysis": {"sha256":"source-sha", "objects":[{
            "name":"Body", "physique":True, "has_object_local_animation":False,
            "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1,
        }]},
    })
    ready = rigid_candidate_mod.plan_rigid_saved_blender_candidate(tmp_path, Resolver(), asset)
    assert ready["status"] == "READY"
    assert ready["skeleton"] == str(smb.resolve())
    assert ready["skeleton_logical"] == "char/test/body.smb"
    assert ready["selected_context"]["model_info_inx"]["logical"] == "char/test/body.inx"

    asset.configs[0]["lod_groups"]["default"] = ["DifferentBody"]
    blocked = rigid_candidate_mod.plan_rigid_saved_blender_candidate(tmp_path, Resolver(), asset)
    assert blocked["status"] == "BLOCKED"
    assert "RIGID_SELECTED_CONTEXT_MISMATCH" in blocked["blockers"]


def test_rigid_candidate_is_scoped_to_saved_selected_lod(monkeypatch, tmp_path):
    import pt_asset_tool.rigid_authoring_candidate as rigid_candidate_mod
    from pt_asset_tool.authoring import build_selected_authoring_context
    from pt_asset_tool.blender_workspace import blender_edit_root

    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    inx = tmp_path / "client" / "body.inx"; inx.write_bytes(b"inx")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    asset = SimpleNamespace(
        asset_id="AST-RIGID-LOD", primary_path="char/test/body.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062",
        rigid_binding_ready=True, binding_mode="ROOT_SKELETON_BOUND", binding_source="TEST",
        binding_skeleton_smb="char/test/body.smb",
        configs=[{
            "inx":"char/test/body.inx", "motion_smb":"char/test/body.smb",
            "lod_groups":{"high":["BodyHi"], "default":["BodyA", "BodyB"], "low":["BodyLow"]},
        }],
    )
    context = build_selected_authoring_context(
        model_info_logical="char/test/body.inx", model_info_path=inx,
        skeleton_logical="char/test/body.smb", skeleton_path=smb,
        lod="default", lod_groups=asset.configs[0]["lod_groups"],
    )
    workspace = blender_edit_root(tmp_path, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True)
    (workspace / "imported.blend").write_bytes(b"blend")
    write_workspace_manifest(
        workspace, asset, source, {"generic_build_authorized":False}, [inx, smb],
        selected_context=context,
    )

    class Resolver:
        def resolve(self, logical, required=True):
            logical=str(logical).replace("\\", "/")
            return {
                "char/test/body.smd":source,
                "char/test/body.inx":inx,
                "char/test/body.smb":smb,
            }[logical]

    monkeypatch.setattr(rigid_candidate_mod, "authoring_plan", lambda asset, source: {
        "source_analysis": {"sha256":"source-sha", "objects":[
            {"name":"BodyA", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
            {"name":"BodyB", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
            {"name":"BodyHi", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
            {"name":"OtherVariant", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
        ]},
    })

    candidate = rigid_candidate_mod.plan_rigid_saved_blender_candidate(
        tmp_path, Resolver(), asset, object_name="BodyA"
    )
    assert candidate["status"] == "READY"
    assert candidate["eligible_objects"] == ["BodyA", "BodyB"]
    assert candidate["selected_lod_nodes"] == ["BodyA", "BodyB"]
    assert candidate["source_contract_eligible_objects"] == ["BodyA", "BodyB", "BodyHi", "OtherVariant"]

    try:
        rigid_candidate_mod.plan_rigid_saved_blender_candidate(
            tmp_path, Resolver(), asset, object_name="OtherVariant"
        )
    except RuntimeError as exc:
        assert "saved rigid LOD context" in str(exc)
        assert "BodyA" in str(exc) and "BodyB" in str(exc)
    else:
        raise AssertionError("out-of-context rigid object must be rejected")


def test_rigid_candidate_scope_reports_only_saved_lod_nodes():
    from pt_asset_tool.rigid_authoring_candidate import inspect_rigid_candidate_scope

    plan = {"source_analysis": {"objects": [
        {"name":"DefaultA", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
        {"name":"DefaultB", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
        {"name":"HighA", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
    ]}}
    context = {"lod":"default", "selected_lod_nodes":["DefaultA", "DefaultB"]}
    scope = inspect_rigid_candidate_scope(plan, context)
    assert scope["eligible_objects"] == ["DefaultA", "DefaultB"]
    assert scope["source_contract_eligible_objects"] == ["DefaultA", "DefaultB", "HighA"]
    assert scope["selection_required"] is True
    assert scope["scope_complete"] is True


def test_rigid_candidate_scope_allows_partial_lod_when_target_is_eligible():
    from pt_asset_tool.rigid_authoring_candidate import inspect_rigid_candidate_scope

    plan = {"source_analysis": {"objects": [
        {"name":"Editable", "physique":True, "has_object_local_animation":False, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
        {"name":"NotEditable", "physique":True, "has_object_local_animation":True, "faces":1, "vertices":3, "texlink_min_layers":1, "texlink_max_layers":1},
    ]}}
    context = {"lod":"default", "selected_lod_nodes":["Editable", "NotEditable"]}
    scope = inspect_rigid_candidate_scope(plan, context)
    assert scope["eligible_objects"] == ["Editable"]
    assert scope["selected_lod_ineligible_objects"] == ["NotEditable"]
    assert scope["scope_complete"] is False
    assert scope["selection_required"] is False


def test_standalone_rigid_context_binds_asset_and_skeleton_without_model_info(tmp_path):
    from pt_asset_tool.authoring import (
        build_standalone_rigid_authoring_context,
        verify_selected_context_for_asset,
        verify_selected_authoring_context,
    )
    source = tmp_path / "client" / "piece.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    smb = tmp_path / "client" / "class.smb"; smb.write_bytes(b"smb")
    report = tmp_path / "structural.json"; report.write_text('{"status":"PASS"}')
    asset = SimpleNamespace(
        asset_id="AST-STANDALONE", primary_path="char/test/piece.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062", configs=[],
    )
    context = build_standalone_rigid_authoring_context(
        asset_logical=asset.primary_path, source_path=source,
        skeleton_logical="char/test/class.smb", skeleton_path=smb,
        selected_nodes=["Piece"], structural_gate_report=report,
    )
    assert context["model_info_inx"] is None
    assert context["lod"] == "standalone"
    assert context["selected_lod_nodes"] == ["Piece"]
    assert verify_selected_authoring_context(context)["status"] == "PASS"

    class Resolver:
        def resolve(self, logical, required=True):
            return {"char/test/class.smb": smb}[str(logical).replace("\\", "/")]
    result = verify_selected_context_for_asset(context, asset, Resolver())
    assert result["status"] == "PASS"

    smb.write_bytes(b"changed")
    drift = verify_selected_authoring_context(context)
    assert drift["status"] == "FAIL"
    assert "SKELETON_SIZE_DRIFT" in drift["errors"] or "SKELETON_SHA_DRIFT" in drift["errors"]


def test_standalone_rigid_context_requires_structural_gate_and_target_identity(tmp_path):
    from pt_asset_tool.authoring import build_standalone_rigid_authoring_context, verify_selected_context_for_asset
    source = tmp_path / "piece.smd"; source.write_bytes(b"smd")
    smb = tmp_path / "class.smb"; smb.write_bytes(b"smb")
    asset = SimpleNamespace(
        asset_id="AST-STANDALONE", primary_path="char/test/piece.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062", configs=[],
    )
    context = build_standalone_rigid_authoring_context(
        asset_logical=asset.primary_path, source_path=source,
        skeleton_logical="char/test/class.smb", skeleton_path=smb,
        selected_nodes=["Piece"],
        selection_basis={"kind":"EXPLICIT_SKELETON", "roundtrip_target":"char/test/other.smd", "structural_gate":"PASS"},
    )
    result = verify_selected_context_for_asset(context, asset)
    assert result["status"] == "FAIL"
    assert "SELECTION_BASIS_TARGET_MISMATCH" in result["errors"]


def test_rigid_candidate_accepts_verified_standalone_skeleton_context(monkeypatch, tmp_path):
    import pt_asset_tool.rigid_authoring_candidate as mod
    from pt_asset_tool.authoring import build_standalone_rigid_authoring_context
    from pt_asset_tool.blender_workspace import blender_edit_root

    source = tmp_path / "client" / "piece.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    smb = tmp_path / "client" / "class.smb"; smb.write_bytes(b"smb")
    structural = tmp_path / "structural.json"; structural.write_text('{"status":"PASS"}')
    asset = SimpleNamespace(
        asset_id="AST-STANDALONE-CAND", primary_path="char/test/piece.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062",
        rigid_binding_ready=False, binding_mode="UNRESOLVED", binding_source="NONE",
        binding_skeleton_smb="", configs=[],
    )
    context = build_standalone_rigid_authoring_context(
        asset_logical=asset.primary_path, source_path=source,
        skeleton_logical="char/test/class.smb", skeleton_path=smb,
        selected_nodes=["Piece"], structural_gate_report=structural,
    )
    workspace = blender_edit_root(tmp_path, "generic_import", asset.primary_path)
    workspace.mkdir(parents=True); (workspace / "imported.blend").write_bytes(b"blend")
    write_workspace_manifest(workspace, asset, source, {"generic_build_authorized":False}, [smb], selected_context=context)

    class Resolver:
        def resolve(self, logical, required=True):
            return {"char/test/piece.smd":source, "char/test/class.smb":smb}[str(logical).replace("\\", "/")]

    monkeypatch.setattr(mod, "authoring_plan", lambda asset, source: {
        "source_analysis":{"sha256":"source-sha","objects":[
            {"name":"Piece","physique":True,"has_object_local_animation":False,"faces":1,"vertices":3,"texlink_min_layers":1,"texlink_max_layers":1}
        ]}
    })
    candidate = mod.plan_rigid_saved_blender_candidate(tmp_path, Resolver(), asset)
    assert candidate["status"] == "READY"
    assert candidate["skeleton"] == str(smb.resolve())
    assert candidate["selected_context"]["format"] == "PT_ASSET_STANDALONE_RIGID_CONTEXT_V1"
    assert candidate["eligible_objects"] == ["Piece"]


def test_explicit_skeleton_lod_context_verifies_config_without_motion_smb(tmp_path):
    from types import SimpleNamespace
    from pt_asset_tool.authoring import build_selected_authoring_context, verify_selected_context_for_asset
    inx=tmp_path/'equip.inx'; inx.write_bytes(b'inx')
    smb=tmp_path/'m4.smb'; smb.write_bytes(b'smb')
    asset=SimpleNamespace(
        asset_id='AST-EQUIP', primary_path='char/tmABCD/equip.smd',
        family='SMD_MODEL_062_RIGID_PHYSIQUE', kind='SMD_MODEL_062',
        binding_skeleton_smb='',
        configs=[{'inx':'char/tmABCD/equip.inx','motion_smb':'','lod_groups':{'high':['PartH'],'default':[],'low':[]}}],
    )
    context=build_selected_authoring_context(
        model_info_logical='char/tmABCD/equip.inx', model_info_path=inx,
        skeleton_logical='char/tmABCD/m4.smb', skeleton_path=smb,
        lod='high', lod_groups=asset.configs[0]['lod_groups'],
        selection_basis={
            'kind':'EXPLICIT_SKELETON_LOD','roundtrip_target':asset.primary_path,'structural_gate':'PASS',
        },
    )
    class Resolver:
        def resolve(self, logical, required=True):
            return {'char/tmABCD/equip.inx':inx,'char/tmABCD/m4.smb':smb}[str(logical).replace('\\','/')]
    result=verify_selected_context_for_asset(context,asset,Resolver())
    assert result['status']=='PASS', result


def test_explicit_skeleton_lod_context_without_binding_requires_structural_basis(tmp_path):
    from types import SimpleNamespace
    from pt_asset_tool.authoring import build_selected_authoring_context, verify_selected_context_for_asset
    inx=tmp_path/'equip.inx'; inx.write_bytes(b'inx')
    smb=tmp_path/'m4.smb'; smb.write_bytes(b'smb')
    asset=SimpleNamespace(
        asset_id='AST-EQUIP', primary_path='char/tmABCD/equip.smd',
        family='SMD_MODEL_062_RIGID_PHYSIQUE', kind='SMD_MODEL_062',
        binding_skeleton_smb='',
        configs=[{'inx':'char/tmABCD/equip.inx','motion_smb':'','lod_groups':{'high':['PartH'],'default':[],'low':[]}}],
    )
    context=build_selected_authoring_context(
        model_info_logical='char/tmABCD/equip.inx', model_info_path=inx,
        skeleton_logical='char/tmABCD/m4.smb', skeleton_path=smb,
        lod='high', lod_groups=asset.configs[0]['lod_groups'], selection_basis=None,
    )
    class Resolver:
        def resolve(self, logical, required=True):
            return {'char/tmABCD/equip.inx':inx,'char/tmABCD/m4.smb':smb}[str(logical).replace('\\','/')]
    result=verify_selected_context_for_asset(context,asset,Resolver())
    assert result['status']=='FAIL'
    assert 'SKELETON_NOT_PROVEN_BY_CONFIG_OR_EXPLICIT_STRUCTURAL_GATE' in result['errors']


def test_explicit_skeleton_lod_context_rejects_structural_basis_without_pass(tmp_path):
    from pt_asset_tool.authoring import build_selected_authoring_context, verify_selected_authoring_context
    inx=tmp_path/'equip.inx'; inx.write_bytes(b'inx')
    smb=tmp_path/'m4.smb'; smb.write_bytes(b'smb')
    context=build_selected_authoring_context(
        model_info_logical='char/tmABCD/equip.inx', model_info_path=inx,
        skeleton_logical='char/tmABCD/m4.smb', skeleton_path=smb,
        lod='high', lod_groups={'high':['PartH'],'default':[],'low':[]},
        selection_basis={
            'kind':'EXPLICIT_SKELETON_LOD','roundtrip_target':'char/tmABCD/equip.smd','structural_gate':'FAIL',
        },
    )
    result=verify_selected_authoring_context(context)
    assert result['status']=='FAIL'
    assert 'STRUCTURAL_GATE_NOT_PROVEN' in result['errors']
