from __future__ import annotations

"""Physical corpus audit for Model0.62 static object-local hierarchy subtypes.

This audit intentionally reads the physical SMD object headers because the legacy
asset inventory retained object bounds/geometry counts, but not NodeParent,
nRot/nPos/nScale or per-object TmFrameCnt.  It is therefore the authoritative
bridge between inventory discovery and subtype certification.
"""

from collections import Counter, defaultdict
import json
import pathlib
import struct
import zipfile
from typing import Any

from .object_local_audit import audit_object_local
from .object_local import parse_object_local_smd

O_NODE_PARENT = 204
O_NROT = 684
O_NPOS = 688
O_NSCALE = 692
O_TM_FRAME_CNT = 2232
MIN_HEADER = 2236


def _cstring(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("latin1", "replace")


def _candidate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths = {
        x["path"]
        for x in audit_object_local(records, limit=10**9)["candidates"]
    }
    by_path = {str(r.get("relative_path") or ""): r for r in records}
    return [by_path[p] for p in sorted(paths, key=str.casefold) if p in by_path]


def _depths(rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    by_name = {}
    for x in rows:
        by_name.setdefault(str(x["name"]).casefold(), x)
    unresolved: list[str] = []
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(row: dict[str, Any]) -> int:
        key = str(row["name"]).casefold()
        if key in memo:
            return memo[key]
        if key in visiting:
            raise ValueError(f"NodeParent cycle at {row['name']!r}")
        visiting.add(key)
        pn = str(row.get("parent") or "")
        if not pn:
            d = 0
        else:
            parent = by_name.get(pn.casefold())
            if parent is None:
                unresolved.append(f"{row['name']}->{pn}")
                d = 0
            else:
                d = 1 + depth(parent)
        visiting.remove(key)
        memo[key] = d
        return d

    max_depth = 0
    for row in rows:
        max_depth = max(max_depth, depth(row))
    return max_depth, unresolved


def _shallow_file(record: dict[str, Any], physical: pathlib.Path) -> dict[str, Any]:
    data = physical.read_bytes()
    objects: list[dict[str, Any]] = []
    for obj in record.get("objects") or []:
        off = int(obj["obj_file_point"])
        if off < 0 or off + MIN_HEADER > len(data):
            raise ValueError(f"object header out of bounds: {obj.get('name')} off={off}")
        nr = struct.unpack_from("<i", data, off + O_NROT)[0]
        np = struct.unpack_from("<i", data, off + O_NPOS)[0]
        ns = struct.unpack_from("<i", data, off + O_NSCALE)[0]
        tf = struct.unpack_from("<i", data, off + O_TM_FRAME_CNT)[0]
        if min(nr, np, ns, tf) < 0:
            raise ValueError(f"negative transform count in {obj.get('name')}")
        parent = _cstring(data[off + O_NODE_PARENT: off + O_NODE_PARENT + 32])
        objects.append({
            "index": int(obj.get("index") or 0),
            "name": str(obj.get("node_name") or obj.get("name") or ""),
            "parent": parent,
            "nRot": nr,
            "nPos": np,
            "nScale": ns,
            "TmFrameCnt": tf,
            "serialized_curve_count": nr + np + ns,
        })

    max_depth, unresolved = _depths(objects)
    names = {str(x["name"]).casefold() for x in objects}
    declared_edges = [x for x in objects if x["parent"]]
    resolved_edges = [x for x in declared_edges if str(x["parent"]).casefold() in names]
    unresolved_edges = [x for x in declared_edges if str(x["parent"]).casefold() not in names]
    child_curve = [x for x in resolved_edges if x["serialized_curve_count"] > 0]
    unresolved_curve = [x for x in unresolved_edges if x["serialized_curve_count"] > 0]
    segmented = [x for x in objects if x["TmFrameCnt"] > 0]
    tags: list[str] = []
    if len(objects) == 1:
        tags.append("SINGLE_OBJECT")
    elif not resolved_edges:
        tags.append("FLAT_MULTI_INDEPENDENT")
    else:
        tags.append("HIERARCHICAL")
    if resolved_edges and not child_curve:
        tags.append("STATIC_CHILD_INHERIT")
    if child_curve:
        tags.append("CHILD_WITH_SERIALIZED_CURVES")
    if unresolved_curve:
        tags.append("UNRESOLVED_PARENT_WITH_CURVES_RUNTIME_ROOT")
    if segmented:
        tags.append("SEGMENTED_TMFRAME")
    if max_depth >= 2:
        tags.append("DEEP_HIERARCHY")
    if unresolved:
        tags.append("UNRESOLVED_PARENT")

    return {
        "path": str(record.get("relative_path") or ""),
        "category": str(record.get("category_hint") or "UNKNOWN"),
        "object_count": len(objects),
        "declared_parent_count": len(declared_edges),
        "parent_edge_count": len(resolved_edges),
        "runtime_unresolved_parent_count": len(unresolved_edges),
        "root_count": len(objects) - len(resolved_edges),
        "max_parent_depth": max_depth,
        "child_with_serialized_curves_count": len(child_curve),
        "unresolved_parent_with_curves_count": len(unresolved_curve),
        "segmented_object_count": len(segmented),
        "unresolved_parents": unresolved,
        "tags": tags,
        "objects": objects,
    }


def audit_object_local_physical_corpus(records, resolver, *, bundle: str | pathlib.Path | None = None,
                                       per_subtype: int = 3) -> dict[str, Any]:
    candidates = _candidate_records(records)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    tag_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    animated_child_paths: list[str] = []
    hold_child_paths: list[str] = []
    parsed_count = 0

    for record in candidates:
        rel = str(record.get("relative_path") or "")
        try:
            physical = pathlib.Path(resolver.resolve(rel))
            row = _shallow_file(record, physical)
            try:
                parsed = parse_object_local_smd(physical, strict_v1=False)
                parsed_count += 1
                row["parser_status"] = "PASS"
                channels = sorted({
                    ("ROT" if str(c) == "ROT_AFFINE" else str(c))
                    for o in parsed.get("objects", [])
                    for c in (o.get("channels_animated") or [])
                })
                row["channels_present"] = channels
                row["legacy_affine_object_count"] = int(parsed.get("legacy_affine_object_count") or 0)
                row["zero_scale_spawn_object_count"] = sum(
                    1 for o in parsed.get("objects", []) if o.get("zero_scale_reference_axes")
                )
                row["parent_edge_count_full_parse"] = int(parsed.get("parent_edge_count") or 0)
                row["unresolved_parent_count_full_parse"] = int(parsed.get("unresolved_parent_count") or 0)
                row["animated_child_count"] = int(parsed.get("animated_child_count") or 0)
                row["hold_child_count"] = sum(
                    1 for o in parsed.get("objects", [])
                    if o.get("parent_index") is not None and o.get("motion_class") == "HOLD"
                )
                if row["legacy_affine_object_count"]:
                    row["tags"].append("LEGACY_AFFINE_ROTATION")
                if row["zero_scale_spawn_object_count"]:
                    row["tags"].append("ZERO_SCALE_SPAWN")
                if row["animated_child_count"]:
                    row["tags"].append("ANIMATED_CHILD_LOCAL_PLUS_PARENT")
                    animated_child_paths.append(rel)
                if row["hold_child_count"]:
                    row["tags"].append("HOLD_CHILD_LOCAL_PLUS_PARENT")
                    hold_child_paths.append(rel)
            except Exception as exc:
                row["parser_status"] = "FAIL"
                row["parser_error"] = f"{type(exc).__name__}: {exc}"
                row["channels_present"] = []
                row["legacy_affine_object_count"] = None
                row["zero_scale_spawn_object_count"] = None
                row["parent_edge_count_full_parse"] = None
                row["unresolved_parent_count_full_parse"] = None
                row["animated_child_count"] = None
                row["hold_child_count"] = None
                row["tags"].append("FULL_PARSE_FAILURE")
                if "LEGACY_AFFINE_ROTATION_UNSUPPORTED" in str(exc):
                    row["tags"].append("LEGACY_AFFINE_ROTATION")
            for tag in set(row["tags"]):
                tag_counts[tag] += 1
            category_counts[row["category"]] += 1
            rows.append(row)
        except Exception as exc:
            errors.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})

    interesting_tags = (
        "ANIMATED_CHILD_LOCAL_PLUS_PARENT",
        "CHILD_WITH_SERIALIZED_CURVES",
        "HOLD_CHILD_LOCAL_PLUS_PARENT",
        "SEGMENTED_TMFRAME",
        "DEEP_HIERARCHY",
        "FULL_PARSE_FAILURE",
        "LEGACY_AFFINE_ROTATION",
        "UNRESOLVED_PARENT",
    )
    reps: dict[str, list[str]] = {}
    for tag in interesting_tags:
        vals = [x["path"] for x in rows if tag in x["tags"]]
        reps[tag] = vals[:max(0, int(per_subtype))]

    report: dict[str, Any] = {
        "format": "PT_OBJECT_LOCAL_PHYSICAL_CORPUS_AUDIT_V2",
        "status": "PASS" if len(rows) == len(candidates) and not errors else "INCOMPLETE",
        "candidate_files_expected": len(candidates),
        "physical_files_audited": len(rows),
        "full_parser_pass_files": parsed_count,
        "scan_errors": errors,
        "tag_counts": dict(sorted(tag_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "animated_child_files": len(animated_child_paths),
        "hold_child_files": len(hold_child_paths),
        "segmented_tmframe_files": tag_counts.get("SEGMENTED_TMFRAME", 0),
        "deep_hierarchy_files": tag_counts.get("DEEP_HIERARCHY", 0),
        "child_with_serialized_curves_files": tag_counts.get("CHILD_WITH_SERIALIZED_CURVES", 0),
        "channel_file_counts": {
            c: sum(1 for r in rows if c in (r.get("channels_present") or []))
            for c in ("ROT", "POS", "SCALE")
        },
        "legacy_affine_files": sum(1 for r in rows if int(r.get("legacy_affine_object_count") or 0) > 0),
        "zero_scale_spawn_files": sum(1 for r in rows if int(r.get("zero_scale_spawn_object_count") or 0) > 0),
        "representatives": reps,
        "supported_advanced_subtypes": [
            "ANIMATED_CHILD_LOCAL_PLUS_PARENT",
            "CHILD_WITH_SERIALIZED_CURVES",
            "DEEP_HIERARCHY",
            "UNRESOLVED_PARENT",
            "UNRESOLVED_PARENT_WITH_CURVES_RUNTIME_ROOT",
            "LEGACY_AFFINE_ROTATION",
            "SEGMENTED_TMFRAME",
        ],
        "unsupported_subtypes": ["FULL_PARSE_FAILURE"],
        "object_local_complete_candidate": (
            len(rows) == len(candidates)
            and not errors
            and parsed_count == len(candidates)
            and tag_counts.get("FULL_PARSE_FAILURE", 0) == 0
        ),
        "rows": rows,
    }

    if bundle:
        out = pathlib.Path(bundle).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        selected: list[str] = []
        # The bundle is now a remaining-unsupported bundle.  Advanced hierarchy,
        # unresolved runtime roots and legacy affine are supported and no longer
        # need to be recopied on every clean corpus audit.
        for tag in ("FULL_PARSE_FAILURE",):
            for rel in reps.get(tag, []):
                if rel not in selected:
                    selected.append(rel)
        summary = {k: v for k, v in report.items() if k != "rows"}
        manifest = {
            "format": "PT_OBJECT_LOCAL_RARE_REPS_V1",
            "source_audit_status": report["status"],
            "selected": selected,
            "representatives": reps,
            "audit_summary": summary,
        }
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("PT_OBJECT_LOCAL_RARE_REPS/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for rel in selected:
                try:
                    src = pathlib.Path(resolver.resolve(rel))
                    zf.write(src, "PT_OBJECT_LOCAL_RARE_REPS/client/" + rel.replace("\\", "/"))
                except Exception as exc:
                    zf.writestr(
                        "PT_OBJECT_LOCAL_RARE_REPS/errors/" + rel.replace("/", "__") + ".txt",
                        f"{type(exc).__name__}: {exc}\n",
                    )
        report["bundle"] = str(out)
        report["bundle_selected_files"] = len(selected)

    return report
