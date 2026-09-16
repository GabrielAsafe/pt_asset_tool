from __future__ import annotations

import json
import math
import pathlib
import struct
from typing import Any

from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_geometry import (
    SH, SI, SO, SV, O_NV, O_NF, O_NT, O_NR, O_NP, O_NS,
    _i32, _object_layout, _parse_rigid_model, _parse_skeleton_tms,
    _transform_point_fixed, _invert_matrix_source,
)
from .rare_rigid_preview import _prepare_one_preview
from .rare_support import prepare_model062_tooling_source
from .utils import low_path, norm_path, run_logged, sha256_file

CANDIDATES = [
    "char/tmABCD/ar0nass.smd",
    "char/tmABCD/CartolaFS.smd",
    "char/tmABCD/CartolaMG.smd",
    "char/tmABCD/CartolaPS.smd",
    "char/tmABCD/CartolaSH.smd",
]
DEFERRED_MULTI_BONE = "char/tmABCD/at_dragon.smd"


def _parse_with_offsets(path: pathlib.Path) -> dict[str, Any]:
    data = pathlib.Path(path).read_bytes()
    model = _parse_rigid_model(path)
    oc = _i32(data, 24)
    if oc != len(model["objects"]):
        raise ValueError("object count mismatch")
    for idx, obj in enumerate(model["objects"]):
        io = SH + idx * SI
        length = _i32(data, io + 32)
        start = _i32(data, io + 36)
        raw = data[start:start + SO]
        nv, nf, nt, nr, np, ns = [_i32(raw, o) for o in (O_NV, O_NF, O_NT, O_NR, O_NP, O_NS)]
        vb, fb, ph, end = _object_layout(start, nv, nf, nt, nr, np, ns, True)
        if end != start + length:
            raise ValueError(f"object[{idx}] layout mismatch")
        obj["object_start"] = start
        obj["object_length"] = length
        obj["vertex_offset"] = vb
        obj["face_offset"] = fb
        obj["physique_offset"] = ph
    return model


def _stored_bound_safe(p: tuple[int, int, int], sb: dict[str, int], margin: int = 32) -> bool:
    x, y, z = p
    # Historical AddVertex axis naming: maxX=abs(x), maxZ=abs(y), maxY=abs(z).
    if abs(x) >= int(sb["maxX"]) - margin:
        return False
    if abs(y) >= int(sb["maxZ"]) - margin:
        return False
    if abs(z) >= int(sb["maxY"]) - margin:
        return False
    xx, yy, zz = x >> 8, y >> 8, z >> 8
    d = abs(xx * xx + yy * yy + zz * zz)
    if d >= int(sb["dBound"]):
        return False
    return math.isqrt(d) <= int(sb["Bound"])


def _incident_safe(world: list[tuple[int, int, int]], faces: list[tuple[int, ...]], vi: int) -> tuple[bool, int]:
    incident = 0
    for f in faces:
        a, b, c = f[:3]
        if vi not in (a, b, c):
            continue
        incident += 1
        p1, p2, p3 = world[a], world[b], world[c]
        vals = (
            (p2[1] - p1[1]) * (p3[2] - p1[2]) - (p2[2] - p1[2]) * (p3[1] - p1[1]),
            (p2[2] - p1[2]) * (p3[0] - p1[0]) - (p2[0] - p1[0]) * (p3[2] - p1[2]),
            (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0]),
        )
        if vals == (0, 0, 0):
            return False, incident
        if any(q < -0x80000000 or q > 0x7FFFFFFF for q in vals):
            return False, incident
    return incident > 0, incident


def _world_normal_vector(local_pos: tuple[int, int, int], local_ep: tuple[int, int, int], tm: list[int]) -> tuple[int, int, int]:
    wp = _transform_point_fixed(local_pos, tm)
    we = _transform_point_fixed(local_ep, tm)
    return tuple(we[i] - wp[i] for i in range(3))


