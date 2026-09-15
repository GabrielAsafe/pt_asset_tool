from __future__ import annotations

import pathlib
import struct
from itertools import combinations
from typing import Any

from .rare_rigid_geometry import _invert_matrix_source, _parse_skeleton_tms, _transform_point_fixed
from .rare_rigid_multibone_bridge import TARGET, _combo, _candidate_for_vertex, SOURCE_NORMAL_DELTA_LIMIT_FIXED
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
from .rare_rigid_geometry import SV
from .utils import sha256_file

MIN_TRANSACTION_VERTICES = 2
MAX_TRANSACTION_VERTICES = 4


def _in_ranges(i: int, ranges: list[list[int]]) -> bool:
    return any(int(lo) <= i < int(hi) for lo, hi in ranges)


def _world_positions_for_object(obj: dict[str, Any], bone_tms: dict[str, list[int]]) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for vi, v in enumerate(obj["vertices"]):
        bone = obj["bones"][vi]
        tm = bone_tms.get(bone)
        if tm is None:
            raise ValueError(f"missing bone transform {bone!r}")
        out.append(_transform_point_fixed(tuple(int(x) for x in v[:3]), tm))
    return out


def plan_requested_at_dragon_transaction(
    prepared: pathlib.Path,
    skeleton: pathlib.Path,
    *,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute one joint at_dragon transaction from the final requested geometry.

    The critical property is that normals are NOT planned vertex-by-vertex.  All
    requested positions are installed into one final world-space geometry first,
    then the union of incident faces is evaluated exactly once.  This prevents two
    individually-safe edits from being incorrectly composed by addition.
    """
    if not (MIN_TRANSACTION_VERTICES <= len(changes) <= MAX_TRANSACTION_VERTICES):
        raise ValueError(f"TRANSACTION_VERTEX_COUNT_{len(changes)}_OUTSIDE_{MIN_TRANSACTION_VERTICES}_{MAX_TRANSACTION_VERTICES}")
    keys = [(int(c["object_index"]), int(c["vertex_index"])) for c in changes]
    if len(set(keys)) != len(keys):
        raise ValueError("DUPLICATE_TRANSACTION_VERTEX")
    object_indices = {oi for oi, _ in keys}
    if len(object_indices) != 1:
        raise ValueError("MULTI_OBJECT_TRANSACTION_DEFERRED")
    oi = next(iter(object_indices))

    model = _parse_with_offsets(prepared)
    bone_tms = _parse_skeleton_tms(skeleton)
    if not (0 <= oi < len(model["objects"])):
        raise ValueError("OBJECT_INDEX_OOB")
    obj = model["objects"][oi]
    world = _world_positions_for_object(obj, bone_tms)
    state = _build_source_normal_state(world, obj["faces"])

    requested_by_vi: dict[int, tuple[int, int, int]] = {}
    changed_meta: dict[int, dict[str, Any]] = {}
    incident_union: set[int] = set()
    mixed_incident_union: set[int] = set()

    for c in changes:
        vi = int(c["vertex_index"])
        if not (0 <= vi < len(obj["vertices"])):
            raise ValueError(f"VERTEX_INDEX_OOB_{vi}")
        incident = list(state["incidence"][vi])
        mixed_incident = [fi for fi in incident if len(_combo(obj, obj["faces"][fi])) > 1]
        if not mixed_incident:
            raise ValueError(f"EDIT_OUTSIDE_V084_MULTIBONE_SCOPE_{vi}")
        if state["current"][vi] is None:
            raise ValueError(f"SOURCE_NORMAL_STATE_UNRESOLVED_{vi}")
        requested = tuple(int(x) for x in c["after_world_fixed"])
        old_world = world[vi]
        if requested == old_world:
            raise ValueError(f"NO_POSITION_CHANGE_{vi}")
        if not _stored_bound_safe(requested, obj["stored_bounds"]):
            raise ValueError(f"EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED_{vi}")

        bone = obj["bones"][vi]
        tm = bone_tms.get(bone)
        if tm is None:
            raise ValueError(f"WITNESS_BONE_MISSING_{vi}")
        inv = _invert_matrix_source(tm)
        old_local = tuple(int(x) for x in obj["vertices"][vi][:3])
        new_local = _transform_point_fixed(requested, inv)
        if new_local == old_local:
            raise ValueError(f"EDIT_QUANTIZES_TO_ORIGINAL_LOCAL_POSITION_{vi}")
        if not all(_i32_safe(q) for q in new_local):
            raise ValueError(f"LOCAL_POSITION_INT32_OVERFLOW_{vi}")
        reimport = _transform_point_fixed(new_local, tm)
        pos_error = max(abs(reimport[z] - requested[z]) for z in range(3))
        if pos_error > POSITION_REIMPORT_LIMIT_FIXED:
            raise ValueError(f"POSITION_REIMPORT_ERROR_{vi}_{pos_error}_GT_{POSITION_REIMPORT_LIMIT_FIXED}")
        if not _stored_bound_safe(reimport, obj["stored_bounds"]):
            raise ValueError(f"REIMPORTED_POSITION_REQUIRES_BOUND_CHANGE_{vi}")

        requested_by_vi[vi] = requested
        changed_meta[vi] = {
            "vertex_index": vi,
            "bone": bone,
            "before_world_fixed": list(old_world),
            "requested_after_world_fixed": list(requested),
            "expected_reimport_world_fixed": list(reimport),
            "requested_reimport_error_fixed": pos_error,
            "before_local_fixed": list(old_local),
            "after_local_fixed": list(new_local),
            "local_delta_fixed": [new_local[z] - old_local[z] for z in range(3)],
            "incident_face_indices": [int(x) for x in incident],
            "mixed_incident_face_indices": [int(x) for x in mixed_incident],
        }
        incident_union.update(incident)
        mixed_incident_union.update(mixed_incident)

    # Final requested geometry first; one SetGNormals delta is then derived from it.
    world2 = list(world)
    for vi, requested in requested_by_vi.items():
        world2[vi] = requested

    changed_face_normals: dict[int, tuple[int, int, int]] = {}
    affected: set[int] = set()
    for fi in sorted(incident_union):
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
    changed_set = set(requested_by_vi)
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
        desired_pos = requested_by_vi.get(av, world[av])
        target_ep_world = tuple(desired_pos[z] + target_vec[z] for z in range(3))
        local_ep = _transform_point_fixed(target_ep_world, av_inv)
        if not all(_i32_safe(q) for q in local_ep):
            raise ValueError(f"NORMAL_ENDPOINT_INT32_OVERFLOW_{av}")
        actual_ep_world = _transform_point_fixed(local_ep, av_tm)
        actual_pos_world = tuple(changed_meta[av]["expected_reimport_world_fixed"]) if av in changed_set else world[av]
        actual_vec = tuple(actual_ep_world[z] - actual_pos_world[z] for z in range(3))
        target_error = max(abs(actual_vec[z] - target_vec[z]) for z in range(3))
        target_error_max = max(target_error_max, target_error)
        after_local_position = tuple(changed_meta[av]["after_local_fixed"]) if av in changed_set else tuple(int(x) for x in av_vertex[:3])
        affected_rows.append({
            "vertex_index": av,
            "bone": av_bone,
            "is_position_changed": av in changed_set,
            "before_local_position_fixed": list(int(x) for x in av_vertex[:3]),
            "after_local_position_fixed": list(after_local_position),
            "before_local_normal_endpoint_fixed": list(int(x) for x in av_vertex[3:6]),
            "after_local_normal_endpoint_fixed": list(local_ep),
            "before_world_position_fixed": list(world[av]),
            "desired_world_position_fixed": list(desired_pos),
            "expected_reimport_world_position_fixed": list(actual_pos_world),
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
        raise ValueError("TRANSACTION_DOES_NOT_AFFECT_MULTIBONE_NEIGHBORHOOD")
    if source_delta_max == 0:
        raise ValueError("SOURCE_NORMAL_DELTA_ZERO")
    if source_delta_max > SOURCE_NORMAL_DELTA_LIMIT_FIXED:
        raise ValueError(f"SOURCE_NORMAL_DELTA_{source_delta_max}_GT_{SOURCE_NORMAL_DELTA_LIMIT_FIXED}")
    if target_error_max > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
        raise ValueError(f"NORMAL_REIMPORT_ERROR_{target_error_max}_GT_{NORMAL_TARGET_REIMPORT_LIMIT_FIXED}")

    mixed_combos = sorted({_combo(obj, obj["faces"][fi]) for fi in mixed_incident_union}, key=lambda x: tuple(s.lower() for s in x))
    changed_rows = [changed_meta[vi] for vi in sorted(changed_meta)]
    pair_shared_faces = 0
    for a, b in combinations(sorted(changed_set), 2):
        if set(changed_meta[a]["incident_face_indices"]) & set(changed_meta[b]["incident_face_indices"]):
            pair_shared_faces += 1
    return {
        "logical": TARGET,
        "object_index": oi,
        "table_name": obj["table_name"],
        "head_name": obj["head_name"],
        "changed_vertex_count": len(changed_rows),
        "changed_vertices": changed_rows,
        "changed_vertex_indices": [int(r["vertex_index"]) for r in changed_rows],
        "incident_face_indices": [int(x) for x in sorted(incident_union)],
        "mixed_incident_face_indices": [int(x) for x in sorted(mixed_incident_union)],
        "incident_face_count": len(incident_union),
        "mixed_incident_face_count": len(mixed_incident_union),
        "changed_vertex_pairs_sharing_face": pair_shared_faces,
        "mixed_incident_bone_combinations": [list(x) for x in mixed_combos],
        "affected_vertex_count": len(affected),
        "affected_bone_count": len(affected_bones),
        "affected_bones": sorted(affected_bones, key=str.lower),
        "affected_vertices": affected_rows,
        "max_requested_reimport_error_fixed": max(int(r["requested_reimport_error_fixed"]) for r in changed_rows),
        "max_current_source_normal_delta_fixed": source_delta_max,
        "max_target_reimport_normal_error_fixed": target_error_max,
        "normal_policy": "JOINT_FINAL_GEOMETRY_SETGNORMALS_ONCE_PLUS_PER_VERTEX_BONE_HISTORICAL_RESIDUAL",
        "bounds_header_policy": "PRESERVE_BYTE_IDENTICAL_INTERIOR_TRANSACTION",
        "transaction_atomic": True,
        "guard_status": "PASS",
    }


def patch_guarded_multivertex(
    source_physical: pathlib.Path,
    prepared_source: pathlib.Path,
    output_physical: pathlib.Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    model = _parse_with_offsets(prepared_source)
    oi = int(plan["object_index"])
    obj = model["objects"][oi]
    changed_set = {int(x) for x in plan["changed_vertex_indices"]}
    src = bytearray(pathlib.Path(source_physical).read_bytes())
    prepared_bytes = pathlib.Path(prepared_source).read_bytes()
    if len(src) != len(prepared_bytes):
        raise ValueError("physical/prepared size mismatch")

    allowed_ranges: list[list[int]] = []
    changed_records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in plan["affected_vertices"]:
        av = int(row["vertex_index"])
        if av in seen:
            raise ValueError(f"duplicate affected vertex {av}")
        seen.add(av)
        if obj["bones"][av] != row["bone"]:
            raise ValueError(f"affected vertex[{av}] Physique bone changed")
        off = int(obj["vertex_offset"]) + av * SV
        old = struct.unpack_from("<6i", src, off)
        expected_old = tuple(int(x) for x in (row["before_local_position_fixed"] + row["before_local_normal_endpoint_fixed"]))
        if old != expected_old:
            raise ValueError(f"source vertex[{av}] changed: {old} != {expected_old}")
        new_pos = tuple(int(x) for x in row["after_local_position_fixed"])
        new_ep = tuple(int(x) for x in row["after_local_normal_endpoint_fixed"])
        is_changed = av in changed_set
        if bool(row.get("is_position_changed")) != is_changed:
            raise ValueError(f"changed-position flag mismatch {av}")
        if is_changed:
            struct.pack_into("<6i", src, off, *(new_pos + new_ep))
            allowed_ranges.append([off, off + SV])
        else:
            if new_pos != tuple(int(x) for x in row["before_local_position_fixed"]):
                raise ValueError(f"neighbor vertex[{av}] position unexpectedly changed")
            struct.pack_into("<3i", src, off + 12, *new_ep)
            allowed_ranges.append([off + 12, off + SV])
        changed_records.append({"vertex_index": av, "bone": row["bone"], "is_position_changed": is_changed, "record_offset": off, "old_record": list(old), "new_record": list(new_pos + new_ep)})

    if not changed_set.issubset(seen):
        raise ValueError("changed vertex missing from affected rows")
    output_physical.parent.mkdir(parents=True, exist_ok=True)
    output_physical.write_bytes(src)
    return {"allowed_byte_ranges": allowed_ranges, "changed_records": changed_records}


def compare_guarded_multivertex(
    source_physical: pathlib.Path,
    output_physical: pathlib.Path,
    prepared_output: pathlib.Path,
    plan: dict[str, Any],
    patch: dict[str, Any],
    bone_tms: dict[str, list[int]],
) -> dict[str, Any]:
    sb = pathlib.Path(source_physical).read_bytes(); ob = pathlib.Path(output_physical).read_bytes()
    errors: list[str] = []
    if len(sb) != len(ob): errors.append("FILE_SIZE")
    if sb[:24] != ob[:24]: errors.append("PHYSICAL_HEADER24_CHANGED")
    diff = [i for i,(a,b) in enumerate(zip(sb,ob)) if a != b]
    outside = [i for i in diff if not _in_ranges(i, patch["allowed_byte_ranges"])]
    if outside: errors.append("NON_AUTHORIZED_BYTES_CHANGED")
    if not diff: errors.append("BYTE_IDENTICAL_AFTER_EDIT")

    out_model = _parse_with_offsets(prepared_output)
    obj = out_model["objects"][int(plan["object_index"])]
    max_target_error = 0; max_position_error = 0
    changed_set = {int(x) for x in plan["changed_vertex_indices"]}
    for row in plan["affected_vertices"]:
        av=int(row["vertex_index"]); v=obj["vertices"][av]
        expected_pos=tuple(int(x) for x in row["after_local_position_fixed"]); expected_ep=tuple(int(x) for x in row["after_local_normal_endpoint_fixed"])
        if tuple(v[:3]) != expected_pos: errors.append(f"OUTPUT_POSITION_{av}")
        if tuple(v[3:6]) != expected_ep: errors.append(f"OUTPUT_NORMAL_ENDPOINT_{av}")
        tm=bone_tms.get(row["bone"])
        if tm is None: errors.append(f"MISSING_BONE_{av}"); continue
        wp=_transform_point_fixed(tuple(int(x) for x in v[:3]),tm); we=_transform_point_fixed(tuple(int(x) for x in v[3:6]),tm)
        vec=tuple(we[z]-wp[z] for z in range(3)); target_vec=tuple(int(x) for x in row["target_historical_world_normal_fixed"])
        nerr=max(abs(vec[z]-target_vec[z]) for z in range(3)); max_target_error=max(max_target_error,nerr)
        if nerr > NORMAL_TARGET_REIMPORT_LIMIT_FIXED: errors.append(f"NORMAL_TARGET_REIMPORT_{av}")
        if av in changed_set:
            expected_world=tuple(int(x) for x in row["expected_reimport_world_position_fixed"])
            perr=max(abs(wp[z]-expected_world[z]) for z in range(3)); max_position_error=max(max_position_error,perr)
            if wp != expected_world: errors.append(f"CHANGED_REIMPORT_WORLD_{av}")

    object_start=int(obj["object_start"])
    bounds_exact=sb[object_start+44:object_start+76] == ob[object_start+44:object_start+76]
    if not bounds_exact: errors.append("BOUNDS_HEADER_CHANGED")
    result={
        "check":"PASS" if not errors else "FAIL", "errors":errors,
        "source_sha256":sha256_file(source_physical), "output_sha256":sha256_file(output_physical),
        "file_size":len(sb), "diff_byte_count":len(diff), "diff_bytes_outside_authorized_ranges":outside,
        "physical_header24_byte_identical":sb[:24]==ob[:24], "all_non_authorized_bytes_byte_identical":not outside and len(sb)==len(ob),
        "bounds_header_byte_identical":bounds_exact, "changed_vertex_count":len(changed_set),
        "max_target_reimport_normal_error_fixed":max_target_error, "max_changed_reimport_position_error_fixed":max_position_error,
        "client_modified":False,
    }
    if errors: raise RuntimeError("guarded multivertex compare failed: "+",".join(errors))
    return result


def discover_transaction_representatives(prepared: pathlib.Path, skeleton: pathlib.Path) -> dict[str, Any]:
    """Find deterministic 2/3/4-vertex joint witnesses from physical at_dragon.

    Preference is given to vertices whose incident neighborhoods overlap, because
    those are the cases that explicitly disprove naive composition of single-vertex
    witnesses and therefore provide the strongest transaction proof.
    """
    model=_parse_with_offsets(prepared); bone_tms=_parse_skeleton_tms(skeleton)
    safe_by_object: dict[int,list[dict[str,Any]]] = {}
    for oi,obj in enumerate(model["objects"]):
        world=_world_positions_for_object(obj,bone_tms); state=_build_source_normal_state(world,obj["faces"])
        mixed=set()
        for fi,f in enumerate(obj["faces"]):
            if len(_combo(obj,f))>1: mixed.update(int(v) for v in f[:3])
        rows=[]
        for vi in sorted(mixed):
            p=_candidate_for_vertex(obj,bone_tms,world,state,vi)
            if p is not None: rows.append(p)
        if rows: safe_by_object[oi]=rows

    reps: dict[str,dict[str,Any]] = {}
    attempts={2:0,3:0,4:0}
    # Build local adjacency from incident-face overlap. Limit neighborhoods to keep the
    # search deterministic and inexpensive on the 253 safe vertices.
    for n in (2,3,4):
        best=None; best_score=None
        for oi,rows in sorted(safe_by_object.items()):
            by_vi={int(r["vertex_index"]):r for r in rows}
            vis=sorted(by_vi)
            inc={vi:set(int(x) for x in by_vi[vi]["incident_face_indices"]) for vi in vis}
            neigh={vi:[vj for vj in vis if vj!=vi and (inc[vi]&inc[vj])] for vi in vis}
            candidate_sets=set()
            for vi in vis:
                pool=neigh[vi][:12]
                if len(pool) >= n-1:
                    for tail in combinations(pool,n-1): candidate_sets.add(tuple(sorted((vi,*tail))))
            # Fallback connected-through-affected neighborhood for sparse topology.
            if not candidate_sets:
                for combo in combinations(vis[:min(40,len(vis))],n): candidate_sets.add(tuple(combo))
            for combo in sorted(candidate_sets):
                attempts[n]+=1
                changes=[]
                for vi in combo:
                    r=by_vi[vi]
                    changes.append({"object_index":oi,"vertex_index":vi,"before_world_fixed":r["before_world_fixed"],"after_world_fixed":r["requested_after_world_fixed"]})
                try:
                    plan=plan_requested_at_dragon_transaction(prepared,skeleton,changes=changes)
                except Exception:
                    continue
                shared=int(plan["changed_vertex_pairs_sharing_face"])
                # Strongest evidence: shared faces, more bones, lower endpoint/position error,
                # and then smaller normal delta / deterministic indices.
                score=(-shared,-int(plan["affected_bone_count"]),int(plan["max_target_reimport_normal_error_fixed"]),int(plan["max_requested_reimport_error_fixed"]),int(plan["max_current_source_normal_delta_fixed"]),oi,combo)
                if best_score is None or score < best_score:
                    best_score=score; best=plan
        if best is not None: reps[f"vertices_{n}"]=best
    return {"representatives":reps,"attempts":{str(k):v for k,v in attempts.items()},"complete":all(f"vertices_{n}" in reps for n in (2,3,4))}


def discover_uniform_translation_pair(prepared: pathlib.Path, skeleton: pathlib.Path) -> dict[str, Any]:
    """Find a two-vertex shared-face transaction that an artist can apply with one G/axis/value operation."""
    model=_parse_with_offsets(prepared); bone_tms=_parse_skeleton_tms(skeleton)
    choices=[]
    for oi,obj in enumerate(model["objects"]):
        world=_world_positions_for_object(obj,bone_tms); state=_build_source_normal_state(world,obj["faces"])
        mixed=set()
        for f in obj["faces"]:
            if len(_combo(obj,f))>1: mixed.update(int(v) for v in f[:3])
        rows=[]
        for vi in sorted(mixed):
            p=_candidate_for_vertex(obj,bone_tms,world,state,vi)
            if p is not None: rows.append(p)
        groups: dict[tuple[str,int],list[dict[str,Any]]] = {}
        for r in rows: groups.setdefault((str(r["axis"]),int(r["delta_world_fixed"])),[]).append(r)
        for (axis,delta), group in groups.items():
            for a,b in combinations(group,2):
                if not (set(a["incident_face_indices"]) & set(b["incident_face_indices"])): continue
                changes=[
                    {"object_index":oi,"vertex_index":int(a["vertex_index"]),"after_world_fixed":list(a["requested_after_world_fixed"])},
                    {"object_index":oi,"vertex_index":int(b["vertex_index"]),"after_world_fixed":list(b["requested_after_world_fixed"])},
                ]
                try: plan=plan_requested_at_dragon_transaction(prepared,skeleton,changes=changes)
                except Exception: continue
                plan["uniform_axis"]=axis; plan["uniform_delta_world_fixed"]=delta; plan["uniform_delta_world"]=float(delta)/256.0
                score=(
                    int(plan["max_target_reimport_normal_error_fixed"]),
                    int(plan["max_requested_reimport_error_fixed"]),
                    int(plan["max_current_source_normal_delta_fixed"]),
                    -int(plan["affected_bone_count"]),
                    abs(delta),oi,tuple(plan["changed_vertex_indices"]),axis,
                )
                choices.append((score,plan))
    if not choices: raise RuntimeError("no uniform shared-face two-vertex transaction found")
    choices.sort(key=lambda x:x[0]); return choices[0][1]
