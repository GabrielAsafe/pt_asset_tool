from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_geometry import _invert_matrix_source, _parse_skeleton_tms, _transform_point_fixed
from .rare_rigid_multibone_bridge import TARGET, _combo, SOURCE_NORMAL_DELTA_LIMIT_FIXED
from .rare_rigid_multibone_roundtrip import patch_guarded_multibone, compare_guarded_multibone
from .rare_rigid_multivertex import (
    MAX_TRANSACTION_VERTICES,
    MIN_TRANSACTION_VERTICES,
    compare_guarded_multivertex,
    discover_transaction_representatives,
    discover_uniform_translation_pair,
    patch_guarded_multivertex,
    plan_requested_at_dragon_transaction,
)
from .rare_rigid_normal_bridge import (
    NORMAL_TARGET_REIMPORT_LIMIT_FIXED,
    POSITION_REIMPORT_LIMIT_FIXED,
    _build_source_normal_state,
    _face_normal_source,
    _i32_safe,
    _updated_current_for_affected,
    _world_hist_vector,
)
from .rare_rigid_preview import _prepare_one_preview
from .rare_rigid_roundtrip import _parse_with_offsets, _stored_bound_safe
from .rare_support import prepare_model062_tooling_source
from .utils import norm_path, run_logged, sha256_file

WORKSPACE_FORMAT = "PT_RARE_RIGID_GUARDED_EDIT_WORKSPACE_V5"
WRITE_FORMAT = "PT_RARE_RIGID_GUARDED_EDIT_WRITE_V5"


def _at_dragon_binding(binding: dict[str, Any]) -> dict[str, Any]:
    rows = [r for r in binding.get("rows") or [] if norm_path(r.get("logical") or "").lower() == TARGET.lower()]
    if len(rows) != 1:
        raise RuntimeError(f"at_dragon binding row unresolved: {len(rows)}")
    row = rows[0]
    if row.get("binding_status") != "VERIFIED_INX_LINK_SKELETON" or not row.get("preview_binding_authorized"):
        raise RuntimeError("at_dragon binding is not verified")
    return row


def _world_positions_for_object(obj: dict[str, Any], bone_tms: dict[str, list[int]]) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for vi, v in enumerate(obj["vertices"]):
        bone = obj["bones"][vi]
        tm = bone_tms.get(bone)
        if tm is None:
            raise RuntimeError(f"missing bone transform {bone!r}")
        out.append(_transform_point_fixed(tuple(int(x) for x in v[:3]), tm))
    return out