def choose_single_bone_witness(model: dict[str, Any], bones: dict[str, list[int]]) -> dict[str, Any]:
    choices: list[tuple[tuple[int, ...], dict[str, Any]]] = []
    for oi, obj in enumerate(model["objects"]):
        bset = sorted(set(obj["bones"]), key=str.lower)
        if len(bset) != 1:
            continue
        bone_name = bset[0]
        tm = bones.get(bone_name)
        if tm is None:
            continue
        inv = _invert_matrix_source(tm)
        world = [_transform_point_fixed(tuple(v[:3]), tm) for v in obj["vertices"]]
        incidence = [[] for _ in world]
        for fi, f in enumerate(obj["faces"]):
            for v in f[:3]:
                incidence[v].append(fi)
        for vi, face_ids in enumerate(incidence):
            if not face_ids:
                continue
            old = obj["vertices"][vi]
            old_local = tuple(int(x) for x in old[:3])
            old_ep = tuple(int(x) for x in old[3:6])
            old_w = world[vi]
            old_vec = _world_normal_vector(old_local, old_ep, tm)
            for delta in (256, -256, 512, -512, 1024, -1024):
                for axis in (0, 2, 1):
                    requested = list(old_w)
                    requested[axis] += delta
                    requested_t = tuple(requested)
                    if not _stored_bound_safe(requested_t, obj["stored_bounds"]):
                        continue
                    new_local = _transform_point_fixed(requested_t, inv)
                    if new_local == old_local:
                        continue
                    if any(q < -0x80000000 or q > 0x7FFFFFFF for q in new_local):
                        continue
                    local_delta = tuple(new_local[i] - old_local[i] for i in range(3))
                    new_ep = tuple(old_ep[i] + local_delta[i] for i in range(3))
                    if any(q < -0x80000000 or q > 0x7FFFFFFF for q in new_ep):
                        continue
                    reimport = _transform_point_fixed(new_local, tm)
                    if not _stored_bound_safe(reimport, obj["stored_bounds"]):
                        continue
                    pos_error = max(abs(reimport[i] - requested_t[i]) for i in range(3))
                    if pos_error > 20:
                        continue
                    w2 = list(world)
                    w2[vi] = requested_t
                    safe, incident_count = _incident_safe(w2, obj["faces"], vi)
                    if not safe:
                        continue
                    new_vec = _world_normal_vector(new_local, new_ep, tm)
                    normal_delta = tuple(new_vec[i] - old_vec[i] for i in range(3))
                    normal_error = max(abs(q) for q in normal_delta)
                    if normal_error > 1:
                        continue
                    score = (incident_count, normal_error, pos_error, abs(delta), oi, vi, axis)
                    plan = {
                        "object_index": oi,
                        "table_name": obj["table_name"],
                        "head_name": obj["head_name"],
                        "bone": bone_name,
                        "vertex_index": vi,
                        "axis": "xyz"[axis],
                        "delta_world_fixed": delta,
                        "delta_world": delta / 256.0,
                        "incident_face_count": incident_count,
                        "before_world_fixed": list(old_w),
                        "requested_after_world_fixed": list(requested_t),
                        "expected_reimport_world_fixed": list(reimport),
                        "requested_reimport_error_fixed": pos_error,
                        "before_local_fixed": list(old_local),
                        "after_local_fixed": list(new_local),
                        "local_delta_fixed": list(local_delta),
                        "before_normal_endpoint_local_fixed": list(old_ep),
                        "after_normal_endpoint_local_fixed": list(new_ep),
                        "before_world_normal_vector_fixed": list(old_vec),
                        "after_world_normal_vector_fixed": list(new_vec),
                        "world_normal_vector_delta_fixed": list(normal_delta),
                        "world_normal_vector_max_delta_fixed": normal_error,
                        "normal_policy": "TRANSLATE_ENDPOINT_WITH_VERTEX_PRESERVE_HISTORICAL_NORMAL_VECTOR",
                        "bounds_header_policy": "PRESERVE_BYTE_IDENTICAL_INTERIOR_WITNESS",
                    }
                    choices.append((score, plan))
    if not choices:
        raise ValueError("no safe single-bone interior witness")
    choices.sort(key=lambda x: x[0])
    return choices[0][1]


