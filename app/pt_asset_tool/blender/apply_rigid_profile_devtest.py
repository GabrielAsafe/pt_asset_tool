from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import bpy

FORMAT = "PT_RIGID_PROFILE_AUTOMATED_EDIT_V1"


def _argv() -> list[str]:
    args = sys.argv
    return args[args.index("--") + 1 :] if "--" in args else []


def _bbox(obj) -> list[list[float]]:
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not pts:
        return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    return [
        [min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)],
        [max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)],
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ns = ap.parse_args(_argv())

    plan_path = pathlib.Path(ns.plan).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    objects = [str(x) for x in plan.get("objects") or []]
    object_refs = [dict(x) for x in plan.get("object_refs") or [] if isinstance(x, dict)]
    if object_refs:
        targets = object_refs
    else:
        targets = [{"name": name, "index": None} for name in objects]
    amplitude = float(plan.get("amplitude") or 0.12)
    if not targets:
        raise RuntimeError("automated rigid profile devtest has no target objects")

    rows = []
    missing = []
    for oi, ref in enumerate(targets):
        name = str(ref.get("name") or "")
        source_index = ref.get("index")
        resolved_source_index = source_index
        if source_index is not None:
            hits = [
                candidate for candidate in bpy.data.objects
                if candidate.type == "MESH"
                and int(candidate.get("pt_smd_object_index", -1)) == int(source_index)
            ]
            obj = hits[0] if len(hits) == 1 else None
            if obj is not None and str(obj.get("pt_smd_node_name") or obj.name) != name:
                obj = None
        else:
            obj = bpy.data.objects.get(name)
            # FIX22_CORE_CORPUS_AND_T5_ATTRIBUTION: preserve the physical
            # object-table identity chosen by the importer for duplicate names.
            if obj is not None:
                imported_index = obj.get("pt_smd_object_index")
                if imported_index is not None and int(imported_index) >= 0:
                    resolved_source_index = int(imported_index)
        if obj is None or obj.type != "MESH":
            missing.append({"name": name, "index": source_index})
            continue
        mesh = obj.data
        if not mesh.vertices:
            raise RuntimeError(f"target mesh has no vertices: {name}")
        before = _bbox(obj)
        # Deterministic whole-mesh deformation.  This deliberately exercises far
        # more than a one-vertex witness while preserving topology, materials and
        # vertex-group/Physique assignments for the writer contract.
        n = max(1, len(mesh.vertices))
        for vi, v in enumerate(mesh.vertices):
            phase = (vi + 1) * (oi + 3)
            # Keep the displacement comfortably above Model0.62 1/256 quantization.
            dx = amplitude * (0.45 + 0.15 * ((oi + 1) % 3)) * math.sin(phase * 0.73)
            dy = amplitude * (0.35 + 0.10 * ((oi + 2) % 4)) * math.cos(phase * 0.51)
            dz = amplitude * (0.25 + 0.08 * ((oi + 3) % 5)) * math.sin(phase * 0.37 + 0.4)
            # Add a gentle centroid-relative scale component so every target
            # receives a spatially distributed edit, not just local noise.
            v.co.x = v.co.x * (1.0 + 0.006 * ((oi % 3) - 1)) + dx
            v.co.y = v.co.y * (1.0 + 0.005 * (((oi + 1) % 3) - 1)) + dy
            v.co.z = v.co.z * (1.0 + 0.004 * (((oi + 2) % 3) - 1)) + dz
        mesh.update()
        after = _bbox(obj)
        rows.append({
            "object": name,
            "object_index": resolved_source_index,
            "blender_object": obj.name,
            "vertex_count": len(mesh.vertices),
            "polygon_count": len(mesh.polygons),
            "material_slot_count": len(obj.material_slots),
            "bbox_before": before,
            "bbox_after": after,
            "bbox_changed": before != after,
        })

    if missing:
        raise RuntimeError(f"automated rigid profile devtest missing mesh objects: {missing}")
    if any(not row["bbox_changed"] for row in rows):
        raise RuntimeError("automated rigid profile devtest failed to alter one or more target bounds")

    out = pathlib.Path(ns.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), check_existing=False)
    report = {
        "format": FORMAT,
        "status": "PASS",
        "plan": str(plan_path),
        "input_blend": str(pathlib.Path(bpy.data.filepath).resolve()),
        "output_blend": str(out),
        "amplitude": amplitude,
        "target_count": len(rows),
        "target_refs": targets,
        "targets": rows,
        "topology_intentionally_changed": False,
        "materials_intentionally_changed": False,
        "vertex_groups_intentionally_changed": False,
    }
    report_path = pathlib.Path(ns.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
