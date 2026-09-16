from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
from collections import Counter
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_edit import prepare_at_dragon_edit_workspace, _reimport_and_check_transaction
from .rare_rigid_geometry import _parse_skeleton_tms
from .rare_rigid_multibone_bridge import TARGET, _candidate_for_vertex, _combo
from .rare_rigid_normal_bridge import _build_source_normal_state
from .rare_rigid_roundtrip import _parse_with_offsets
from .rare_support import prepare_model062_tooling_source
from . import rare_rigid_multivertex as mv

FORMAT = "PT_RARE_RIGID_LARGE_TRANSACTION_PROBE_AUDIT_V1"
PROBE_COUNTS = (5, 6, 7, 8)
PROBE_MAX = max(PROBE_COUNTS)
BEAM_LIMIT = 256
from .certified_writers import CERTIFIED_WRITERS

EXPECTED_WRITER_HASHES = CERTIFIED_WRITERS


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(root / rel) for rel in EXPECTED_WRITER_HASHES}


def _safe_rows(prepared: pathlib.Path, skeleton: pathlib.Path) -> tuple[dict[int, list[dict[str, Any]]], dict[str, list[int]]]:
    model = _parse_with_offsets(prepared)
    bone_tms = _parse_skeleton_tms(skeleton)
    safe: dict[int, list[dict[str, Any]]] = {}
    for oi, obj in enumerate(model["objects"]):
        world = mv._world_positions_for_object(obj, bone_tms)
        state = _build_source_normal_state(world, obj["faces"])
        mixed: set[int] = set()
        for f in obj["faces"]:
            if len(_combo(obj, f)) > 1:
                mixed.update(int(v) for v in f[:3])
        rows: list[dict[str, Any]] = []
        for vi in sorted(mixed):
            p = _candidate_for_vertex(obj, bone_tms, world, state, vi)
            if p is not None:
                rows.append(p)
        if rows:
            safe[oi] = rows
    return safe, bone_tms


def _row_sets(row: dict[str, Any]) -> tuple[set[int], set[int]]:
    inc = {int(x) for x in row.get("incident_face_indices") or []}
    affected = {int(r["vertex_index"]) for r in row.get("affected_vertices") or [] if "vertex_index" in r}
    return inc, affected


def _candidate_pre_score(combo: tuple[int, ...], by_vi: dict[int, dict[str, Any]]) -> tuple[Any, ...]:
    shared_faces = 0
    neighborhood_overlap = 0
    bones: set[str] = set()
    total_target_error = 0
    total_position_error = 0
    total_normal_delta = 0
    sets = {vi: _row_sets(by_vi[vi]) for vi in combo}
    for vi in combo:
        row = by_vi[vi]
        bones.update(str(x) for x in row.get("affected_bones") or [])
        total_target_error += int(row.get("max_target_reimport_normal_error_fixed", 0))
        total_position_error += int(row.get("requested_reimport_error_fixed", 0))
        total_normal_delta += int(row.get("max_current_source_normal_delta_fixed", 0))
    for i, a in enumerate(combo):
        for b in combo[i + 1:]:
            ia, aa = sets[a]
            ib, ab = sets[b]
            if ia & ib:
                shared_faces += 1
            if aa & ab:
                neighborhood_overlap += 1
    return (
        -shared_faces,
        -neighborhood_overlap,
        -len(bones),
        total_target_error,
        total_position_error,
        total_normal_delta,
        combo,
    )


