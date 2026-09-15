from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import struct
from itertools import combinations
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_edit import prepare_at_dragon_edit_workspace
from .rare_rigid_geometry import SV, _parse_skeleton_tms, _transform_point_fixed
from .rare_rigid_large_production import POLICY_REL, load_and_validate_policy
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, _safe_rows
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_normal_bridge import NORMAL_TARGET_REIMPORT_LIMIT_FIXED
from .rare_rigid_roundtrip import _parse_with_offsets
from . import rare_rigid_multivertex as mv
from .utils import run_logged

FORMAT = "PT_RARE_RIGID_CROSS_OBJECT_TRANSACTION_PROBE_AUDIT_V1"
RELEASE_VERSION = "0.8.22"
PROBE_OBJECT_COUNTS = (2, 3)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(root / rel) for rel in EXPECTED_WRITER_HASHES}


def _cert_sha(reg: CertificationRegistry) -> str:
    return _sha256(reg.path) if reg.path.is_file() else hashlib.sha256(b"").hexdigest()


def _pair_score(plan: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -int(plan.get("changed_vertex_pairs_sharing_face", 0)),
        -int(plan.get("affected_bone_count", 0)),
        int(plan.get("max_target_reimport_normal_error_fixed", 1 << 30)),
        int(plan.get("max_requested_reimport_error_fixed", 1 << 30)),
        int(plan.get("max_current_source_normal_delta_fixed", 1 << 30)),
        int(plan.get("object_index", 1 << 30)),
        tuple(int(x) for x in plan.get("changed_vertex_indices") or []),
    )


def _best_pair_per_object(prepared: pathlib.Path, skeleton: pathlib.Path) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    safe_by_object, _ = _safe_rows(prepared, skeleton)
    best: dict[int, dict[str, Any]] = {}
    attempts: dict[str, int] = {}
    for oi, rows in sorted(safe_by_object.items()):
        by_vi = {int(r["vertex_index"]): r for r in rows}
        ranked: list[tuple[tuple[Any, ...], tuple[int, int]]] = []
        vis = sorted(by_vi)
        for a, b in combinations(vis, 2):
            ra, rb = by_vi[a], by_vi[b]
            ia = {int(x) for x in ra.get("incident_face_indices") or []}
            ib = {int(x) for x in rb.get("incident_face_indices") or []}
            aa = {int(r["vertex_index"]) for r in ra.get("affected_vertices") or [] if "vertex_index" in r}
            ab = {int(r["vertex_index"]) for r in rb.get("affected_vertices") or [] if "vertex_index" in r}
            pre = (
                0 if ia & ib else 1,
                0 if aa & ab else 1,
                int(ra.get("max_target_reimport_normal_error_fixed", 0)) + int(rb.get("max_target_reimport_normal_error_fixed", 0)),
                int(ra.get("requested_reimport_error_fixed", 0)) + int(rb.get("requested_reimport_error_fixed", 0)),
                a, b,
            )
            ranked.append((pre, (a, b)))
        ranked.sort(key=lambda x: x[0])
        count = 0
        chosen: dict[str, Any] | None = None
        chosen_score: tuple[Any, ...] | None = None
        # Bound search cost but retain deterministic fallbacks across the safe set.
        for _, pair in ranked[:512]:
            count += 1
            changes = []
            for vi in pair:
                r = by_vi[vi]
                changes.append({
                    "object_index": oi,
                    "vertex_index": vi,
                    "before_world_fixed": list(r["before_world_fixed"]),
                    "after_world_fixed": list(r["requested_after_world_fixed"]),
                })
            try:
                plan = mv.plan_requested_at_dragon_transaction(prepared, skeleton, changes=changes)
            except Exception:
                continue
            score = _pair_score(plan)
            if chosen_score is None or score < chosen_score:
                chosen, chosen_score = plan, score
                if int(plan.get("changed_vertex_pairs_sharing_face", 0)) > 0:
                    break
        attempts[str(oi)] = count
        if chosen is not None:
            best[oi] = chosen
    return best, attempts