def plan_requested_at_dragon_edit(
    prepared: pathlib.Path,
    skeleton: pathlib.Path,
    *,
    object_index: int,
    vertex_index: int,
    requested_world_fixed: tuple[int, int, int],
) -> dict[str, Any]:
    """Recompute the V0.8.4 guard for one exact artist-requested at_dragon vertex move."""
    model = _parse_with_offsets(prepared)
    bone_tms = _parse_skeleton_tms(skeleton)
    if not (0 <= object_index < len(model["objects"])):
        raise ValueError("object index out of bounds")
    obj = model["objects"][object_index]
    if not (0 <= vertex_index < len(obj["vertices"])):
        raise ValueError("vertex index out of bounds")

    world = _world_positions_for_object(obj, bone_tms)
    state = _build_source_normal_state(world, obj["faces"])
    vi = int(vertex_index)
    incident = list(state["incidence"][vi])
    mixed_incident = [fi for fi in incident if len(_combo(obj, obj["faces"][fi])) > 1]
    if not mixed_incident:
        raise ValueError("EDIT_OUTSIDE_V084_MULTIBONE_SCOPE")
    if state["current"][vi] is None:
        raise ValueError("SOURCE_NORMAL_STATE_UNRESOLVED")

    vertex_bone = obj["bones"][vi]
    tm = bone_tms.get(vertex_bone)
    if tm is None:
        raise ValueError("WITNESS_BONE_MISSING")
    inv = _invert_matrix_source(tm)
    oldv = obj["vertices"][vi]
    old_local = tuple(int(x) for x in oldv[:3])
    old_world = world[vi]
    requested_t = tuple(int(x) for x in requested_world_fixed)
    if requested_t == old_world:
        raise ValueError("NO_POSITION_CHANGE")
    if not _stored_bound_safe(requested_t, obj["stored_bounds"]):
        raise ValueError("EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED")

    new_local = _transform_point_fixed(requested_t, inv)
    if new_local == old_local:
        raise ValueError("EDIT_QUANTIZES_TO_ORIGINAL_LOCAL_POSITION")
    if not all(_i32_safe(q) for q in new_local):
        raise ValueError("LOCAL_POSITION_INT32_OVERFLOW")
    reimport = _transform_point_fixed(new_local, tm)
    pos_error = max(abs(reimport[z] - requested_t[z]) for z in range(3))
    if pos_error > POSITION_REIMPORT_LIMIT_FIXED:
        raise ValueError(f"POSITION_REIMPORT_ERROR_{pos_error}_GT_{POSITION_REIMPORT_LIMIT_FIXED}")
    if not _stored_bound_safe(reimport, obj["stored_bounds"]):
        raise ValueError("REIMPORTED_POSITION_REQUIRES_BOUND_CHANGE")

    world2 = list(world)
    world2[vi] = requested_t
    changed_face_normals: dict[int, tuple[int, int, int]] = {}
    affected: set[int] = set()
    for fi in incident:
        f = obj["faces"][fi]
        a, b, c = [int(x) for x in f[:3]]
        n = _face_normal_source(world2[a], world2[b], world2[c])
        if n is None:
            raise ValueError(f"FACE_{fi}_DEGENERATE_OR_INT32_OVERFLOW")
        changed_face_normals[fi] = n
        affected.update((a, b, c))
    if any(state["current"][av] is None for av in affected):
        raise ValueError("AFFECTED_SOURCE_NORMAL_STATE_UNRESOLVED")
    current2 = _updated_current_for_affected(state, obj["faces"], changed_face_normals, affected)
    if current2 is None:
        raise ValueError("AFFECTED_CURRENT_NORMAL_REBUILD_FAILED")

    affected_rows: list[dict[str, Any]] = []
    source_delta_max = 0
    target_error_max = 0
    affected_bones: set[str] = set()
    for av in sorted(affected):
        before_current = state["current"][av]
        assert before_current is not None
        after_current = current2[av]
        source_delta = tuple(after_current[z] - before_current[z] for z in range(3))
        source_delta_max = max(source_delta_max, max(abs(q) for q in source_delta))

        av_bone = obj["bones"][av]
        affected_bones.add(av_bone)
        av_tm = bone_tms.get(av_bone)
        if av_tm is None:
            raise ValueError(f"AFFECTED_BONE_MISSING_{av}")
        av_inv = _invert_matrix_source(av_tm)
        av_vertex = obj["vertices"][av]
        old_hist = _world_hist_vector(av_vertex, av_tm)
        residual = tuple(old_hist[z] - before_current[z] for z in range(3))
        target_vec = tuple(after_current[z] + residual[z] for z in range(3))
        desired_pos = requested_t if av == vi else world[av]
        target_ep_world = tuple(desired_pos[z] + target_vec[z] for z in range(3))
        local_ep = _transform_point_fixed(target_ep_world, av_inv)
        if not all(_i32_safe(q) for q in local_ep):
            raise ValueError(f"NORMAL_ENDPOINT_INT32_OVERFLOW_{av}")
        actual_ep_world = _transform_point_fixed(local_ep, av_tm)
        actual_pos_world = reimport if av == vi else world[av]
        actual_vec = tuple(actual_ep_world[z] - actual_pos_world[z] for z in range(3))
        target_error = max(abs(actual_vec[z] - target_vec[z]) for z in range(3))
        target_error_max = max(target_error_max, target_error)
        affected_rows.append({
            "vertex_index": av,
            "bone": av_bone,
            "is_position_witness": av == vi,
            "before_local_position_fixed": list(int(x) for x in av_vertex[:3]),
            "after_local_position_fixed": list(new_local if av == vi else tuple(int(x) for x in av_vertex[:3])),
            "before_local_normal_endpoint_fixed": list(int(x) for x in av_vertex[3:6]),
            "after_local_normal_endpoint_fixed": list(local_ep),
            "before_world_position_fixed": list(world[av]),
            "desired_world_position_fixed": list(desired_pos),
            "expected_reimport_world_position_fixed": list(reimport if av == vi else world[av]),
            "before_current_source_normal_fixed": list(before_current),
            "after_current_source_normal_fixed": list(after_current),
            "current_source_normal_delta_fixed": list(source_delta),
            "before_historical_world_normal_fixed": list(old_hist),
            "historical_residual_vs_current_source_fixed": list(residual),
            "target_historical_world_normal_fixed": list(target_vec),
            "actual_reimport_world_normal_fixed": list(actual_vec),
            "target_reimport_error_fixed": target_error,
        })

    if len(affected_bones) < 2:
        raise ValueError("EDIT_DOES_NOT_AFFECT_MULTIBONE_NEIGHBORHOOD")
    if source_delta_max == 0:
        raise ValueError("SOURCE_NORMAL_DELTA_ZERO")
    if source_delta_max > SOURCE_NORMAL_DELTA_LIMIT_FIXED:
        raise ValueError(f"SOURCE_NORMAL_DELTA_{source_delta_max}_GT_{SOURCE_NORMAL_DELTA_LIMIT_FIXED}")
    if target_error_max > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
        raise ValueError(f"NORMAL_REIMPORT_ERROR_{target_error_max}_GT_{NORMAL_TARGET_REIMPORT_LIMIT_FIXED}")

    mixed_combos = sorted({_combo(obj, obj["faces"][fi]) for fi in mixed_incident}, key=lambda x: tuple(s.lower() for s in x))
    return {
        "logical": TARGET,
        "object_index": int(obj["index"]),
        "table_name": obj["table_name"],
        "head_name": obj["head_name"],
        "vertex_index": vi,
        "bone": vertex_bone,
        "before_world_fixed": list(old_world),
        "requested_after_world_fixed": list(requested_t),
        "expected_reimport_world_fixed": list(reimport),
        "requested_reimport_error_fixed": pos_error,
        "before_local_fixed": list(old_local),
        "after_local_fixed": list(new_local),
        "local_delta_fixed": [new_local[z] - old_local[z] for z in range(3)],
        "incident_face_indices": [int(x) for x in incident],
        "mixed_incident_face_indices": [int(x) for x in mixed_incident],
        "incident_face_count": len(incident),
        "mixed_incident_face_count": len(mixed_incident),
        "mixed_incident_bone_combinations": [list(x) for x in mixed_combos],
        "affected_vertex_count": len(affected),
        "affected_bone_count": len(affected_bones),
        "affected_bones": sorted(affected_bones, key=str.lower),
        "affected_vertices": affected_rows,
        "max_current_source_normal_delta_fixed": source_delta_max,
        "max_target_reimport_normal_error_fixed": target_error_max,
        "normal_policy": "PER_VERTEX_BONE_HISTORICAL_RESIDUAL_PLUS_CURRENT_SOURCE_SETGNORMALS_DELTA",
        "bounds_header_policy": "PRESERVE_BYTE_IDENTICAL_INTERIOR_WITNESS",
        "guard_status": "PASS",
    }