def _beam_candidate_sets(rows: list[dict[str, Any]], target: int, beam_limit: int = BEAM_LIMIT) -> list[tuple[int, ...]]:
    by_vi = {int(r["vertex_index"]): r for r in rows}
    vis = sorted(by_vi)
    if len(vis) < target:
        return []
    row_sets = {vi: _row_sets(by_vi[vi]) for vi in vis}
    adjacency: dict[int, set[int]] = {vi: set() for vi in vis}
    for i, a in enumerate(vis):
        ia, aa = row_sets[a]
        for b in vis[i + 1:]:
            ib, ab = row_sets[b]
            if (ia & ib) or (aa & ab):
                adjacency[a].add(b)
                adjacency[b].add(a)

    frontier = [(vi,) for vi in vis]
    for size in range(2, target + 1):
        expanded: set[tuple[int, ...]] = set()
        for combo in frontier:
            pool: set[int] = set()
            for vi in combo:
                pool.update(adjacency[vi])
            pool.difference_update(combo)
            for v in sorted(pool):
                expanded.add(tuple(sorted((*combo, v))))
        if not expanded:
            frontier = []
            break
        ranked = sorted(expanded, key=lambda c: _candidate_pre_score(c, by_vi))
        frontier = ranked[:beam_limit]

    candidates = list(frontier)
    # Deterministic fallback windows prevent a sparse overlap graph from hiding all probes.
    if len(candidates) < min(64, beam_limit):
        stride_max = min(8, max(1, len(vis) // target))
        extra: set[tuple[int, ...]] = set(candidates)
        for stride in range(1, stride_max + 1):
            for start in range(0, len(vis)):
                combo = tuple(vis[start + stride * k] for k in range(target) if start + stride * k < len(vis))
                if len(combo) == target:
                    extra.add(combo)
        candidates = sorted(extra, key=lambda c: _candidate_pre_score(c, by_vi))[:beam_limit]
    return candidates


def _plan_probe(prepared: pathlib.Path, skeleton: pathlib.Path, changes: list[dict[str, Any]]) -> dict[str, Any]:
    # Audit-only process-local widening. The installed artist writer source stays byte-identical
    # and still extracts/rejects anything beyond four vertices.
    old = mv.MAX_TRANSACTION_VERTICES
    try:
        mv.MAX_TRANSACTION_VERTICES = PROBE_MAX
        return mv.plan_requested_at_dragon_transaction(prepared, skeleton, changes=changes)
    finally:
        mv.MAX_TRANSACTION_VERTICES = old


def discover_large_representatives(prepared: pathlib.Path, skeleton: pathlib.Path) -> dict[str, Any]:
    safe_by_object, _ = _safe_rows(prepared, skeleton)
    reps: dict[str, dict[str, Any]] = {}
    attempts: dict[str, int] = {}
    rejected: dict[str, dict[str, int]] = {}
    for n in PROBE_COUNTS:
        ranked_candidates: list[tuple[tuple[Any, ...], int, tuple[int, ...]]] = []
        rows_by_object: dict[int, dict[int, dict[str, Any]]] = {}
        for oi, rows in sorted(safe_by_object.items()):
            by_vi = {int(r["vertex_index"]): r for r in rows}
            rows_by_object[oi] = by_vi
            for combo in _beam_candidate_sets(rows, n):
                ranked_candidates.append((_candidate_pre_score(combo, by_vi), oi, combo))
        ranked_candidates.sort(key=lambda x: (x[0], x[1], x[2]))

        reasons: Counter[str] = Counter()
        count = 0
        best: dict[str, Any] | None = None
        # The pre-score already prefers overlapping neighborhoods and bone diversity.
        # Stop at the first physical joint plan that passes, avoiding thousands of
        # repeated full SMD/skeleton parses merely to optimize an audit witness.
        for _, oi, combo in ranked_candidates[:BEAM_LIMIT]:
            count += 1
            by_vi = rows_by_object[oi]
            changes = [
                {
                    "object_index": oi,
                    "vertex_index": vi,
                    "before_world_fixed": list(by_vi[vi]["before_world_fixed"]),
                    "after_world_fixed": list(by_vi[vi]["requested_after_world_fixed"]),
                }
                for vi in combo
            ]
            try:
                best = _plan_probe(prepared, skeleton, changes)
                break
            except Exception as exc:
                reasons[str(exc).split(":", 1)[0]] += 1
        attempts[str(n)] = count
        rejected[str(n)] = dict(reasons.most_common(12))
        if best is not None:
            reps[f"vertices_{n}"] = best
    return {
        "representatives": reps,
        "attempts": attempts,
        "top_rejections": rejected,
        "safe_vertices_by_object": {str(oi): len(rows) for oi, rows in safe_by_object.items()},
        "complete": all(f"vertices_{n}" in reps for n in PROBE_COUNTS),
    }


def run_probe(project_root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + "_workspace")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    writer_before = _writer_hashes(project_root)
    if writer_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError(f"CERTIFIED_WRITER_HASH_MISMATCH:{writer_before}")

    settings = Settings.discover(project_root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    cert = CertificationRegistry(settings.certifications_dir)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)

    isolated = work / "isolated_artist_workspace"
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, cert, settings,
        project_root=project_root, open_gui=False, reset=True,
        workspace_root=isolated, workspace_origin="AUDIT_LARGE_TRANSACTION_PROBE",
    )
    prepared = pathlib.Path(manifest["prepared_source"])
    skeleton = pathlib.Path(manifest["skeleton"])
    discovery = discover_large_representatives(prepared, skeleton)
    if not discovery.get("complete"):
        raise RuntimeError(f"LARGE_TRANSACTION_REPRESENTATIVES_INCOMPLETE:{discovery}")

    preview = json.loads((isolated / "base_preview" / "summary.json").read_text(encoding="utf-8"))
    bone_tms = _parse_skeleton_tms(skeleton)
    rows: list[dict[str, Any]] = []

    for n in PROBE_COUNTS:
        plan = discovery["representatives"][f"vertices_{n}"]
        staging = work / f"transaction_{n}.smd.probe_staging"
        final_output = work / f"transaction_{n}.smd"
        prepared_output = work / f"prepared_transaction_{n}.smd"
        for p in (staging, final_output, prepared_output):
            p.unlink(missing_ok=True)
        patch = mv.patch_guarded_multivertex(source, prepared, staging, plan)
        prepare_model062_tooling_source(staging, prepared_output)
        binary = mv.compare_guarded_multivertex(source, staging, prepared_output, plan, patch, bone_tms)
        validation = _reimport_and_check_transaction(
            reg=reg, resolver=resolver, certifications=cert, settings=settings,
            project_root=project_root, preview=preview, skeleton=skeleton,
            prepared_output=prepared_output, plan=plan, work=work / f"validation_{n}",
        )
        # Probe atomicity: publish only after every check above has passed.
        staging.replace(final_output)
        rows.append({
            "changed_vertex_count": n,
            "check": "PASS",
            "object_index": plan["object_index"],
            "changed_vertex_indices": plan["changed_vertex_indices"],
            "changed_vertex_pairs_sharing_face": plan["changed_vertex_pairs_sharing_face"],
            "affected_bone_count": plan["affected_bone_count"],
            "affected_bones": plan["affected_bones"],
            "max_requested_reimport_error_fixed": plan["max_requested_reimport_error_fixed"],
            "max_current_source_normal_delta_fixed": plan["max_current_source_normal_delta_fixed"],
            "max_target_reimport_normal_error_fixed": plan["max_target_reimport_normal_error_fixed"],
            "non_authorized_bytes_exact": binary["all_non_authorized_bytes_byte_identical"],
            "bounds_exact": binary["bounds_header_byte_identical"],
            "binary_diff_byte_count": binary["diff_byte_count"],
            "blender_reimport_pass": True,
            "transaction_witness_pass": validation["witness"].get("check") == "PASS",
            "transport_pass": validation["transport"].get("check") == "PASS",
            "atomic_probe_publish": True,
            "output_smd": str(final_output),
            "output_sha256": _sha256(final_output),
        })

    # Negative control: force one member of the five-vertex witness outside historical bounds.
    neg = json.loads(json.dumps(discovery["representatives"]["vertices_5"]))
    neg_changes = []
    for i, r in enumerate(neg["changed_vertices"]):
        after = list(r["requested_after_world_fixed"])
        if i == 0:
            after[0] += 1_000_000
        neg_changes.append({
            "object_index": neg["object_index"],
            "vertex_index": int(r["vertex_index"]),
            "before_world_fixed": list(r["before_world_fixed"]),
            "after_world_fixed": after,
        })
    negative_blocked = False
    negative_error = ""
    try:
        _plan_probe(prepared, skeleton, neg_changes)
    except Exception as exc:
        negative_blocked = True
        negative_error = str(exc)

    writer_after = _writer_hashes(project_root)
    source_sha_after = _sha256(source)
    writer_unchanged = writer_before == writer_after == EXPECTED_WRITER_HASHES
    client_unchanged = source_sha_before == source_sha_after
    complete = (
        len(rows) == len(PROBE_COUNTS)
        and all(r["check"] == "PASS" for r in rows)
        and all(r["non_authorized_bytes_exact"] and r["bounds_exact"] for r in rows)
        and all(r["blender_reimport_pass"] and r["transaction_witness_pass"] and r["transport_pass"] for r in rows)
        and negative_blocked
        and writer_unchanged
        and client_unchanged
    )
    return {
        "format": FORMAT,
        "status": "PASS" if complete else "FAIL",
        "logical": TARGET,
        "release_version": "0.8.14",
        "base_consolidated_release": "0.8.13",
        "probe_vertex_counts": list(PROBE_COUNTS),
        "probe_representatives_complete": bool(discovery.get("complete")),
        "representative_attempts": discovery.get("attempts"),
        "representative_top_rejections": discovery.get("top_rejections"),
        "safe_vertices_by_object": discovery.get("safe_vertices_by_object"),
        "rows": rows,
        "negative_transaction_blocked": negative_blocked,
        "negative_transaction_error": negative_error,
        "certified_writer_hashes_before": writer_before,
        "certified_writer_hashes_after": writer_after,
        "writer_modules_modified": not writer_unchanged,
        "client_source_sha256_before": source_sha_before,
        "client_source_sha256_after": source_sha_after,
        "client_modified": not client_unchanged,
        "artist_writer_max_vertices": 4,
        "large_transaction_write_authorized": False,
        "policy": {
            "scope": "audit-only physical joint transaction probe for 5..8 changed vertices in one at_dragon mesh object; interior only",
            "joint_normals": "all requested positions are installed into one final geometry before SetGNormals-derived normal deltas are calculated",
            "writer": "certified V0.8.9 artist writer remains byte-identical and capped at four vertices",
            "authorization": "PASS proves candidate roundtrip evidence only; it does not authorize artist writes above four vertices",
            "next_on_pass": "build an isolated candidate saved-Blender writer gate for 5..8 vertices before any live authorization",
            "deferred": "cross-object transactions, extent changes, topology, and live writes above four vertices remain fail-closed",
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit-only at_dragon 5..8 vertex joint transaction probe")
    ap.add_argument("--root", required=True)
    ap.add_argument("--output", required=True)
    ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).expanduser().resolve()
    try:
        report = run_probe(pathlib.Path(ns.root), out)
    except Exception as exc:
        report = {
            "format": FORMAT,
            "status": "FAIL",
            "release_version": "0.8.14",
            "error": f"{type(exc).__name__}:{exc}",
            "artist_writer_max_vertices": 4,
            "large_transaction_write_authorized": False,
            "writer_modules_modified": None,
            "client_modified": None,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") == "PASS":
        print("rare_rigid_large_transaction_probe=PASS counts=5,6,7,8 writer_max=4 write_authorized=false client_modified=false")
        return 0
    print("rare_rigid_large_transaction_probe=FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