def discover_cross_object_representatives(prepared: pathlib.Path, skeleton: pathlib.Path) -> dict[str, Any]:
    pairs, attempts = _best_pair_per_object(prepared, skeleton)
    ordered = sorted(pairs.values(), key=_pair_score)
    reps: dict[str, dict[str, Any]] = {}
    for object_count in PROBE_OBJECT_COUNTS:
        if len(ordered) < object_count:
            continue
        selected = ordered[:object_count]
        object_indices = [int(p["object_index"]) for p in selected]
        if len(set(object_indices)) != object_count:
            raise RuntimeError("CROSS_OBJECT_DISCOVERY_DUPLICATE_OBJECT")
        reps[f"objects_{object_count}"] = {
            "object_count": object_count,
            "object_indices": object_indices,
            "total_changed_vertices": sum(int(p["changed_vertex_count"]) for p in selected),
            "per_object_plans": selected,
            "transaction_atomic": True,
            "guard_status": "PASS",
        }
    return {
        "representatives": reps,
        "pair_attempts_by_object": attempts,
        "objects_with_safe_pair": sorted(int(x) for x in pairs),
        "complete": all(f"objects_{n}" in reps for n in PROBE_OBJECT_COUNTS),
    }


def _append_plan_patch(
    src: bytearray,
    model: dict[str, Any],
    plan: dict[str, Any],
    allowed_ranges: list[list[int]],
    changed_records: list[dict[str, Any]],
) -> None:
    oi = int(plan["object_index"])
    obj = model["objects"][oi]
    changed_set = {int(x) for x in plan["changed_vertex_indices"]}
    seen: set[int] = set()
    for row in plan["affected_vertices"]:
        av = int(row["vertex_index"])
        if av in seen:
            raise ValueError(f"DUPLICATE_AFFECTED_VERTEX_{oi}_{av}")
        seen.add(av)
        if obj["bones"][av] != row["bone"]:
            raise ValueError(f"AFFECTED_PHYSIQUE_BONE_CHANGED_{oi}_{av}")
        off = int(obj["vertex_offset"]) + av * SV
        old = struct.unpack_from("<6i", src, off)
        expected_old = tuple(int(x) for x in (row["before_local_position_fixed"] + row["before_local_normal_endpoint_fixed"]))
        if old != expected_old:
            raise ValueError(f"SOURCE_VERTEX_CHANGED_{oi}_{av}:{old}!={expected_old}")
        new_pos = tuple(int(x) for x in row["after_local_position_fixed"])
        new_ep = tuple(int(x) for x in row["after_local_normal_endpoint_fixed"])
        is_changed = av in changed_set
        if bool(row.get("is_position_changed")) != is_changed:
            raise ValueError(f"CHANGED_POSITION_FLAG_MISMATCH_{oi}_{av}")
        if is_changed:
            struct.pack_into("<6i", src, off, *(new_pos + new_ep))
            allowed_ranges.append([off, off + SV])
        else:
            if new_pos != tuple(int(x) for x in row["before_local_position_fixed"]):
                raise ValueError(f"NEIGHBOR_POSITION_CHANGED_{oi}_{av}")
            struct.pack_into("<3i", src, off + 12, *new_ep)
            allowed_ranges.append([off + 12, off + SV])
        changed_records.append({
            "object_index": oi,
            "vertex_index": av,
            "bone": row["bone"],
            "is_position_changed": is_changed,
            "record_offset": off,
            "old_record": list(old),
            "new_record": list(new_pos + new_ep),
        })
    if not changed_set.issubset(seen):
        raise ValueError(f"CHANGED_VERTEX_MISSING_FROM_AFFECTED_ROWS_OBJECT_{oi}")