def _workspace_root(project_root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(project_root) / "pt_build" / "rare_rigid_edit_v089" / "at_dragon.smd"


def prepare_at_dragon_edit_workspace(
    reg,
    resolver,
    certifications,
    settings,
    *,
    project_root: pathlib.Path,
    open_gui: bool,
    reset: bool = False,
    workspace_root: pathlib.Path | None = None,
    workspace_origin: str = "USER",
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root)
    work = pathlib.Path(workspace_root) if workspace_root is not None else _workspace_root(project_root)
    if reset and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    existing_manifest = work / "workspace_manifest.json"
    if not reset and existing_manifest.is_file():
        manifest = json.loads(existing_manifest.read_text(encoding="utf-8"))
        edit_blend = pathlib.Path(manifest.get("edit_blend") or "")
        source_now = pathlib.Path(resolver.resolve(TARGET, required=True))
        if manifest.get("format") != WORKSPACE_FORMAT or manifest.get("logical") != TARGET:
            # A previous-version workspace is never resumed implicitly.  The physical
            # source remains read-only; only the disposable pt_build workspace is reset.
            shutil.rmtree(work)
            work.mkdir(parents=True, exist_ok=True)
            existing_manifest = work / "workspace_manifest.json"
        elif manifest.get("workspace_origin") != workspace_origin:
            raise RuntimeError("edit workspace origin mismatch; rerun with --reset")
        else:
            edit_blend = pathlib.Path(manifest.get("edit_blend") or "")
            source_now = pathlib.Path(resolver.resolve(TARGET, required=True))
            if not edit_blend.is_file():
                raise RuntimeError("existing edit workspace blend is missing; rerun with --reset")
            if sha256_file(source_now) != manifest.get("source_sha256"):
                raise RuntimeError("physical at_dragon changed since workspace creation; rerun with --reset")
            if open_gui:
                viewer = project_root / "pt_asset_tool/blender/open_rare_rigid_edit.py"
                run_logged(
                    settings.blender_command() + [str(edit_blend), "--python", str(viewer), "--", "--manifest", str(existing_manifest)],
                    work / "04_edit_gui.log",
                )
            return manifest
    binding = audit_rare_rigid_binding(reg, resolver, project_root=project_root, work=work / "binding_recheck", bundle=None)
    if binding.get("status") != "PASS" or not binding.get("preview_integration_authorized"):
        raise RuntimeError("binding recheck failed")
    _at_dragon_binding(binding)

    preview = _prepare_one_preview(
        reg=reg,
        resolver=resolver,
        certifications=certifications,
        settings=settings,
        project_root=project_root,
        binding=binding,
        logical=TARGET,
        work=work / "base_preview",
        open_gui=False,
    )
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    prepared = work / "base_preview" / "prepared" / pathlib.PurePosixPath(TARGET)
    skeleton = pathlib.Path(resolver.resolve(preview["motion_smb"], required=True))
    edit_blend = work / "at_dragon_guarded_edit.blend"
    baseline_report = work / "edit_baseline_blender.json"
    prep_script = project_root / "pt_asset_tool/blender/prepare_rare_rigid_edit.py"
    run_logged(
        settings.blender_command() + [
            "--background", str(preview["preview_blend"]), "--python-exit-code", "1",
            "--python", str(prep_script), "--",
            "--out", str(edit_blend), "--report", str(baseline_report), "--logical", TARGET,
        ],
        work / "03_prepare_edit_workspace.log",
    )
    # V0.8.9 keeps the V0.8.8 persisted-baseline rule: the authoritative baseline is NEVER the in-memory state that existed
    # before the first .blend serialization. Canonicalize a reopen/save cycle, capture
    # the persisted state, then prove that a second save/reopen is a no-op.
    canonicalize_script = project_root / "pt_asset_tool/blender/canonicalize_rare_rigid_edit.py"
    capture_script = project_root / "pt_asset_tool/blender/capture_rare_rigid_edit_baseline.py"
    extract_script = project_root / "pt_asset_tool/blender/extract_rare_rigid_edit.py"
    run_logged(
        settings.blender_command() + ["--background", str(edit_blend), "--python-exit-code", "1", "--python", str(canonicalize_script)],
        work / "03a_canonicalize_persisted_blend.log",
    )
    run_logged(
        settings.blender_command() + ["--background", str(edit_blend), "--python-exit-code", "1", "--python", str(capture_script), "--", "--report", str(baseline_report), "--logical", TARGET],
        work / "03b_capture_persisted_baseline.log",
    )
    baseline = json.loads(baseline_report.read_text(encoding="utf-8"))
    if baseline.get("check") != "PASS" or baseline.get("baseline_source") != "PERSISTED_BLEND_REOPENED_OBJECT_MODE":
        raise RuntimeError(f"persisted edit baseline capture failed: {baseline}")
    run_logged(
        settings.blender_command() + ["--background", str(edit_blend), "--python-exit-code", "1", "--python", str(canonicalize_script)],
        work / "03c_second_canonical_save.log",
    )
    baseline_stability_report = work / "edit_baseline_persistence_check.json"
    run_logged(
        settings.blender_command() + ["--background", str(edit_blend), "--python-exit-code", "1", "--python", str(extract_script), "--", "--baseline", str(baseline_report), "--report", str(baseline_stability_report), "--allow-no-change"],
        work / "03d_persisted_baseline_stability.log",
    )
    baseline_stability = json.loads(baseline_stability_report.read_text(encoding="utf-8"))
    if baseline_stability.get("check") != "PASS" or int(baseline_stability.get("changed_vertex_count",-1)) != 0:
        raise RuntimeError(f"persisted edit baseline is not save/reload stable: {baseline_stability}")

    # Keep the proven single-vertex default for backwards-compatible one-point edits,
    # and additionally discover a physically valid two-vertex transaction.  The GUI
    # preselects the transaction; the writer still recomputes the joint guard from
    # the actual saved geometry immediately before any output is created.
    from .rare_rigid_multibone_bridge import analyze_at_dragon_multibone
    analyzed = analyze_at_dragon_multibone(prepared, skeleton)
    default_plan = (analyzed.get("representative_witnesses") or {}).get("affected_bones_ge_2") or {}
    default_safe_selection = {
        "object_index": int(default_plan.get("object_index", -1)),
        "vertex_index": int(default_plan.get("vertex_index", -1)),
        "bone": default_plan.get("bone"),
        "affected_bone_count": default_plan.get("affected_bone_count"),
        "suggested_axis": default_plan.get("axis"),
        "suggested_delta_world_fixed": default_plan.get("delta_world_fixed"),
    }
    if default_safe_selection["object_index"] < 0 or default_safe_selection["vertex_index"] < 0:
        raise RuntimeError("default safe multibone UI selection unresolved")
    tx_discovery = discover_transaction_representatives(prepared, skeleton)
    if not tx_discovery.get("complete"):
        raise RuntimeError(f"multi-vertex transaction representatives unresolved: {tx_discovery}")
    # The artist-facing default is deliberately simpler than the strongest audit
    # witness: both selected vertices accept the same axis/delta, so one Blender
    # G/axis/value operation produces the entire two-vertex transaction.
    default_tx_plan = discover_uniform_translation_pair(prepared, skeleton)
    default_safe_transaction = {
        "object_index": int(default_tx_plan.get("object_index", -1)),
        "changed_vertex_indices": [int(x) for x in (default_tx_plan.get("changed_vertex_indices") or [])],
        "affected_bone_count": int(default_tx_plan.get("affected_bone_count", 0)),
        "affected_bones": list(default_tx_plan.get("affected_bones") or []),
        "shared_face_pairs": int(default_tx_plan.get("changed_vertex_pairs_sharing_face", 0)),
        "uniform_axis": default_tx_plan.get("uniform_axis"),
        "uniform_delta_world_fixed": int(default_tx_plan.get("uniform_delta_world_fixed", 0)),
        "uniform_delta_world": float(default_tx_plan.get("uniform_delta_world", 0.0)),
        "suggested_changes": [
            {
                "vertex_index": int(r["vertex_index"]),
                "before_world_fixed": list(r["before_world_fixed"]),
                "after_world_fixed": list(r["requested_after_world_fixed"]),
            }
            for r in (default_tx_plan.get("changed_vertices") or [])
        ],
    }
    if default_safe_transaction["object_index"] < 0 or len(default_safe_transaction["changed_vertex_indices"]) != 2:
        raise RuntimeError("default safe two-vertex transaction unresolved")

    manifest = {
        "format": WORKSPACE_FORMAT,
        "logical": TARGET,
        "source": str(source),
        "source_sha256": sha256_file(source),
        "prepared_source": str(prepared),
        "prepared_source_sha256": sha256_file(prepared),
        "motion_smb": preview["motion_smb"],
        "skeleton": str(skeleton),
        "skeleton_sha256": sha256_file(skeleton),
        "root_model": preview["root_model"],
        "source_inxs": preview["source_inxs"],
        "target_inx": preview["target_inx"],
        "root_lod": preview["root_lod"],
        "rare_visibility_policy": preview["rare_visibility_policy"],
        "edit_blend": str(edit_blend),
        "baseline_blender_report": str(baseline_report),
        "baseline_persistence_report": str(baseline_stability_report),
        "persisted_baseline_canonicalized": True,
        "persisted_baseline_stable": True,
        "default_safe_selection": default_safe_selection,
        "default_safe_transaction": default_safe_transaction,
        "transaction_representatives_discovered": True,
        "write_scope": "AT_DRAGON_ONE_TO_FOUR_CHANGED_MULTIBONE_BOUNDARY_VERTICES_SINGLE_OBJECT_INTERIOR_TRANSACTION",
        "workspace_origin": workspace_origin,
        "ui_safety_profile": {
            "object_transforms_locked": True,
            "proportional_edit_disabled": True,
            "vertex_select_mode": True,
            "automerge_disabled": True,
            "imported_vertex_selection_cleared": True,
            "default_safe_vertex_preselected": False,
            "default_safe_transaction_preselected": True,
            "max_transaction_vertices": MAX_TRANSACTION_VERTICES,
        },
        "client_modified": False,
    }
    manifest_path = work / "workspace_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if open_gui:
        viewer = project_root / "pt_asset_tool/blender/open_rare_rigid_edit.py"
        run_logged(
            settings.blender_command() + [str(edit_blend), "--python", str(viewer), "--", "--manifest", str(manifest_path)],
            work / "04_edit_gui.log",
        )
    return manifest


def _reimport_and_check(
    *, reg, resolver, certifications, settings, project_root: pathlib.Path,
    preview: dict[str, Any], skeleton: pathlib.Path, prepared_output: pathlib.Path,
    plan: dict[str, Any], work: pathlib.Path,
) -> dict[str, Any]:
    root_src = pathlib.Path(resolver.resolve(preview["root_model"], required=True))
    source_inx = pathlib.Path(resolver.resolve(preview["source_inxs"][0], required=True))
    target_inx = pathlib.Path(resolver.resolve(preview["target_inx"], required=True))
    overlay_root = pathlib.Path(preview["preview_blend"]).parent / "textures" / "texture_overlay_client"
    if not overlay_root.is_dir():
        raise RuntimeError("base preview texture overlay missing")

    rebuilt_blend = work / "rebuilt_preview.blend"
    import_report = work / "rebuilt_import.json"
    importer_script = project_root / "pt_asset_tool/blender/import_rare_rigid_context.py"
    common = [
        "--importer", str(project_root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src), "--skeleton", str(skeleton),
        "--rare-model-info", str(source_inx), "--root-model-info", str(target_inx),
        "--root-lod", str(preview["root_lod"]), "--rare-visibility-policy", str(preview["rare_visibility_policy"]),
        "--client-root", str(overlay_root), "--out", str(rebuilt_blend), "--report", str(import_report),
        "--logical", TARGET, "--root-logical", str(preview["root_model"]),
    ]
    run_logged(settings.blender_command() + ["--background", "--python-exit-code", "1", "--python", str(importer_script), "--", *common], work / "07_rebuilt_import.log")
    imported = json.loads(import_report.read_text(encoding="utf-8"))
    if imported.get("check") != "PASS":
        raise RuntimeError(f"rebuilt import failed: {imported}")

    transport_report = work / "rebuilt_transport.json"
    checker = project_root / "pt_asset_tool/blender/check_rare_rigid_context.py"
    run_logged(settings.blender_command() + [
        "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(checker), "--",
        "--importer", str(project_root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src), "--skeleton", str(skeleton),
        "--rare-model-info", str(source_inx), "--root-model-info", str(target_inx),
        "--root-lod", str(preview["root_lod"]), "--rare-visibility-policy", str(preview["rare_visibility_policy"]),
        "--report", str(transport_report),
    ], work / "08_rebuilt_transport.log")
    transport = json.loads(transport_report.read_text(encoding="utf-8"))
    if transport.get("check") != "PASS":
        raise RuntimeError(f"rebuilt transport failed: {transport}")

    plan_path = work / "write_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    witness_report = work / "rebuilt_witness_check.json"
    witness_checker = project_root / "pt_asset_tool/blender/check_rare_rigid_geometry_witness.py"
    run_logged(settings.blender_command() + [
        "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(witness_checker), "--",
        "--plan", str(plan_path), "--report", str(witness_report),
    ], work / "09_rebuilt_witness.log")
    witness = json.loads(witness_report.read_text(encoding="utf-8"))
    if witness.get("check") != "PASS":
        raise RuntimeError(f"rebuilt witness failed: {witness}")
    return {"rebuilt_blend": str(rebuilt_blend), "transport": transport, "witness": witness}


def _reimport_and_check_transaction(
    *, reg, resolver, certifications, settings, project_root: pathlib.Path,
    preview: dict[str, Any], skeleton: pathlib.Path, prepared_output: pathlib.Path,
    plan: dict[str, Any], work: pathlib.Path,
) -> dict[str, Any]:
    root_src = pathlib.Path(resolver.resolve(preview["root_model"], required=True))
    source_inx = pathlib.Path(resolver.resolve(preview["source_inxs"][0], required=True))
    target_inx = pathlib.Path(resolver.resolve(preview["target_inx"], required=True))
    overlay_root = pathlib.Path(preview["preview_blend"]).parent / "textures" / "texture_overlay_client"
    if not overlay_root.is_dir():
        raise RuntimeError("base preview texture overlay missing")
    work.mkdir(parents=True, exist_ok=True)
    rebuilt_blend = work / "rebuilt_preview.blend"
    import_report = work / "rebuilt_import.json"
    importer_script = project_root / "pt_asset_tool/blender/import_rare_rigid_context.py"
    common = [
        "--importer", str(project_root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src), "--skeleton", str(skeleton),
        "--rare-model-info", str(source_inx), "--root-model-info", str(target_inx),
        "--root-lod", str(preview["root_lod"]), "--rare-visibility-policy", str(preview["rare_visibility_policy"]),
        "--client-root", str(overlay_root), "--out", str(rebuilt_blend), "--report", str(import_report),
        "--logical", TARGET, "--root-logical", str(preview["root_model"]),
    ]
    run_logged(settings.blender_command() + ["--background", "--python-exit-code", "1", "--python", str(importer_script), "--", *common], work / "07_rebuilt_import.log")
    imported = json.loads(import_report.read_text(encoding="utf-8"))
    if imported.get("check") != "PASS":
        raise RuntimeError(f"rebuilt import failed: {imported}")
    transport_report = work / "rebuilt_transport.json"
    checker = project_root / "pt_asset_tool/blender/check_rare_rigid_context.py"
    run_logged(settings.blender_command() + [
        "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(checker), "--",
        "--importer", str(project_root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src), "--skeleton", str(skeleton),
        "--rare-model-info", str(source_inx), "--root-model-info", str(target_inx),
        "--root-lod", str(preview["root_lod"]), "--rare-visibility-policy", str(preview["rare_visibility_policy"]),
        "--report", str(transport_report),
    ], work / "08_rebuilt_transport.log")
    transport = json.loads(transport_report.read_text(encoding="utf-8"))
    if transport.get("check") != "PASS":
        raise RuntimeError(f"rebuilt transport failed: {transport}")
    plan_path = work / "write_transaction_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    witness_report = work / "rebuilt_transaction_check.json"
    witness_checker = project_root / "pt_asset_tool/blender/check_rare_rigid_transaction.py"
    run_logged(settings.blender_command() + [
        "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(witness_checker), "--",
        "--plan", str(plan_path), "--report", str(witness_report),
    ], work / "09_rebuilt_transaction.log")
    witness = json.loads(witness_report.read_text(encoding="utf-8"))
    if witness.get("check") != "PASS":
        raise RuntimeError(f"rebuilt transaction witness failed: {witness}")
    return {"rebuilt_blend": str(rebuilt_blend), "transport": transport, "witness": witness}


def write_at_dragon_edit_workspace(
    reg,
    resolver,
    certifications,
    settings,
    *,
    project_root: pathlib.Path,
    output: pathlib.Path | None = None,
    workspace_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root)
    work = pathlib.Path(workspace_root) if workspace_root is not None else _workspace_root(project_root)
    manifest_path = work / "workspace_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("edit workspace missing; run: pt_asset.py edit rare-model char/tmABCD/at_dragon.smd")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != WORKSPACE_FORMAT or manifest.get("logical") != TARGET:
        raise RuntimeError("edit workspace manifest mismatch")

    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    if sha256_file(source) != manifest.get("source_sha256"):
        raise RuntimeError("physical at_dragon source changed since edit workspace creation")
    skeleton = pathlib.Path(resolver.resolve(manifest["motion_smb"], required=True))
    if sha256_file(skeleton) != manifest.get("skeleton_sha256"):
        raise RuntimeError("physical skeleton changed since edit workspace creation")
    prepared = pathlib.Path(manifest["prepared_source"])
    if not prepared.is_file() or sha256_file(prepared) != manifest.get("prepared_source_sha256"):
        raise RuntimeError("prepared source changed/missing")

    # Reverify the serialized INX LinkFile binding immediately before every write.
    binding = audit_rare_rigid_binding(reg, resolver, project_root=project_root, work=work / "write_binding_recheck", bundle=None)
    if binding.get("status") != "PASS":
        raise RuntimeError("binding recheck failed before write")
    _at_dragon_binding(binding)

    edit_blend = pathlib.Path(manifest["edit_blend"])
    if not edit_blend.is_file():
        raise RuntimeError("saved edit blend missing")
    extraction_report = work / "artist_edit_extract.json"
    extract_script = project_root / "pt_asset_tool/blender/extract_rare_rigid_edit.py"
    run_logged(settings.blender_command() + [
        "--background", str(edit_blend), "--python-exit-code", "1", "--python", str(extract_script), "--",
        "--baseline", str(manifest["baseline_blender_report"]), "--report", str(extraction_report),
        "--max-changed", str(MAX_TRANSACTION_VERTICES),
    ], work / "05_extract_artist_edit.log")
    extraction = json.loads(extraction_report.read_text(encoding="utf-8"))
    if extraction.get("check") != "PASS":
        raise RuntimeError(f"Blender edit extraction failed: {extraction}")
    changed = list(extraction.get("changed_vertices") or [])
    if not (1 <= len(changed) <= MAX_TRANSACTION_VERTICES):
        raise RuntimeError(f"V0.8.9 requires 1..{MAX_TRANSACTION_VERTICES} changed rare vertices; got {len(changed)}")
    changed_objects = sorted({int(r["object_index"]) for r in changed})
    if len(changed_objects) != 1:
        raise RuntimeError("V0.8.9 multi-vertex transactions must remain inside one rare mesh object")

    multi = len(changed) >= MIN_TRANSACTION_VERTICES
    if not multi:
        ch = changed[0]
        plan = plan_requested_at_dragon_edit(
            prepared,
            skeleton,
            object_index=int(ch["object_index"]),
            vertex_index=int(ch["vertex_index"]),
            requested_world_fixed=tuple(int(x) for x in ch["after_world_fixed"]),
        )
        if list(plan["before_world_fixed"]) != list(ch["before_world_fixed"]):
            raise RuntimeError("workspace baseline position does not match physical source")
        changed_vertex_indices = [int(plan["vertex_index"])]
        max_position_error = int(plan["requested_reimport_error_fixed"])
        joint_shared_face_pairs = 0
        transaction_mode = "SINGLE_VERTEX_GUARDED"
        transaction_atomic = True
    else:
        plan = plan_requested_at_dragon_transaction(
            prepared,
            skeleton,
            changes=[
                {
                    "object_index": int(ch["object_index"]),
                    "vertex_index": int(ch["vertex_index"]),
                    "before_world_fixed": [int(x) for x in ch["before_world_fixed"]],
                    "after_world_fixed": [int(x) for x in ch["after_world_fixed"]],
                }
                for ch in changed
            ],
        )
        extract_by_vi = {int(ch["vertex_index"]): ch for ch in changed}
        for row in plan["changed_vertices"]:
            vi = int(row["vertex_index"])
            ch = extract_by_vi.get(vi)
            if ch is None or list(row["before_world_fixed"]) != list(ch["before_world_fixed"]):
                raise RuntimeError(f"workspace baseline position does not match physical source for vertex {vi}")
        changed_vertex_indices = [int(x) for x in plan["changed_vertex_indices"]]
        max_position_error = int(plan["max_requested_reimport_error_fixed"])
        joint_shared_face_pairs = int(plan["changed_vertex_pairs_sharing_face"])
        transaction_mode = "JOINT_FINAL_GEOMETRY_TRANSACTION"
        transaction_atomic = bool(plan.get("transaction_atomic"))

    final_output = pathlib.Path(output) if output else (work / "output" / "at_dragon_guarded_edit.smd")
    if not final_output.is_absolute():
        final_output = (project_root / final_output).resolve()
    final_output.parent.mkdir(parents=True, exist_ok=True)
    staging = final_output.with_name(final_output.name + ".v089_staging")
    if staging.exists():
        staging.unlink()
    prepared_output = work / "output" / "prepared_at_dragon.smd"
    if prepared_output.exists():
        prepared_output.unlink()

    # Build the entire output transaction in a disposable staging file.  The user-visible
    # output path is atomically replaced only after binary, Blender transport and witness
    # validation all pass.  A rejected transaction therefore cannot partially publish.
    try:
        if multi:
            patch = patch_guarded_multivertex(source, prepared, staging, plan)
        else:
            patch = patch_guarded_multibone(source, prepared, staging, plan)
        prepare_model062_tooling_source(staging, prepared_output)
        bone_tms = _parse_skeleton_tms(skeleton)
        if multi:
            binary = compare_guarded_multivertex(source, staging, prepared_output, plan, patch, bone_tms)
        else:
            binary = compare_guarded_multibone(source, staging, prepared_output, plan, patch, bone_tms)

        preview = json.loads((work / "base_preview" / "summary.json").read_text(encoding="utf-8"))
        if multi:
            validation = _reimport_and_check_transaction(
                reg=reg, resolver=resolver, certifications=certifications, settings=settings,
                project_root=project_root, preview=preview, skeleton=skeleton,
                prepared_output=prepared_output, plan=plan, work=work / "write_validation",
            )
        else:
            validation = _reimport_and_check(
                reg=reg, resolver=resolver, certifications=certifications, settings=settings,
                project_root=project_root, preview=preview, skeleton=skeleton,
                prepared_output=prepared_output, plan=plan, work=work / "write_validation",
            )
        staging.replace(final_output)
    except Exception:
        if staging.exists():
            staging.unlink()
        raise

    try:
        asset_id = str(getattr(reg.resolve(TARGET), "asset_id", "") or "")
    except Exception:
        asset_id = ""
    if not asset_id:
        asset_id = "RARE::" + TARGET
    write_scope = (
        "AT_DRAGON_TWO_TO_FOUR_CHANGED_MULTIBONE_BOUNDARY_VERTICES_SINGLE_OBJECT_INTERIOR_ATOMIC_TRANSACTION"
        if multi else
        "AT_DRAGON_EXACTLY_ONE_CHANGED_MULTIBONE_BOUNDARY_VERTEX_INTERIOR_ONLY"
    )
    cert = certifications.add(
        asset_id=asset_id,
        asset_path=TARGET,
        family="MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT",
        test="RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE" if multi else "RARE_RIGID_ARTIST_GUARDED_EDIT_WRITE",
        layer="AUTOMATIC",
        result="PASS",
        source_sha256=sha256_file(source),
        artifact_sha256=sha256_file(final_output),
        metadata={
            "write_scope": write_scope,
            "transaction_mode": transaction_mode,
            "artist_changed_vertices": len(changed),
            "object_index": int(plan["object_index"]),
            "changed_vertex_indices": changed_vertex_indices,
            "affected_bone_count": int(plan["affected_bone_count"]),
            "affected_bones": list(plan["affected_bones"]),
            "max_requested_reimport_error_fixed": max_position_error,
            "max_target_reimport_normal_error_fixed": binary["max_target_reimport_normal_error_fixed"],
            "non_authorized_bytes_byte_identical": binary["all_non_authorized_bytes_byte_identical"],
            "bounds_header_byte_identical": binary["bounds_header_byte_identical"],
            "joint_final_geometry_guard": multi,
            "atomic_output_replace": True,
            "client_modified": False,
        },
    )

    result = {
        "format": WRITE_FORMAT,
        "status": "PASS",
        "logical": TARGET,
        "artist_changed_vertices": len(changed),
        "transaction_mode": transaction_mode,
        "transaction_atomic": transaction_atomic,
        "atomic_output_replace": True,
        "single_object_transaction": True,
        "max_transaction_vertices_authorized": MAX_TRANSACTION_VERTICES,
        "joint_final_geometry_guard": multi,
        "object_index": int(plan["object_index"]),
        "head_name": plan["head_name"],
        "changed_vertex_indices": changed_vertex_indices,
        "changed_vertex_pairs_sharing_face": joint_shared_face_pairs,
        "affected_bone_count": int(plan["affected_bone_count"]),
        "affected_bones": list(plan["affected_bones"]),
        "max_requested_reimport_error_fixed": max_position_error,
        "max_current_source_normal_delta_fixed": int(plan["max_current_source_normal_delta_fixed"]),
        "max_target_reimport_normal_error_fixed": binary["max_target_reimport_normal_error_fixed"],
        "all_non_authorized_bytes_byte_identical": binary["all_non_authorized_bytes_byte_identical"],
        "bounds_header_byte_identical": binary["bounds_header_byte_identical"],
        "transport_position_error": validation["transport"].get("max_position_abs_error"),
        "transport_uv_error": validation["transport"].get("max_uv_abs_error"),
        "physique_mismatch_count": validation["transport"].get("physique_mismatch_count"),
        "output_smd": str(final_output),
        "rebuilt_blend": validation["rebuilt_blend"],
        "certification_id": cert["certification_id"],
        "write_scope": write_scope,
        "writer_input_mode_before": extraction.get("writer_input_mode_before"),
        "writer_input_mode_after": extraction.get("writer_input_mode_after"),
        "writer_input_object_mode_canonicalized": extraction.get("writer_input_object_mode_canonicalized"),
        "non_position_semantic_state_pass": extraction.get("non_position_semantic_state_pass"),
        "volatile_fingerprint_mismatch_objects": extraction.get("volatile_fingerprint_mismatch_objects"),
        "max_uv_state_delta": extraction.get("max_uv_state_delta"),
        "max_physique_weight_delta": extraction.get("max_physique_weight_delta"),
        "original_client_modified": False,
    }
    if not multi:
        result["vertex_index"] = int(plan["vertex_index"])
        result["requested_reimport_error_fixed"] = int(plan["requested_reimport_error_fixed"])
    report = work / "write_result.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(report)
    return result


def audit_rare_rigid_edit_workflow(
    reg,
    resolver,
    certifications,
    settings,
    *,
    project_root: pathlib.Path,
    work: pathlib.Path,
) -> dict[str, Any]:
    """Certify the real saved-Blender multi-vertex transaction path on 2/3/4 vertices."""
    project_root = pathlib.Path(project_root)
    work = pathlib.Path(work)
    audit_workspace = work / "isolated_artist_workspace"
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, certifications, settings,
        project_root=project_root, open_gui=False, reset=True,
        workspace_root=audit_workspace, workspace_origin="AUDIT",
    )
    prepared = pathlib.Path(manifest["prepared_source"])
    skeleton = pathlib.Path(manifest["skeleton"])
    discovery = discover_transaction_representatives(prepared, skeleton)
    reps = discovery.get("representatives") or {}
    if not discovery.get("complete"):
        raise RuntimeError(f"transaction representative discovery incomplete: {discovery}")

    edit_blend = pathlib.Path(manifest["edit_blend"])
    clean_blend = audit_workspace / "clean_persisted_artist_base.blend"
    shutil.copy2(edit_blend, clean_blend)

    # Negative control exercises the full saved-Blender -> extraction -> joint guard
    # -> atomic-output writer. One selected vertex is pushed far outside historical
    # bounds; the writer must fail and the requested output path must remain absent.
    negative_path = work / "negative_transaction_should_not_exist.smd"
    if negative_path.exists(): negative_path.unlink()
    negative_blocked = False; negative_error = ""
    apply_script = project_root / "pt_asset_tool/blender/apply_rare_rigid_transaction_witness.py"
    bad_plan = json.loads(json.dumps(reps["vertices_2"]))
    bad_plan["changed_vertices"][0]["requested_after_world_fixed"][0] += 1_000_000
    bad_plan_path = audit_workspace / "audit_transaction_negative.json"
    bad_plan_path.write_text(json.dumps(bad_plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    bad_apply_report = audit_workspace / "audit_transaction_negative_apply.json"
    shutil.copy2(clean_blend, edit_blend)
    run_logged(settings.blender_command()+[
        "--background",str(edit_blend),"--python-exit-code","1","--python",str(apply_script),"--",
        "--plan",str(bad_plan_path),"--report",str(bad_apply_report),
    ],audit_workspace / "audit_transaction_negative_apply.log")
    try:
        write_at_dragon_edit_workspace(reg,resolver,certifications,settings,project_root=project_root,output=negative_path,workspace_root=audit_workspace)
    except Exception as exc:
        negative_blocked = True; negative_error = str(exc)
    negative_output_created = negative_path.exists()

    rows=[]; max_normal=0; max_pos=0; max_bones=0; shared_reps=0
    for n in (2,3,4):
        key=f"vertices_{n}"; plan=reps[key]
        shutil.copy2(clean_blend, edit_blend)
        plan_path=audit_workspace / f"audit_transaction_{n}.json"
        plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        apply_report=audit_workspace / f"audit_transaction_apply_{n}.json"
        run_logged(settings.blender_command()+[
            "--background",str(edit_blend),"--python-exit-code","1","--python",str(apply_script),"--",
            "--plan",str(plan_path),"--report",str(apply_report),
        ],audit_workspace / f"audit_transaction_apply_{n}.log")
        applied=json.loads(apply_report.read_text(encoding="utf-8"))
        if applied.get("check")!="PASS": raise RuntimeError(f"transaction artist witness {n} failed: {applied}")
        out=work / f"rebuilt_artist_transaction_{n}.smd"
        write=write_at_dragon_edit_workspace(reg,resolver,certifications,settings,project_root=project_root,output=out,workspace_root=audit_workspace)
        row={
            "changed_vertex_count":n,
            "check":write.get("status"),
            "object_index":write.get("object_index"),
            "changed_vertex_indices":write.get("changed_vertex_indices"),
            "changed_vertex_pairs_sharing_face":write.get("changed_vertex_pairs_sharing_face"),
            "affected_bone_count":write.get("affected_bone_count"),
            "affected_bones":write.get("affected_bones"),
            "max_requested_reimport_error_fixed":write.get("max_requested_reimport_error_fixed"),
            "max_target_reimport_normal_error_fixed":write.get("max_target_reimport_normal_error_fixed"),
            "joint_final_geometry_guard":write.get("joint_final_geometry_guard"),
            "transaction_atomic":write.get("transaction_atomic"),
            "atomic_output_replace":write.get("atomic_output_replace"),
            "non_authorized_bytes_exact":write.get("all_non_authorized_bytes_byte_identical"),
            "bounds_exact":write.get("bounds_header_byte_identical"),
            "transport_position_error":write.get("transport_position_error"),
            "transport_uv_error":write.get("transport_uv_error"),
            "physique_mismatch_count":write.get("physique_mismatch_count"),
            "writer_input_mode_before":write.get("writer_input_mode_before"),
            "writer_input_mode_after":write.get("writer_input_mode_after"),
            "non_position_semantic_state_pass":write.get("non_position_semantic_state_pass"),
            "output_smd":write.get("output_smd"),
            "certification_id":write.get("certification_id"),
            "client_modified":False,
        }
        rows.append(row)
        max_normal=max(max_normal,int(row["max_target_reimport_normal_error_fixed"] or 0)); max_pos=max(max_pos,int(row["max_requested_reimport_error_fixed"] or 0)); max_bones=max(max_bones,int(row["affected_bone_count"] or 0))
        if int(row["changed_vertex_pairs_sharing_face"] or 0)>0: shared_reps+=1

    complete=(
        len(rows)==3 and all(r.get("check")=="PASS" for r in rows)
        and all(bool(r.get("joint_final_geometry_guard")) for r in rows)
        and all(bool(r.get("transaction_atomic")) and bool(r.get("atomic_output_replace")) for r in rows)
        and all(bool(r.get("non_authorized_bytes_exact")) and bool(r.get("bounds_exact")) for r in rows)
        and all(bool(r.get("non_position_semantic_state_pass")) for r in rows)
        and shared_reps==3 and negative_blocked and not negative_output_created
    )
    result={
        "format":"PT_RARE_RIGID_GUARDED_EDIT_WORKFLOW_AUDIT_V5",
        "status":"PASS" if complete else "FAIL",
        "logical":TARGET,
        "workspace_prepared":True,
        "audit_workspace_isolated":True,
        "audit_workspace":str(audit_workspace),
        "persistent_artist_workspace_touched":False,
        "persisted_baseline_canonicalized":bool(manifest.get("persisted_baseline_canonicalized")),
        "persisted_baseline_stable":bool(manifest.get("persisted_baseline_stable")),
        "default_safe_transaction":manifest.get("default_safe_transaction"),
        "ui_safety_profile":manifest.get("ui_safety_profile"),
        "transaction_representatives_expected":3,
        "transaction_representatives_audited":len(rows),
        "transaction_roundtrip_pass":sum(1 for r in rows if r.get("check")=="PASS"),
        "transaction_vertex_counts":[2,3,4],
        "shared_face_transaction_representatives":shared_reps,
        "max_transaction_vertices_authorized":MAX_TRANSACTION_VERTICES,
        "single_object_transaction_only":True,
        "joint_final_geometry_guard":True,
        "transaction_atomic":True,
        "atomic_output_replace":True,
        "negative_transaction_blocked":negative_blocked,
        "negative_transaction_error":negative_error,
        "negative_output_created":negative_output_created,
        "max_affected_bone_count":max_bones,
        "max_requested_reimport_error_fixed":max_pos,
        "max_target_reimport_normal_error_fixed":max_normal,
        "single_vertex_write_authorized":True,
        "multi_vertex_transaction_write_authorized":complete,
        "extent_write_authorized":False,
        "topology_write_authorized":False,
        "rows":rows,
        "policy":{
            "joint_normals":"all requested positions are installed into one final geometry before SetGNormals deltas are calculated; single-vertex witness deltas are never composed additively",
            "atomicity":"the final output path is replaced only after joint guard, byte-range compare, Blender reimport, transport and transaction witness all pass",
            "scope":"2..4 changed multibone-boundary vertices in one at_dragon rare mesh object; interior only",
            "deferred":"cross-object transactions, more than four changed vertices, extent changes and topology remain fail-closed",
            "client_modified":False,
        },
        "client_modified":False,
    }
    rp=work / "rare_rigid_edit_workflow_v089.json"; rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); result["report"]=str(rp)
    return result