def patch_single_bone_witness(source_physical: pathlib.Path, prepared_source: pathlib.Path,
                              output_physical: pathlib.Path, plan: dict[str, Any]) -> dict[str, Any]:
    model = _parse_with_offsets(prepared_source)
    oi = int(plan["object_index"]); vi = int(plan["vertex_index"])
    if not 0 <= oi < len(model["objects"]):
        raise ValueError("witness object OOB")
    obj = model["objects"][oi]
    if not 0 <= vi < len(obj["vertices"]):
        raise ValueError("witness vertex OOB")
    if len(set(obj["bones"])) != 1 or obj["bones"][vi] != plan["bone"]:
        raise ValueError("single-bone witness changed since planning")
    src = bytearray(pathlib.Path(source_physical).read_bytes())
    normalized = pathlib.Path(prepared_source).read_bytes()
    if len(src) != len(normalized):
        raise ValueError("physical/prepared size mismatch")
    off = int(obj["vertex_offset"]) + vi * SV
    old = struct.unpack_from("<6i", src, off)
    expected_old = tuple(plan["before_local_fixed"] + plan["before_normal_endpoint_local_fixed"])
    if old != expected_old:
        raise ValueError(f"source witness bytes changed: {old} != {expected_old}")
    new = tuple(plan["after_local_fixed"] + plan["after_normal_endpoint_local_fixed"])
    struct.pack_into("<6i", src, off, *new)
    output_physical.parent.mkdir(parents=True, exist_ok=True)
    output_physical.write_bytes(src)
    return {
        "vertex_record_offset": off,
        "allowed_byte_range": [off, off + SV],
        "old_record": list(old),
        "new_record": list(new),
    }