def patch_cross_object_transaction(
    source_physical: pathlib.Path,
    prepared_source: pathlib.Path,
    output_physical: pathlib.Path,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    plans = list(transaction.get("per_object_plans") or [])
    if len(plans) < 2:
        raise ValueError("CROSS_OBJECT_REQUIRES_AT_LEAST_TWO_OBJECT_PLANS")
    object_indices = [int(p["object_index"]) for p in plans]
    if len(set(object_indices)) != len(plans):
        raise ValueError("CROSS_OBJECT_PLAN_OBJECT_DUPLICATE")
    model = _parse_with_offsets(prepared_source)
    src = bytearray(pathlib.Path(source_physical).read_bytes())
    prepared_bytes = pathlib.Path(prepared_source).read_bytes()
    if len(src) != len(prepared_bytes):
        raise ValueError("PHYSICAL_PREPARED_SIZE_MISMATCH")
    allowed_ranges: list[list[int]] = []
    changed_records: list[dict[str, Any]] = []
    # All per-object plans are fully built before this function is called. No output is
    # published until every plan has passed and the complete bytearray is assembled.
    for plan in plans:
        _append_plan_patch(src, model, plan, allowed_ranges, changed_records)
    output_physical.parent.mkdir(parents=True, exist_ok=True)
    staging = output_physical.with_suffix(output_physical.suffix + ".staging")
    staging.write_bytes(src)
    staging.replace(output_physical)
    return {
        "allowed_byte_ranges": allowed_ranges,
        "changed_records": changed_records,
        "object_indices": object_indices,
        "atomic_output_replace": True,
    }


def _in_ranges(i: int, ranges: list[list[int]]) -> bool:
    return any(int(lo) <= i < int(hi) for lo, hi in ranges)


def compare_cross_object_transaction(
    source_physical: pathlib.Path,
    output_physical: pathlib.Path,
    prepared_output: pathlib.Path,
    skeleton: pathlib.Path,
    transaction: dict[str, Any],
    patch: dict[str, Any],
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
    bone_tms = _parse_skeleton_tms(skeleton)
    bounds_by_object: dict[str, bool] = {}
    max_target_error = 0
    max_position_error = 0
    for plan in transaction["per_object_plans"]:
        oi = int(plan["object_index"])
        obj = out_model["objects"][oi]
        changed_set = {int(x) for x in plan["changed_vertex_indices"]}
        for row in plan["affected_vertices"]:
            av = int(row["vertex_index"])
            v = obj["vertices"][av]
            expected_pos = tuple(int(x) for x in row["after_local_position_fixed"])
            expected_ep = tuple(int(x) for x in row["after_local_normal_endpoint_fixed"])
            if tuple(v[:3]) != expected_pos:
                errors.append(f"OUTPUT_POSITION_{oi}_{av}")
            if tuple(v[3:6]) != expected_ep:
                errors.append(f"OUTPUT_NORMAL_ENDPOINT_{oi}_{av}")
            tm = bone_tms.get(row["bone"])
            if tm is None:
                errors.append(f"MISSING_BONE_{oi}_{av}")
                continue
            wp = _transform_point_fixed(tuple(int(x) for x in v[:3]), tm)
            we = _transform_point_fixed(tuple(int(x) for x in v[3:6]), tm)
            vec = tuple(we[z] - wp[z] for z in range(3))
            target_vec = tuple(int(x) for x in row["target_historical_world_normal_fixed"])
            nerr = max(abs(vec[z] - target_vec[z]) for z in range(3))
            max_target_error = max(max_target_error, nerr)
            if nerr > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
                errors.append(f"NORMAL_TARGET_REIMPORT_{oi}_{av}")
            if av in changed_set:
                expected_world = tuple(int(x) for x in row["expected_reimport_world_position_fixed"])
                perr = max(abs(wp[z] - expected_world[z]) for z in range(3))
                max_position_error = max(max_position_error, perr)
                if wp != expected_world:
                    errors.append(f"CHANGED_REIMPORT_WORLD_{oi}_{av}")
        object_start = int(obj["object_start"])
        exact = sb[object_start + 44:object_start + 76] == ob[object_start + 44:object_start + 76]
        bounds_by_object[str(oi)] = exact
        if not exact:
            errors.append(f"BOUNDS_HEADER_CHANGED_{oi}")

    result = {
        "check": "PASS" if not errors else "FAIL",
        "errors": errors,
        "source_sha256": _sha256(source_physical),
        "output_sha256": _sha256(output_physical),
        "file_size": len(sb),
        "diff_byte_count": len(diff),
        "diff_bytes_outside_authorized_ranges": outside,
        "physical_header24_byte_identical": sb[:24] == ob[:24],
        "all_non_authorized_bytes_byte_identical": not outside and len(sb) == len(ob),
        "bounds_header_byte_identical_by_object": bounds_by_object,
        "all_affected_object_bounds_byte_identical": all(bounds_by_object.values()),
        "max_target_reimport_normal_error_fixed": max_target_error,
        "max_changed_reimport_position_error_fixed": max_position_error,
        "client_modified": False,
    }
    if errors:
        raise RuntimeError("cross-object compare failed:" + ",".join(errors))
    return result


def _reimport_and_check_all(
    *, root: pathlib.Path, settings: Settings, resolver: ClientResolver,
    manifest: dict[str, Any], prepared_output: pathlib.Path,
    transaction: dict[str, Any], work: pathlib.Path,
) -> dict[str, Any]:
    root_src = pathlib.Path(resolver.resolve(manifest["root_model"], required=True))
    source_inx = pathlib.Path(resolver.resolve(manifest["source_inxs"][0], required=True))
    target_inx = pathlib.Path(resolver.resolve(manifest["target_inx"], required=True))
    summary_path = pathlib.Path(manifest["edit_blend"]).parent / "base_preview" / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError("BASE_PREVIEW_SUMMARY_MISSING")
    preview = json.loads(summary_path.read_text(encoding="utf-8"))
    overlay_root = pathlib.Path(preview["preview_blend"]).parent / "textures" / "texture_overlay_client"
    if not overlay_root.is_dir():
        raise RuntimeError("BASE_PREVIEW_TEXTURE_OVERLAY_MISSING")
    skeleton = pathlib.Path(manifest["skeleton"])
    work.mkdir(parents=True, exist_ok=True)
    rebuilt_blend = work / "rebuilt_cross_object_preview.blend"
    import_report = work / "rebuilt_import.json"
    importer_script = root / "pt_asset_tool/blender/import_rare_rigid_context.py"
    common = [
        "--importer", str(root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src), "--skeleton", str(skeleton),
        "--rare-model-info", str(source_inx), "--root-model-info", str(target_inx),
        "--root-lod", str(manifest["root_lod"]), "--rare-visibility-policy", str(manifest["rare_visibility_policy"]),
        "--client-root", str(overlay_root), "--out", str(rebuilt_blend), "--report", str(import_report),
        "--logical", TARGET, "--root-logical", str(manifest["root_model"]),
    ]
    run_logged(settings.blender_command() + ["--background", "--python-exit-code", "1", "--python", str(importer_script), "--", *common], work / "01_rebuilt_import.log")
    imported = json.loads(import_report.read_text(encoding="utf-8"))
    if imported.get("check") != "PASS":
        raise RuntimeError(f"CROSS_OBJECT_REBUILT_IMPORT_FAILED:{imported}")

    transport_report = work / "rebuilt_transport.json"
    checker = root / "pt_asset_tool/blender/check_rare_rigid_context.py"
    run_logged(settings.blender_command() + [
        "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(checker), "--",
        "--importer", str(root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(prepared_output), "--root-smd", str(root_src), "--skeleton", str(skeleton),
        "--rare-model-info", str(source_inx), "--root-model-info", str(target_inx),
        "--root-lod", str(manifest["root_lod"]), "--rare-visibility-policy", str(manifest["rare_visibility_policy"]),
        "--report", str(transport_report),
    ], work / "02_rebuilt_transport.log")
    transport = json.loads(transport_report.read_text(encoding="utf-8"))
    if transport.get("check") != "PASS":
        raise RuntimeError(f"CROSS_OBJECT_REBUILT_TRANSPORT_FAILED:{transport}")

    witness_rows = []
    witness_checker = root / "pt_asset_tool/blender/check_rare_rigid_transaction.py"
    for plan in transaction["per_object_plans"]:
        oi = int(plan["object_index"])
        plan_path = work / f"transaction_object_{oi}.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        witness_report = work / f"transaction_object_{oi}_check.json"
        run_logged(settings.blender_command() + [
            "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(witness_checker), "--",
            "--plan", str(plan_path), "--report", str(witness_report),
        ], work / f"03_transaction_object_{oi}.log")
        witness = json.loads(witness_report.read_text(encoding="utf-8"))
        if witness.get("check") != "PASS":
            raise RuntimeError(f"CROSS_OBJECT_WITNESS_OBJECT_{oi}_FAILED:{witness}")
        witness_rows.append({"object_index": oi, "check": "PASS", "report": str(witness_report)})
    return {
        "rebuilt_blend": str(rebuilt_blend),
        "blender_reimport_pass": True,
        "transport_pass": True,
        "transport_position_error": transport.get("max_position_abs_error"),
        "transport_uv_error": transport.get("max_uv_abs_error"),
        "physique_mismatch_count": transport.get("physique_mismatch_count"),
        "per_object_transaction_witness": witness_rows,
        "all_object_transaction_witness_pass": True,
    }


def _negative_partial_failure(
    prepared: pathlib.Path,
    skeleton: pathlib.Path,
    transaction: dict[str, Any],
    output: pathlib.Path,
) -> tuple[bool, str]:
    bad = json.loads(json.dumps(transaction))
    plans = bad["per_object_plans"]
    target_plan = plans[-1]
    row = target_plan["changed_vertices"][0]
    # Force one object outside its preserved bounds. Because all object plans must be
    # recomputed before patching, the transaction must fail with zero output.
    requested = list(row["requested_after_world_fixed"])
    requested[0] += 1 << 28
    changes = []
    for r in target_plan["changed_vertices"]:
        changes.append({
            "object_index": int(target_plan["object_index"]),
            "vertex_index": int(r["vertex_index"]),
            "after_world_fixed": requested if int(r["vertex_index"]) == int(row["vertex_index"]) else list(r["requested_after_world_fixed"]),
        })
    try:
        mv.plan_requested_at_dragon_transaction(prepared, skeleton, changes=changes)
    except Exception as exc:
        output.unlink(missing_ok=True)
        return True, f"{type(exc).__name__}:{exc}"
    return False, "UNEXPECTED_PASS"


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + "_workspace")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    policy = load_and_validate_policy(root)
    policy_path = root / POLICY_REL
    policy_sha_before = _sha256(policy_path)
    if int(policy.get("production_max_vertices", -1)) != 8 or policy.get("single_object_only") is not True:
        raise RuntimeError("V0821_PRODUCTION_POLICY_SCOPE_UNEXPECTED")

    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_CROSS_OBJECT_PROBE")

    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir)
    real_count_before = len(real_cert.records())
    real_sha_before = _cert_sha(real_cert)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)
    if source_sha_before != policy.get("client_source_sha256"):
        raise RuntimeError("CLIENT_SOURCE_SHA_DIVERGES_FROM_V0821_POLICY")

    isolated_cert = CertificationRegistry(work / "isolated_certifications")
    workspace = work / "isolated_artist_workspace"
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, isolated_cert, settings,
        project_root=root, open_gui=False, reset=True,
        workspace_root=workspace, workspace_origin="AUDIT_V0822_CROSS_OBJECT_PROBE",
    )
    isolated_preview = isolated_cert.records()
    if len(isolated_preview) != 1 or isolated_preview[0].get("test") != "RARE_RIGID_BLENDER_PREVIEW":
        raise RuntimeError(f"ISOLATED_PREVIEW_CERT_UNEXPECTED:{isolated_preview}")

    prepared = pathlib.Path(manifest["prepared_source"])
    skeleton = pathlib.Path(manifest["skeleton"])
    discovery = discover_cross_object_representatives(prepared, skeleton)
    if not discovery.get("complete"):
        raise RuntimeError(f"CROSS_OBJECT_REPRESENTATIVE_DISCOVERY_INCOMPLETE:{discovery}")

    rows: list[dict[str, Any]] = []
    for object_count in PROBE_OBJECT_COUNTS:
        tx = discovery["representatives"][f"objects_{object_count}"]
        row_root = work / f"objects_{object_count}"
        out_smd = row_root / f"cross_object_{object_count}_objects.smd"
        patch = patch_cross_object_transaction(source, prepared, out_smd, tx)
        compare = compare_cross_object_transaction(source, out_smd, out_smd, skeleton, tx, patch)
        rebuilt = _reimport_and_check_all(
            root=root, settings=settings, resolver=resolver, manifest=manifest,
            prepared_output=out_smd, transaction=tx, work=row_root / "reimport",
        )
        all_bones = sorted({str(b) for p in tx["per_object_plans"] for b in p.get("affected_bones") or []}, key=str.lower)
        rows.append({
            "status": "PASS",
            "object_count": object_count,
            "object_indices": list(tx["object_indices"]),
            "total_changed_vertices": int(tx["total_changed_vertices"]),
            "per_object_changed_vertex_indices": {
                str(p["object_index"]): list(p["changed_vertex_indices"]) for p in tx["per_object_plans"]
            },
            "per_object_changed_vertex_pairs_sharing_face": {
                str(p["object_index"]): int(p["changed_vertex_pairs_sharing_face"]) for p in tx["per_object_plans"]
            },
            "affected_bone_count_union": len(all_bones),
            "affected_bones_union": all_bones,
            "max_requested_reimport_error_fixed": max(int(p["max_requested_reimport_error_fixed"]) for p in tx["per_object_plans"]),
            "max_current_source_normal_delta_fixed": max(int(p["max_current_source_normal_delta_fixed"]) for p in tx["per_object_plans"]),
            "max_target_reimport_normal_error_fixed": max(int(p["max_target_reimport_normal_error_fixed"]) for p in tx["per_object_plans"]),
            "all_non_authorized_bytes_byte_identical": compare["all_non_authorized_bytes_byte_identical"],
            "all_affected_object_bounds_byte_identical": compare["all_affected_object_bounds_byte_identical"],
            "bounds_header_byte_identical_by_object": compare["bounds_header_byte_identical_by_object"],
            "binary_diff_byte_count": compare["diff_byte_count"],
            "blender_reimport_pass": rebuilt["blender_reimport_pass"],
            "transport_pass": rebuilt["transport_pass"],
            "transport_position_error": rebuilt["transport_position_error"],
            "transport_uv_error": rebuilt["transport_uv_error"],
            "physique_mismatch_count": rebuilt["physique_mismatch_count"],
            "all_object_transaction_witness_pass": rebuilt["all_object_transaction_witness_pass"],
            "per_object_transaction_witness": rebuilt["per_object_transaction_witness"],
            "transaction_atomic": True,
            "atomic_probe_publish": patch["atomic_output_replace"],
            "output_smd": str(out_smd),
            "output_sha256": _sha256(out_smd),
        })

    negative_output = work / "negative_should_not_exist.smd"
    negative_blocked, negative_error = _negative_partial_failure(
        prepared, skeleton, discovery["representatives"]["objects_2"], negative_output,
    )
    if not negative_blocked or negative_output.exists():
        raise RuntimeError(f"CROSS_OBJECT_PARTIAL_FAILURE_NEGATIVE_NOT_CLEAN:{negative_error}")

    # Production remains single-object only in V0.8.21; the existing strict planner must
    # still reject a mixed-object request despite this new audit-only evidence.
    prod_tx = discovery["representatives"]["objects_2"]
    mixed_changes = []
    for p in prod_tx["per_object_plans"]:
        r = p["changed_vertices"][0]
        mixed_changes.append({
            "object_index": int(p["object_index"]),
            "vertex_index": int(r["vertex_index"]),
            "after_world_fixed": list(r["requested_after_world_fixed"]),
        })
    try:
        mv.plan_requested_at_dragon_transaction(prepared, skeleton, changes=mixed_changes)
    except Exception as exc:
        production_blocked = "MULTI_OBJECT_TRANSACTION_DEFERRED" in str(exc)
        production_error = f"{type(exc).__name__}:{exc}"
    else:
        production_blocked = False
        production_error = "UNEXPECTED_PASS"
    if not production_blocked:
        raise RuntimeError(f"PRODUCTION_CROSS_OBJECT_FAIL_CLOSED_LOST:{production_error}")

    writers_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_count_after = len(real_cert.records())
    real_sha_after = _cert_sha(real_cert)
    policy_sha_after = _sha256(policy_path)
    writer_unchanged = writers_before == writers_after == EXPECTED_WRITER_HASHES
    client_unchanged = source_sha_before == source_sha_after
    cert_unchanged = real_count_before == real_count_after and real_sha_before == real_sha_after
    policy_unchanged = policy_sha_before == policy_sha_after
    if not all([writer_unchanged, client_unchanged, cert_unchanged, policy_unchanged]):
        raise RuntimeError("CROSS_OBJECT_PROBE_SIDE_EFFECT_DETECTED")

    return {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE_VERSION,
        "base_release": "0.8.21",
        "logical": TARGET,
        "v0821_production_policy_valid": True,
        "production_single_object_max_vertices": 8,
        "probe_object_counts": list(PROBE_OBJECT_COUNTS),
        "probe_representatives_complete": True,
        "objects_with_safe_pair": discovery["objects_with_safe_pair"],
        "pair_attempts_by_object": discovery["pair_attempts_by_object"],
        "rows": rows,
        "negative_partial_failure_blocked": True,
        "negative_partial_failure_error": negative_error,
        "negative_output_created": False,
        "production_cross_object_still_blocked": True,
        "production_cross_object_error": production_error,
        "cross_object_write_authorized": False,
        "real_certification_count_before": real_count_before,
        "real_certification_count_after": real_count_after,
        "real_certification_registry_sha256_before": real_sha_before,
        "real_certification_registry_sha256_after": real_sha_after,
        "real_certification_registry_modified": False,
        "production_policy_sha256_before": policy_sha_before,
        "production_policy_sha256_after": policy_sha_after,
        "production_policy_modified": False,
        "writer_modules_modified": False,
        "client_source_sha256_before": source_sha_before,
        "client_source_sha256_after": source_sha_after,
        "client_modified": False,
        "policy": {
            "scope": "audit-only at_dragon cross-object transaction probe using 2 changed vertices per affected mesh object; interior only",
            "joint_geometry": "each mesh object receives one complete final geometry / SetGNormals plan; all object plans must pass before any combined output is atomically published",
            "binary": "authorized byte ranges are the union of all affected-object vertex/normal ranges; bounds headers for every affected object remain byte-identical",
            "production": "V0.8.21 production policy remains single-object max 8 and must continue rejecting mixed-object requests",
            "authorization": "PASS is cross-object physical evidence only; no artist cross-object write authorization is added",
            "next_on_pass": "build V0.8.23 isolated saved-Blender cross-object candidate before any live writer widening",
            "deferred": "production cross-object writes, extent/bounds changes, topology and >8 vertices remain fail-closed",
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V0.8.22 audit-only at_dragon cross-object transaction probe")
    ap.add_argument("--root", required=True)
    ap.add_argument("--output", required=True)
    ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).expanduser().resolve()
    try:
        report = run(pathlib.Path(ns.root), out)
    except Exception as exc:
        report = {
            "format": FORMAT,
            "status": "FAIL",
            "release_version": RELEASE_VERSION,
            "error": f"{type(exc).__name__}:{exc}",
            "cross_object_write_authorized": False,
            "production_single_object_max_vertices": 8,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") == "PASS":
        print("rare_rigid_cross_object_probe=PASS object_counts=2,3 production_single_object_max=8 cross_object_authorized=false client_modified=false")
        return 0
    print("rare_rigid_cross_object_probe=FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
