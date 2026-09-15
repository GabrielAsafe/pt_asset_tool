from __future__ import annotations

import json
import pathlib
from collections import Counter
from typing import Any

from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_geometry import _invert_matrix_source, _parse_skeleton_tms, _transform_point_fixed
from .rare_rigid_normal_bridge import (
    NORMAL_TARGET_REIMPORT_LIMIT_FIXED,
    POSITION_REIMPORT_LIMIT_FIXED,
    _build_source_normal_state,
    _face_normal_source,
    _i32_safe,
    _updated_current_for_affected,
    _world_hist_vector,
)
from .rare_rigid_roundtrip import _parse_with_offsets, _stored_bound_safe
from .rare_support import prepare_model062_tooling_source
from .utils import norm_path, sha256_file

TARGET = "char/tmABCD/at_dragon.smd"
# Diagnostic witness amplitudes only.  Writer authorization is intentionally
# NOT granted by this census; these moves probe the exact per-vertex-bone math.
WITNESS_DELTAS_FIXED = (64, -64, 128, -128, 256, -256, 512, -512)
SOURCE_NORMAL_DELTA_LIMIT_FIXED = 4096


def _combo(obj: dict[str, Any], face: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(sorted({obj["bones"][int(v)] for v in face[:3]}, key=str.lower))


def _candidate_for_vertex(
    obj: dict[str, Any],
    bone_tms: dict[str, list[int]],
    world: list[tuple[int, int, int]],
    state: dict[str, Any],
    vi: int,
) -> dict[str, Any] | None:
    incident = list(state["incidence"][vi])
    mixed_incident = [fi for fi in incident if len(_combo(obj, obj["faces"][fi])) > 1]
    if not mixed_incident or state["current"][vi] is None:
        return None

    vertex_bone = obj["bones"][vi]
    tm = bone_tms.get(vertex_bone)
    if tm is None:
        return None
    inv = _invert_matrix_source(tm)
    oldv = obj["vertices"][vi]
    old_local = tuple(int(x) for x in oldv[:3])
    old_world = world[vi]
    choices: list[tuple[tuple[int, ...], dict[str, Any]]] = []

    for delta in WITNESS_DELTAS_FIXED:
        for axis in (0, 2, 1):
            requested = list(old_world)
            requested[axis] += int(delta)
            requested_t = tuple(requested)
            if not _stored_bound_safe(requested_t, obj["stored_bounds"]):
                continue
            new_local = _transform_point_fixed(requested_t, inv)
            if new_local == old_local or not all(_i32_safe(q) for q in new_local):
                continue
            reimport = _transform_point_fixed(new_local, tm)
            pos_error = max(abs(reimport[z] - requested_t[z]) for z in range(3))
            if pos_error > POSITION_REIMPORT_LIMIT_FIXED or not _stored_bound_safe(reimport, obj["stored_bounds"]):
                continue

            world2 = list(world)
            world2[vi] = requested_t
            changed_face_normals: dict[int, tuple[int, int, int]] = {}
            affected: set[int] = set()
            valid = True
            for fi in incident:
                f = obj["faces"][fi]
                a, b, c = [int(x) for x in f[:3]]
                n = _face_normal_source(world2[a], world2[b], world2[c])
                if n is None:
                    valid = False
                    break
                changed_face_normals[fi] = n
                affected.update((a, b, c))
            if not valid or any(state["current"][av] is None for av in affected):
                continue
            current2 = _updated_current_for_affected(state, obj["faces"], changed_face_normals, affected)
            if current2 is None:
                continue

            affected_rows = []
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
                    valid = False
                    break
                av_inv = _invert_matrix_source(av_tm)
                av_vertex = obj["vertices"][av]
                old_hist = _world_hist_vector(av_vertex, av_tm)
                residual = tuple(old_hist[z] - before_current[z] for z in range(3))
                target_vec = tuple(after_current[z] + residual[z] for z in range(3))
                desired_pos = requested_t if av == vi else world[av]
                target_ep_world = tuple(desired_pos[z] + target_vec[z] for z in range(3))
                local_ep = _transform_point_fixed(target_ep_world, av_inv)
                if not all(_i32_safe(q) for q in local_ep):
                    valid = False
                    break
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
            if not valid:
                continue
            if source_delta_max == 0 or source_delta_max > SOURCE_NORMAL_DELTA_LIMIT_FIXED:
                continue
            if target_error_max > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
                continue

            mixed_combos = sorted({_combo(obj, obj["faces"][fi]) for fi in mixed_incident}, key=lambda x: tuple(s.lower() for s in x))
            plan = {
                "object_index": int(obj["index"]),
                "table_name": obj["table_name"],
                "head_name": obj["head_name"],
                "vertex_index": vi,
                "bone": vertex_bone,
                "axis": "xyz"[axis],
                "delta_world_fixed": int(delta),
                "delta_world": float(delta) / 256.0,
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
            }
            score = (
                target_error_max,
                pos_error,
                source_delta_max,
                abs(int(delta)),
                len(affected),
                -len(affected_bones),
                int(obj["index"]),
                vi,
                axis,
            )
            choices.append((score, plan))
    if not choices:
        return None
    choices.sort(key=lambda x: x[0])
    return choices[0][1]


def analyze_at_dragon_multibone(prepared: pathlib.Path, skeleton: pathlib.Path) -> dict[str, Any]:
    model = _parse_with_offsets(prepared)
    bone_tms = _parse_skeleton_tms(skeleton)

    total_vertices = sum(len(o["vertices"]) for o in model["objects"])
    total_faces = sum(len(o["faces"]) for o in model["objects"])
    mixed_faces: set[tuple[int, int]] = set()
    mixed_vertices: set[tuple[int, int]] = set()
    all_combos: Counter[tuple[str, ...]] = Counter()
    object_rows = []
    safe_by_vertex: dict[tuple[int, int], dict[str, Any]] = {}

    for oi, obj in enumerate(model["objects"]):
        tms = []
        world = []
        for vi, v in enumerate(obj["vertices"]):
            b = obj["bones"][vi]
            tm = bone_tms.get(b)
            if tm is None:
                raise ValueError(f"object[{oi}] missing skeleton bone {b!r}")
            tms.append(tm)
            world.append(_transform_point_fixed(tuple(int(x) for x in v[:3]), tm))
        state = _build_source_normal_state(world, obj["faces"])

        obj_mixed_faces = 0
        obj_mixed_vertices: set[int] = set()
        obj_combos: Counter[tuple[str, ...]] = Counter()
        for fi, f in enumerate(obj["faces"]):
            combo = _combo(obj, f)
            if len(combo) <= 1:
                continue
            obj_mixed_faces += 1
            mixed_faces.add((oi, fi))
            obj_combos[combo] += 1
            all_combos[combo] += 1
            for v in f[:3]:
                obj_mixed_vertices.add(int(v))
                mixed_vertices.add((oi, int(v)))

        safe_count = 0
        for vi in sorted(obj_mixed_vertices):
            plan = _candidate_for_vertex(obj, bone_tms, world, state, vi)
            if plan is not None:
                safe_by_vertex[(oi, vi)] = plan
                safe_count += 1

        object_rows.append({
            "object_index": oi,
            "head_name": obj["head_name"],
            "vertices": len(obj["vertices"]),
            "faces": len(obj["faces"]),
            "bind_bone_count": len(set(obj["bones"])),
            "mixed_bone_faces": obj_mixed_faces,
            "mixed_boundary_vertices": len(obj_mixed_vertices),
            "safe_mixed_boundary_vertices": safe_count,
            "mixed_bone_combinations": len(obj_combos),
        })

    covered_faces: set[tuple[int, int]] = set()
    covered_combos: set[tuple[str, ...]] = set()
    for oi, fi in mixed_faces:
        obj = model["objects"][oi]
        f = obj["faces"][fi]
        if any((oi, int(v)) in safe_by_vertex for v in f[:3]):
            covered_faces.add((oi, fi))
            covered_combos.add(_combo(obj, f))

    safe_plans = list(safe_by_vertex.values())
    reps: dict[str, dict[str, Any]] = {}
    for n in (2, 3, 4):
        candidates = [p for p in safe_plans if int(p["affected_bone_count"]) >= n]
        if candidates:
            candidates.sort(key=lambda p: (
                int(p["max_target_reimport_normal_error_fixed"]),
                int(p["requested_reimport_error_fixed"]),
                int(p["max_current_source_normal_delta_fixed"]),
                abs(int(p["delta_world_fixed"])),
                int(p["object_index"]), int(p["vertex_index"]),
            ))
            reps[f"affected_bones_ge_{n}"] = candidates[0]

    result = {
        "total_objects": len(model["objects"]),
        "total_vertices": total_vertices,
        "total_faces": total_faces,
        "bind_bones_used": len({b for o in model["objects"] for b in o["bones"]}),
        "mixed_bone_faces": len(mixed_faces),
        "mixed_boundary_vertices": len(mixed_vertices),
        "safe_mixed_boundary_vertices": len(safe_by_vertex),
        "blocked_mixed_boundary_vertices": len(mixed_vertices) - len(safe_by_vertex),
        "mixed_faces_with_safe_vertex": len(covered_faces),
        "mixed_faces_without_safe_vertex": len(mixed_faces) - len(covered_faces),
        "distinct_mixed_bone_combinations": len(all_combos),
        "safe_mixed_bone_combinations": len(covered_combos),
        "blocked_mixed_bone_combinations": len(all_combos) - len(covered_combos),
        "max_safe_requested_position_error_fixed": max([int(p["requested_reimport_error_fixed"]) for p in safe_plans] or [0]),
        "max_safe_source_normal_delta_fixed": max([int(p["max_current_source_normal_delta_fixed"]) for p in safe_plans] or [0]),
        "max_safe_target_reimport_normal_error_fixed": max([int(p["max_target_reimport_normal_error_fixed"]) for p in safe_plans] or [0]),
        "representative_witnesses": reps,
        "object_rows": object_rows,
        "mixed_combo_face_counts": [
            {"bones": list(k), "faces": int(v), "safe": k in covered_combos}
            for k, v in sorted(all_combos.items(), key=lambda kv: (-kv[1], tuple(s.lower() for s in kv[0])))
        ],
    }
    result["representative_2bone_found"] = "affected_bones_ge_2" in reps
    result["representative_3bone_found"] = "affected_bones_ge_3" in reps
    result["representative_4bone_found"] = "affected_bones_ge_4" in reps
    return result


def audit_rare_rigid_multibone_bridge(reg, resolver, *, project_root: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    project_root = pathlib.Path(project_root)
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)

    binding = audit_rare_rigid_binding(reg, resolver, project_root=project_root, work=work / "binding_recheck", bundle=None)
    if binding.get("status") != "PASS":
        return {
            "format": "PT_RARE_RIGID_MULTIBONE_BRIDGE_AUDIT_V1",
            "status": "FAIL",
            "error": "binding recheck failed",
            "multibone_geometry_write_authorized": False,
            "client_modified": False,
        }

    brow = next((r for r in binding.get("rows") or [] if norm_path(r.get("logical") or "").lower() == TARGET.lower()), None)
    if brow is None:
        raise RuntimeError("at_dragon binding row missing")
    if brow.get("binding_status") != "VERIFIED_INX_LINK_SKELETON":
        raise RuntimeError("at_dragon binding is not verified")

    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    prepared = work / "prepared" / pathlib.PurePosixPath(TARGET)
    prep = prepare_model062_tooling_source(source, prepared)
    motion = norm_path(brow.get("resolved_motion_smb") or "")
    skeleton = pathlib.Path(resolver.resolve(motion, required=True))
    analysis = analyze_at_dragon_multibone(prepared, skeleton)

    complete = (
        analysis["mixed_bone_faces"] == 628
        and analysis["bind_bones_used"] == 31
        and analysis["safe_mixed_boundary_vertices"] > 0
        and analysis["representative_2bone_found"]
        and analysis["representative_3bone_found"]
        and analysis["representative_4bone_found"]
        and analysis["max_safe_requested_position_error_fixed"] <= POSITION_REIMPORT_LIMIT_FIXED
        and analysis["max_safe_target_reimport_normal_error_fixed"] <= NORMAL_TARGET_REIMPORT_LIMIT_FIXED
    )
    result = {
        "format": "PT_RARE_RIGID_MULTIBONE_BRIDGE_AUDIT_V1",
        "status": "PASS" if complete else "FAIL",
        "logical": TARGET,
        "physical_family": prep["family"],
        "source_sha256": sha256_file(source),
        "motion_smb": motion,
        "motion_smb_sha256": sha256_file(skeleton),
        **analysis,
        "multibone_bridge_preflight_complete_candidate": complete,
        "guarded_multibone_writer_candidate": complete,
        "multibone_geometry_write_authorized": False,
        "extent_write_authorized": False,
        "topology_write_authorized": False,
        "source_findings": {
            "SetGNormals": "normals are computed in the common pre-ReformPhysique coordinate space before per-vertex bone inverse transforms",
            "ReformPhysique": "each vertex position and normal endpoint is serialized through the inverse matrix of that vertex's own Physique bone",
            "bridge": "for a changed mixed-bone face, preserve each affected vertex's historical residual independently, then serialize each target endpoint through that vertex's own bone inverse",
        },
        "policy": {
            "scope": "audit-only; this version proves a guarded per-vertex-bone bridge candidate but does not write at_dragon",
            "safe_subset": "a future writer may act only when the exact requested edit passes the same per-edit position, nondegenerate-face, int32, source-normal-delta and endpoint-reimport gates",
            "blocked_subset": "mixed-boundary vertices without a safe witness remain fail-closed; no interpolation across unsupported finger/arm boundaries is inferred",
            "bounds": "only interior witnesses are considered; extent changes remain separate",
            "topology": "unchanged",
            "client_modified": False,
        },
        "client_modified": False,
    }
    rp = work / "rare_rigid_multibone_bridge_audit_report.json"
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(rp)
    return result