def compare_single_bone_output(source_physical: pathlib.Path, output_physical: pathlib.Path,
                               prepared_output: pathlib.Path, plan: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    sb = pathlib.Path(source_physical).read_bytes(); ob = pathlib.Path(output_physical).read_bytes()
    errors: list[str] = []
    if len(sb) != len(ob): errors.append("FILE_SIZE")
    if sb[:24] != ob[:24]: errors.append("PHYSICAL_HEADER24_CHANGED")
    lo, hi = patch["allowed_byte_range"]
    diff = [i for i, (a, b) in enumerate(zip(sb, ob)) if a != b]
    outside = [i for i in diff if not (lo <= i < hi)]
    if outside: errors.append("NON_WITNESS_BYTES_CHANGED")
    if not diff: errors.append("BYTE_IDENTICAL_AFTER_EDIT")
    out_model = _parse_with_offsets(prepared_output)
    obj = out_model["objects"][int(plan["object_index"])]
    v = obj["vertices"][int(plan["vertex_index"])]
    if tuple(v[:3]) != tuple(plan["after_local_fixed"]): errors.append("OUTPUT_POSITION")
    if tuple(v[3:6]) != tuple(plan["after_normal_endpoint_local_fixed"]): errors.append("OUTPUT_NORMAL_ENDPOINT")
    result = {
        "check": "PASS" if not errors else "FAIL",
        "errors": errors,
        "source_sha256": sha256_file(source_physical),
        "output_sha256": sha256_file(output_physical),
        "file_size": len(sb),
        "diff_byte_count": len(diff),
        "diff_bytes_outside_witness_record": outside,
        "physical_header24_byte_identical": sb[:24] == ob[:24],
        "all_non_witness_bytes_byte_identical": not outside and len(sb) == len(ob),
        "bounds_header_byte_identical": not any((int(obj["object_start"]) + 44) <= i < (int(obj["object_start"]) + 76) for i in diff),
        "physique_names_byte_identical": True,
        "texlink_face_material_animation_bytes_byte_identical": not outside,
        "client_modified": False,
    }
    if errors:
        raise RuntimeError("rare rigid single-bone compare failed: " + ",".join(errors))
    return result


def _binding_row(binding: dict[str, Any], logical: str) -> dict[str, Any]:
    rows = [r for r in binding.get("rows") or [] if low_path(r.get("logical") or "") == low_path(logical)]
    if len(rows) != 1:
        raise ValueError(f"binding row unresolved for {logical}")
    return rows[0]


def _run_one(*, reg, resolver, certifications, settings, project_root: pathlib.Path,
             binding: dict[str, Any], logical: str, work: pathlib.Path) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    base_preview_work = work / "base_preview"
    preview = _prepare_one_preview(
        reg=reg, resolver=resolver, certifications=certifications, settings=settings,
        project_root=project_root, binding=binding, logical=logical,
        work=base_preview_work, open_gui=False,
    )
    source = pathlib.Path(resolver.resolve(logical, required=True))
    prepared = base_preview_work / "prepared" / pathlib.PurePosixPath(logical)
    skeleton = pathlib.Path(resolver.resolve(preview["motion_smb"], required=True))
    model = _parse_with_offsets(prepared)
    bone_tms = _parse_skeleton_tms(skeleton)
    plan = choose_single_bone_witness(model, bone_tms)
    plan["logical"] = logical
    plan_path = work / "witness_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    witness_blend = work / "edited_witness.blend"
    witness_report = work / "blender_witness.json"
    witness_script = project_root / "pt_asset_tool/blender/witness_rare_rigid_geometry.py"
    run_logged(settings.blender_command() + [
        "--background", str(preview["preview_blend"]), "--python-exit-code", "1",
        "--python", str(witness_script), "--",
        "--plan", str(plan_path), "--out", str(witness_blend), "--report", str(witness_report),
    ], work / "03_blender_witness.log")
    wr = json.loads(witness_report.read_text(encoding="utf-8"))
    if wr.get("check") != "PASS":
        raise RuntimeError(f"Blender witness failed: {wr}")
    if list(wr.get("after_world_fixed") or []) != plan["requested_after_world_fixed"]:
        raise RuntimeError("Blender witness fixed coordinate differs from plan")

    output = work / "rebuilt_rare_single_bone.smd"
    patch = patch_single_bone_witness(source, prepared, output, plan)
    prepared_output = work / "prepared_output" / pathlib.PurePosixPath(logical)
    prepare_model062_tooling_source(output, prepared_output)
    binary = compare_single_bone_output(source, output, prepared_output, plan, patch)

    root_src = pathlib.Path(resolver.resolve(preview["root_model"], required=True))
    source_inx = pathlib.Path(resolver.resolve(preview["source_inxs"][0], required=True))
    target_inx = pathlib.Path(resolver.resolve(preview["target_inx"], required=True))
    overlay_root = base_preview_work / "textures" / "texture_overlay_client"
    if not overlay_root.is_dir():
        raise RuntimeError("base preview texture overlay missing")
    rebuilt_blend = work / "rebuilt_preview.blend"
    import_report = work / "rebuilt_import.json"
    importer_script = project_root / "pt_asset_tool/blender/import_rare_rigid_context.py"
    common = [
        "--importer", str(project_root / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src),
        "--skeleton", str(skeleton), "--rare-model-info", str(source_inx),
        "--root-model-info", str(target_inx), "--root-lod", str(preview["root_lod"]),
        "--rare-visibility-policy", str(preview["rare_visibility_policy"]),
        "--client-root", str(overlay_root), "--out", str(rebuilt_blend), "--report", str(import_report),
        "--logical", logical, "--root-logical", str(preview["root_model"]),
    ]
    run_logged(settings.blender_command() + [
        "--background", "--python-exit-code", "1", "--python", str(importer_script), "--", *common
    ], work / "04_rebuilt_import.log")
    imported = json.loads(import_report.read_text(encoding="utf-8"))
    if imported.get("check") != "PASS":
        raise RuntimeError(f"rebuilt import failed: {imported}")

    transport_report = work / "rebuilt_transport.json"
    checker = project_root / "pt_asset_tool/blender/check_rare_rigid_context.py"
    run_logged(settings.blender_command() + [
        "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(checker), "--",
        "--importer", str(project_root / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src), "--skeleton", str(skeleton),
        "--rare-model-info", str(source_inx), "--root-model-info", str(target_inx),
        "--root-lod", str(preview["root_lod"]), "--rare-visibility-policy", str(preview["rare_visibility_policy"]),
        "--report", str(transport_report),
    ], work / "05_rebuilt_transport.log")
    transport = json.loads(transport_report.read_text(encoding="utf-8"))
    if transport.get("check") != "PASS":
        raise RuntimeError(f"rebuilt transport failed: {transport}")

    witness_check = work / "rebuilt_witness_check.json"
    witness_checker = project_root / "pt_asset_tool/blender/check_rare_rigid_geometry_witness.py"
    run_logged(settings.blender_command() + [
        "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(witness_checker), "--",
        "--plan", str(plan_path), "--report", str(witness_check),
    ], work / "06_rebuilt_witness.log")
    wc = json.loads(witness_check.read_text(encoding="utf-8"))
    if wc.get("check") != "PASS":
        raise RuntimeError(f"rebuilt witness check failed: {wc}")

    cert = certifications.add(
        asset_id=str(getattr(reg.resolve(logical), "asset_id", "") or ("RARE::" + logical)),
        asset_path=logical, family="MODEL062_ALT_MAGIC_BODY_EXACT",
        test="RARE_RIGID_SINGLE_BONE_GEOMETRY_ROUNDTRIP", layer="AUTOMATIC", result="PASS",
        source_sha256=sha256_file(source), artifact_sha256=sha256_file(output),
        metadata={
            "write_scope": "SINGLE_BONE_INTERIOR_VERTEX_POSITION",
            "normal_policy": plan["normal_policy"],
            "object_index": plan["object_index"], "vertex_index": plan["vertex_index"],
            "local_delta_fixed": plan["local_delta_fixed"],
            "requested_reimport_error_fixed": plan["requested_reimport_error_fixed"],
            "world_normal_vector_max_delta_fixed": plan["world_normal_vector_max_delta_fixed"],
            "non_witness_bytes_byte_identical": binary["all_non_witness_bytes_byte_identical"],
            "bounds_header_byte_identical": binary["bounds_header_byte_identical"],
            "transport_check": transport.get("check"), "witness_check": wc.get("check"),
            "client_modified": False,
        },
    )
    return {
        "logical": logical,
        "check": "PASS",
        "object_index": plan["object_index"], "head_name": plan["head_name"],
        "bone": plan["bone"], "vertex_index": plan["vertex_index"],
        "delta_world": plan["delta_world"], "local_delta_fixed": plan["local_delta_fixed"],
        "requested_reimport_error_fixed": plan["requested_reimport_error_fixed"],
        "world_normal_vector_max_delta_fixed": plan["world_normal_vector_max_delta_fixed"],
        "normal_policy": plan["normal_policy"],
        "physical_header24_byte_identical": binary["physical_header24_byte_identical"],
        "all_non_witness_bytes_byte_identical": binary["all_non_witness_bytes_byte_identical"],
        "bounds_header_byte_identical": binary["bounds_header_byte_identical"],
        "transport_position_error": transport.get("max_position_abs_error"),
        "transport_uv_error": transport.get("max_uv_abs_error"),
        "physique_mismatch_count": transport.get("physique_mismatch_count"),
        "rebuilt_witness_world_fixed": wc.get("actual_world_fixed"),
        "rebuilt_smd": str(output), "rebuilt_blend": str(rebuilt_blend),
        "certification_id": cert["certification_id"], "client_modified": False,
    }


def audit_rare_rigid_single_bone_roundtrip(reg, resolver, certifications, settings, *, project_root: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    project_root = pathlib.Path(project_root); work = pathlib.Path(work); work.mkdir(parents=True, exist_ok=True)
    preflight = __import__("pt_asset_tool.rare_rigid_geometry", fromlist=["audit_rare_rigid_geometry_preflight"]).audit_rare_rigid_geometry_preflight(
        reg, resolver, project_root=project_root, work=work / "preflight_recheck"
    )
    if preflight.get("status") != "PASS" or set(map(low_path, preflight.get("single_bone_candidate_files") or [])) != set(map(low_path, CANDIDATES)):
        raise RuntimeError("V0.7.9 preflight recheck did not reproduce the five single-bone candidates")
    binding = audit_rare_rigid_binding(reg, resolver, project_root=project_root, work=work / "binding_recheck", bundle=None)
    if binding.get("status") != "PASS":
        raise RuntimeError("binding recheck failed")
    rows = []; errors = []
    for logical in CANDIDATES:
        try:
            rows.append(_run_one(
                reg=reg, resolver=resolver, certifications=certifications, settings=settings,
                project_root=project_root, binding=binding, logical=logical,
                work=work / pathlib.PurePosixPath(logical).name,
            ))
        except Exception as exc:
            errors.append({"logical": logical, "error": f"{type(exc).__name__}: {exc}"})
    passed = sum(r.get("check") == "PASS" for r in rows)
    result = {
        "format": "PT_RARE_RIGID_SINGLE_BONE_GEOMETRY_ROUNDTRIP_V1",
        "status": "PASS" if passed == len(CANDIDATES) and not errors else "FAIL",
        "expected": len(CANDIDATES), "audited": len(rows), "roundtrip_pass": passed,
        "single_bone_position_write_authorized": passed == len(CANDIDATES) and not errors,
        "write_scope": "SINGLE_BONE_INTERIOR_VERTEX_POSITION_WITH_HISTORICAL_NORMAL_VECTOR_LOCK",
        "arbitrary_geometry_write_authorized": False,
        "multi_bone_deferred": DEFERRED_MULTI_BONE,
        "normal_recompute_deferred": True,
        "max_requested_reimport_error_fixed": max([int(r.get("requested_reimport_error_fixed") or 0) for r in rows] or [0]),
        "max_world_normal_vector_delta_fixed": max([int(r.get("world_normal_vector_max_delta_fixed") or 0) for r in rows] or [0]),
        "non_witness_bytes_exact_files": sum(bool(r.get("all_non_witness_bytes_byte_identical")) for r in rows),
        "bounds_header_exact_files": sum(bool(r.get("bounds_header_byte_identical")) for r in rows),
        "physique_mismatch_total": sum(int(r.get("physique_mismatch_count") or 0) for r in rows),
        "errors": errors,
        "policy": {
            "position": "Blender bind-pose edit is quantized to fixed world, transformed by exact source smMatrixInvert, and only the selected serialized vertex is changed",
            "normal": "do not regenerate historical SetGNormals provenance; translate that vertex's serialized normal endpoint by the exact same local delta, preserving its historical normal vector (runtime fixed transform drift <=1)",
            "bounds": "first writer is interior-only; maxX/maxY/maxZ/dBound/Bound remain byte-identical",
            "untouched": "every byte outside the selected 24-byte smVERTEX record must remain byte-identical, including alternate magic, faces, TexLinks, materials, animation arrays and Physique names",
            "deferred": "neighbor normal recomputation, extent-changing edits and at_dragon multi-bone deformation require separate proof",
            "client_modified": False,
        },
        "rows": rows, "client_modified": False,
    }
    rp = work / "rare_rigid_single_bone_roundtrip_report.json"
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(rp)
    return result
