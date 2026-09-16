from __future__ import annotations

import json
import pathlib
import struct
from typing import Any

from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_geometry import SV, _parse_skeleton_tms, _transform_point_fixed
from .rare_rigid_multibone_bridge import TARGET, analyze_at_dragon_multibone, audit_rare_rigid_multibone_bridge
from .rare_rigid_normal_bridge import NORMAL_TARGET_REIMPORT_LIMIT_FIXED, POSITION_REIMPORT_LIMIT_FIXED
from .rare_rigid_preview import _prepare_one_preview
from .rare_rigid_roundtrip import _parse_with_offsets
from .rare_support import prepare_model062_tooling_source
from .utils import norm_path, run_logged, sha256_file

REP_KEYS = (
    "affected_bones_ge_2",
    "affected_bones_ge_3",
    "affected_bones_ge_4",
)


def _in_ranges(i: int, ranges: list[list[int]]) -> bool:
    return any(int(lo) <= i < int(hi) for lo, hi in ranges)


def patch_guarded_multibone(
    source_physical: pathlib.Path,
    prepared_source: pathlib.Path,
    output_physical: pathlib.Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Patch only the witness position and affected normal endpoints.

    This intentionally does not touch bounds, faces, topology, Physique names,
    materials, TexLinks, animation arrays, or the legacy name mismatch bytes.
    """
    model = _parse_with_offsets(prepared_source)
    oi = int(plan["object_index"])
    vi = int(plan["vertex_index"])
    obj = model["objects"][oi]
    if obj["bones"][vi] != plan["bone"]:
        raise ValueError("witness Physique bone changed since planning")

    src = bytearray(pathlib.Path(source_physical).read_bytes())
    prepared_bytes = pathlib.Path(prepared_source).read_bytes()
    if len(src) != len(prepared_bytes):
        raise ValueError("physical/prepared size mismatch")

    allowed_ranges: list[list[int]] = []
    changed_records: list[dict[str, Any]] = []
    seen_vertices: set[int] = set()
    witness_seen = False

    for row in plan["affected_vertices"]:
        av = int(row["vertex_index"])
        if av in seen_vertices:
            raise ValueError(f"duplicate affected vertex {av}")
        seen_vertices.add(av)
        if not (0 <= av < len(obj["vertices"])):
            raise ValueError(f"affected vertex OOB: {av}")
        if obj["bones"][av] != row["bone"]:
            raise ValueError(f"affected vertex[{av}] Physique bone changed")

        off = int(obj["vertex_offset"]) + av * SV
        old = struct.unpack_from("<6i", src, off)
        expected_old = tuple(
            int(x)
            for x in (row["before_local_position_fixed"] + row["before_local_normal_endpoint_fixed"])
        )
        if old != expected_old:
            raise ValueError(f"source vertex[{av}] changed: {old} != {expected_old}")

        new_pos = tuple(int(x) for x in row["after_local_position_fixed"])
        new_ep = tuple(int(x) for x in row["after_local_normal_endpoint_fixed"])
        is_witness = bool(row["is_position_witness"])
        if is_witness:
            if av != vi:
                raise ValueError("position witness row does not match planned vertex")
            if witness_seen:
                raise ValueError("multiple position witness rows")
            witness_seen = True
            struct.pack_into("<6i", src, off, *(new_pos + new_ep))
            allowed_ranges.append([off, off + SV])
        else:
            # Position bytes of neighboring vertices are provenance and must remain exact.
            if new_pos != tuple(int(x) for x in row["before_local_position_fixed"]):
                raise ValueError(f"neighbor vertex[{av}] position unexpectedly changed in plan")
            struct.pack_into("<3i", src, off + 12, *new_ep)
            allowed_ranges.append([off + 12, off + SV])

        changed_records.append(
            {
                "vertex_index": av,
                "bone": row["bone"],
                "is_position_witness": is_witness,
                "record_offset": off,
                "old_record": list(old),
                "new_record": list(new_pos + new_ep),
            }
        )

    if not witness_seen:
        raise ValueError("position witness row missing")

    output_physical.parent.mkdir(parents=True, exist_ok=True)
    output_physical.write_bytes(src)
    return {"allowed_byte_ranges": allowed_ranges, "changed_records": changed_records}


def compare_guarded_multibone(
    source_physical: pathlib.Path,
    output_physical: pathlib.Path,
    prepared_output: pathlib.Path,
    plan: dict[str, Any],
    patch: dict[str, Any],
    bone_tms: dict[str, list[int]],
) -> dict[str, Any]:
    sb = pathlib.Path(source_physical).read_bytes()
    ob = pathlib.Path(output_physical).read_bytes()
    errors: list[str] = []
    if len(sb) != len(ob):
        errors.append("FILE_SIZE")
    if sb[:24] != ob[:24]:
        errors.append("PHYSICAL_HEADER24_CHANGED")

    diff = [i for i, (a, b) in enumerate(zip(sb, ob)) if a != b]
    outside = [i for i in diff if not _in_ranges(i, patch["allowed_byte_ranges"])]
    if outside:
        errors.append("NON_AUTHORIZED_BYTES_CHANGED")
    if not diff:
        errors.append("BYTE_IDENTICAL_AFTER_EDIT")

    out_model = _parse_with_offsets(prepared_output)
    obj = out_model["objects"][int(plan["object_index"])]
    witness_vi = int(plan["vertex_index"])
    max_target_error = 0
    max_position_error = 0

    for row in plan["affected_vertices"]:
        av = int(row["vertex_index"])
        v = obj["vertices"][av]
        expected_pos = tuple(int(x) for x in row["after_local_position_fixed"])
        expected_ep = tuple(int(x) for x in row["after_local_normal_endpoint_fixed"])
        if tuple(v[:3]) != expected_pos:
            errors.append(f"OUTPUT_POSITION_{av}")
        if tuple(v[3:6]) != expected_ep:
            errors.append(f"OUTPUT_NORMAL_ENDPOINT_{av}")

        bone = row["bone"]
        tm = bone_tms.get(bone)
        if tm is None:
            errors.append(f"MISSING_BONE_{av}")
            continue
        wp = _transform_point_fixed(tuple(int(x) for x in v[:3]), tm)
        we = _transform_point_fixed(tuple(int(x) for x in v[3:6]), tm)
        vec = tuple(we[z] - wp[z] for z in range(3))
        target_vec = tuple(int(x) for x in row["target_historical_world_normal_fixed"])
        normal_err = max(abs(vec[z] - target_vec[z]) for z in range(3))
        max_target_error = max(max_target_error, normal_err)
        if normal_err > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
            errors.append(f"NORMAL_TARGET_REIMPORT_{av}")

        if av == witness_vi:
            expected_world = tuple(int(x) for x in plan["expected_reimport_world_fixed"])
            position_err = max(abs(wp[z] - expected_world[z]) for z in range(3))
            max_position_error = max(max_position_error, position_err)
            if wp != expected_world:
                errors.append("WITNESS_REIMPORT_WORLD")

    object_start = int(obj["object_start"])
    bounds_exact = sb[object_start + 44 : object_start + 76] == ob[object_start + 44 : object_start + 76]
    if not bounds_exact:
        errors.append("BOUNDS_HEADER_CHANGED")

    result = {
        "check": "PASS" if not errors else "FAIL",
        "errors": errors,
        "source_sha256": sha256_file(source_physical),
        "output_sha256": sha256_file(output_physical),
        "file_size": len(sb),
        "diff_byte_count": len(diff),
        "diff_bytes_outside_authorized_ranges": outside,
        "physical_header24_byte_identical": sb[:24] == ob[:24],
        "all_non_authorized_bytes_byte_identical": not outside and len(sb) == len(ob),
        "bounds_header_byte_identical": bounds_exact,
        "max_target_reimport_normal_error_fixed": max_target_error,
        "max_witness_reimport_position_error_fixed": max_position_error,
        "client_modified": False,
    }
    if errors:
        raise RuntimeError("guarded multibone compare failed: " + ",".join(errors))
    return result


def _run_rep(
    *,
    reg,
    resolver,
    certifications,
    settings,
    project_root: pathlib.Path,
    preview: dict[str, Any],
    source: pathlib.Path,
    prepared: pathlib.Path,
    skeleton: pathlib.Path,
    plan: dict[str, Any],
    rep_key: str,
    work: pathlib.Path,
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    plan = json.loads(json.dumps(plan))
    plan["logical"] = TARGET
    plan["representative_key"] = rep_key
    plan_path = work / "witness_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Blender proves that the requested edit is representable in the imported bind-pose mesh.
    witness_blend = work / "edited_witness.blend"
    witness_report = work / "blender_witness.json"
    witness_script = project_root / "pt_asset_tool/blender/witness_rare_rigid_geometry.py"
    run_logged(
        settings.blender_command()
        + [
            "--background",
            str(preview["preview_blend"]),
            "--python-exit-code",
            "1",
            "--python",
            str(witness_script),
            "--",
            "--plan",
            str(plan_path),
            "--out",
            str(witness_blend),
            "--report",
            str(witness_report),
        ],
        work / "01_blender_witness.log",
    )
    wr = json.loads(witness_report.read_text(encoding="utf-8"))
    if wr.get("check") != "PASS":
        raise RuntimeError(f"Blender witness failed: {wr}")
    if list(wr.get("after_world_fixed") or []) != plan["requested_after_world_fixed"]:
        raise RuntimeError("Blender witness fixed coordinate differs from plan")

    # Re-run the exact per-edit guard immediately before writing.  The plan itself
    # already contains every measured gate; we refuse if any one is out of scope.
    affected_bones = int(plan["affected_bone_count"])
    if affected_bones < 2:
        raise RuntimeError("representative is not multibone")
    if int(plan["requested_reimport_error_fixed"]) > POSITION_REIMPORT_LIMIT_FIXED:
        raise RuntimeError("position guard failed")
    if int(plan["max_target_reimport_normal_error_fixed"]) > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
        raise RuntimeError("normal endpoint guard failed")
    if plan.get("bounds_header_policy") != "PRESERVE_BYTE_IDENTICAL_INTERIOR_WITNESS":
        raise RuntimeError("extent-changing edit reached guarded multibone writer")

    output = work / "rebuilt_at_dragon_guarded_multibone.smd"
    patch = patch_guarded_multibone(source, prepared, output, plan)
    prepared_output = work / "prepared_output" / pathlib.PurePosixPath(TARGET)
    prepare_model062_tooling_source(output, prepared_output)
    bone_tms = _parse_skeleton_tms(skeleton)
    binary = compare_guarded_multibone(source, output, prepared_output, plan, patch, bone_tms)

    root_src = pathlib.Path(resolver.resolve(preview["root_model"], required=True))
    source_inx = pathlib.Path(resolver.resolve(preview["source_inxs"][0], required=True))
    target_inx = pathlib.Path(resolver.resolve(preview["target_inx"], required=True))
    base_preview_work = pathlib.Path(preview["preview_blend"]).parent
    overlay_root = base_preview_work / "textures" / "texture_overlay_client"
    if not overlay_root.is_dir():
        raise RuntimeError("base preview texture overlay missing")

    rebuilt_blend = work / "rebuilt_preview.blend"
    import_report = work / "rebuilt_import.json"
    importer_script = project_root / "pt_asset_tool/blender/import_rare_rigid_context.py"
    common = [
        "--importer",
        str(project_root / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd",
        str(prepared_output),
        "--root-smd",
        str(root_src),
        "--skeleton",
        str(skeleton),
        "--rare-model-info",
        str(source_inx),
        "--root-model-info",
        str(target_inx),
        "--root-lod",
        str(preview["root_lod"]),
        "--rare-visibility-policy",
        str(preview["rare_visibility_policy"]),
        "--client-root",
        str(overlay_root),
        "--out",
        str(rebuilt_blend),
        "--report",
        str(import_report),
        "--logical",
        TARGET,
        "--root-logical",
        str(preview["root_model"]),
    ]
    run_logged(
        settings.blender_command()
        + ["--background", "--python-exit-code", "1", "--python", str(importer_script), "--", *common],
        work / "02_rebuilt_import.log",
    )
    imported = json.loads(import_report.read_text(encoding="utf-8"))
    if imported.get("check") != "PASS":
        raise RuntimeError(f"rebuilt import failed: {imported}")

    transport_report = work / "rebuilt_transport.json"
    checker = project_root / "pt_asset_tool/blender/check_rare_rigid_context.py"
    run_logged(
        settings.blender_command()
        + [
            "--background",
            str(rebuilt_blend),
            "--python-exit-code",
            "1",
            "--python",
            str(checker),
            "--",
            "--importer",
            str(project_root / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"),
            "--rare-smd",
            str(prepared_output),
            "--root-smd",
            str(root_src),
            "--skeleton",
            str(skeleton),
            "--rare-model-info",
            str(source_inx),
            "--root-model-info",
            str(target_inx),
            "--root-lod",
            str(preview["root_lod"]),
            "--rare-visibility-policy",
            str(preview["rare_visibility_policy"]),
            "--report",
            str(transport_report),
        ],
        work / "03_rebuilt_transport.log",
    )
    transport = json.loads(transport_report.read_text(encoding="utf-8"))
    if transport.get("check") != "PASS":
        raise RuntimeError(f"rebuilt transport failed: {transport}")

    witness_check = work / "rebuilt_witness_check.json"
    witness_checker = project_root / "pt_asset_tool/blender/check_rare_rigid_geometry_witness.py"
    run_logged(
        settings.blender_command()
        + [
            "--background",
            str(rebuilt_blend),
            "--python-exit-code",
            "1",
            "--python",
            str(witness_checker),
            "--",
            "--plan",
            str(plan_path),
            "--report",
            str(witness_check),
        ],
        work / "04_rebuilt_witness.log",
    )
    wc = json.loads(witness_check.read_text(encoding="utf-8"))
    if wc.get("check") != "PASS":
        raise RuntimeError(f"rebuilt witness check failed: {wc}")

    try:
        asset_id = str(getattr(reg.resolve(TARGET), "asset_id", "") or "")
    except Exception:
        asset_id = ""
    if not asset_id:
        asset_id = "RARE::" + TARGET
    cert = certifications.add(
        asset_id=asset_id,
        asset_path=TARGET,
        family="MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT",
        test="RARE_RIGID_GUARDED_MULTIBONE_GEOMETRY_ROUNDTRIP",
        layer="AUTOMATIC",
        result="PASS",
        source_sha256=sha256_file(source),
        artifact_sha256=sha256_file(output),
        metadata={
            "representative_key": rep_key,
            "write_scope": "AT_DRAGON_INTERIOR_PER_EDIT_GUARDED_MULTIBONE_POSITION_AND_NORMALS",
            "affected_bone_count": affected_bones,
            "affected_bones": plan["affected_bones"],
            "object_index": plan["object_index"],
            "vertex_index": plan["vertex_index"],
            "requested_reimport_error_fixed": plan["requested_reimport_error_fixed"],
            "max_current_source_normal_delta_fixed": plan["max_current_source_normal_delta_fixed"],
            "max_target_reimport_normal_error_fixed": binary["max_target_reimport_normal_error_fixed"],
            "non_authorized_bytes_byte_identical": binary["all_non_authorized_bytes_byte_identical"],
            "bounds_header_byte_identical": binary["bounds_header_byte_identical"],
            "transport_check": transport.get("check"),
            "witness_check": wc.get("check"),
            "universal_multibone_write": False,
            "client_modified": False,
        },
    )

    return {
        "representative_key": rep_key,
        "check": "PASS",
        "logical": TARGET,
        "object_index": plan["object_index"],
        "head_name": plan["head_name"],
        "vertex_index": plan["vertex_index"],
        "bone": plan["bone"],
        "affected_bone_count": affected_bones,
        "affected_bones": plan["affected_bones"],
        "mixed_incident_bone_combinations": plan["mixed_incident_bone_combinations"],
        "delta_world_fixed": plan["delta_world_fixed"],
        "axis": plan["axis"],
        "requested_reimport_error_fixed": plan["requested_reimport_error_fixed"],
        "max_current_source_normal_delta_fixed": plan["max_current_source_normal_delta_fixed"],
        "max_target_reimport_normal_error_fixed": binary["max_target_reimport_normal_error_fixed"],
        "all_non_authorized_bytes_byte_identical": binary["all_non_authorized_bytes_byte_identical"],
        "bounds_header_byte_identical": binary["bounds_header_byte_identical"],
        "transport_position_error": transport.get("max_position_abs_error"),
        "transport_uv_error": transport.get("max_uv_abs_error"),
        "physique_mismatch_count": transport.get("physique_mismatch_count"),
        "rebuilt_witness_world_fixed": wc.get("actual_world_fixed"),
        "rebuilt_smd": str(output),
        "rebuilt_blend": str(rebuilt_blend),
        "certification_id": cert["certification_id"],
        "client_modified": False,
    }


def audit_rare_rigid_guarded_multibone_roundtrip(
    reg,
    resolver,
    certifications,
    settings,
    *,
    project_root: pathlib.Path,
    work: pathlib.Path,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root)
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)

    # Re-run V0.8.3 first; a writer is never allowed to rely on stale census data.
    preflight = audit_rare_rigid_multibone_bridge(
        reg, resolver, project_root=project_root, work=work / "preflight_recheck"
    )
    if preflight.get("status") != "PASS" or not preflight.get("guarded_multibone_writer_candidate"):
        raise RuntimeError("V0.8.3 multibone preflight recheck failed")
    if preflight.get("mixed_bone_faces") != 628 or preflight.get("bind_bones_used") != 31:
        raise RuntimeError("at_dragon physical census changed")

    reps = dict(preflight.get("representative_witnesses") or {})
    missing = [k for k in REP_KEYS if k not in reps]
    if missing:
        raise RuntimeError(f"required representative witnesses missing: {missing}")
    counts = [int(reps[k]["affected_bone_count"]) for k in REP_KEYS]
    if counts != [2, 3, 4]:
        raise RuntimeError(f"representative bone-count ladder changed: {counts}")

    binding = audit_rare_rigid_binding(
        reg, resolver, project_root=project_root, work=work / "binding_recheck", bundle=None
    )
    if binding.get("status") != "PASS":
        raise RuntimeError("binding recheck failed")

    preview_work = work / "base_preview"
    preview = _prepare_one_preview(
        reg=reg,
        resolver=resolver,
        certifications=certifications,
        settings=settings,
        project_root=project_root,
        binding=binding,
        logical=TARGET,
        work=preview_work,
        open_gui=False,
    )
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    prepared = preview_work / "prepared" / pathlib.PurePosixPath(TARGET)
    skeleton = pathlib.Path(resolver.resolve(preview["motion_smb"], required=True))

    # Independent mathematical re-analysis protects against a report/plan mismatch.
    fresh = analyze_at_dragon_multibone(prepared, skeleton)
    if fresh["safe_mixed_boundary_vertices"] != int(preflight["safe_mixed_boundary_vertices"]):
        raise RuntimeError("safe multibone census changed after preview preparation")

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for key in REP_KEYS:
        try:
            rows.append(
                _run_rep(
                    reg=reg,
                    resolver=resolver,
                    certifications=certifications,
                    settings=settings,
                    project_root=project_root,
                    preview=preview,
                    source=source,
                    prepared=prepared,
                    skeleton=skeleton,
                    plan=fresh["representative_witnesses"][key],
                    rep_key=key,
                    work=work / key,
                )
            )
        except Exception as exc:
            errors.append({"representative_key": key, "error": f"{type(exc).__name__}: {exc}"})

    passed = sum(r.get("check") == "PASS" for r in rows)
    complete = passed == len(REP_KEYS) and not errors
    result = {
        "format": "PT_RARE_RIGID_GUARDED_MULTIBONE_GEOMETRY_ROUNDTRIP_V1",
        "status": "PASS" if complete else "FAIL",
        "logical": TARGET,
        "expected_representatives": len(REP_KEYS),
        "audited_representatives": len(rows),
        "roundtrip_pass": passed,
        "representative_bone_counts": [int(r["affected_bone_count"]) for r in rows],
        "guarded_multibone_position_normal_write_authorized": complete,
        "guard_scope": "PER_EDIT_INTERIOR_AT_DRAGON_ONLY_IF_POSITION_NONDEGENERATE_INT32_NORMAL_ENDPOINT_AND_BOUNDS_GATES_PASS",
        "universal_at_dragon_geometry_write_authorized": False,
        "extent_changing_multibone_write_authorized": False,
        "topology_write_authorized": False,
        "safe_mixed_boundary_vertices": fresh["safe_mixed_boundary_vertices"],
        "blocked_mixed_boundary_vertices": fresh["blocked_mixed_boundary_vertices"],
        "mixed_faces_with_safe_vertex": fresh["mixed_faces_with_safe_vertex"],
        "mixed_faces_without_safe_vertex": fresh["mixed_faces_without_safe_vertex"],
        "safe_mixed_bone_combinations": fresh["safe_mixed_bone_combinations"],
        "distinct_mixed_bone_combinations": fresh["distinct_mixed_bone_combinations"],
        "max_requested_reimport_error_fixed": max([int(r.get("requested_reimport_error_fixed") or 0) for r in rows] or [0]),
        "max_current_source_normal_delta_fixed": max([int(r.get("max_current_source_normal_delta_fixed") or 0) for r in rows] or [0]),
        "max_target_reimport_normal_error_fixed": max([int(r.get("max_target_reimport_normal_error_fixed") or 0) for r in rows] or [0]),
        "non_authorized_bytes_exact_representatives": sum(bool(r.get("all_non_authorized_bytes_byte_identical")) for r in rows),
        "bounds_header_exact_representatives": sum(bool(r.get("bounds_header_byte_identical")) for r in rows),
        "physique_mismatch_total": sum(int(r.get("physique_mismatch_count") or 0) for r in rows),
        "errors": errors,
        "rows": rows,
        "policy": {
            "authorization": "authorization is per requested edit, never per file; the exact guard must be recomputed immediately before writing",
            "safe_subset": "only edits passing the proven per-vertex-bone position and normal provenance bridge, nondegenerate-face, int32 and historical-bound gates are writable",
            "blocked_subset": "the remaining 270 mixed-boundary vertices stay fail-closed; no proximity, interpolation or bone-name similarity can authorize them",
            "bounds": "V0.8.4 is interior-only for at_dragon; multibone extent changes remain deferred",
            "topology": "unchanged",
            "legacy_name_mismatch": "MBHB18/MBHB19 provenance remains byte-identical outside explicitly authorized vertex endpoint fields",
            "client_modified": False,
        },
        "client_modified": False,
    }
    rp = work / "rare_rigid_guarded_multibone_roundtrip_report.json"
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(rp)
    return result
