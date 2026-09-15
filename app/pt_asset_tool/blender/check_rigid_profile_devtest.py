from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import bpy

FORMAT = "PT_RIGID_PROFILE_AUTOMATED_REIMPORT_CHECK_V1"


def _argv() -> list[str]:
    args = sys.argv
    return args[args.index("--") + 1 :] if "--" in args else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--report", required=True)
    ns = ap.parse_args(_argv())
    expected = json.loads(pathlib.Path(ns.expected).read_text(encoding="utf-8"))
    objects = dict(expected.get("objects") or {})
    object_refs = [dict(x) for x in expected.get("object_refs") or [] if isinstance(x, dict)]
    targets = object_refs or [{"name": name, **dict(contract)} for name, contract in objects.items()]
    errors = []
    rows = []
    for ref in targets:
        name = str(ref.get("name") or "")
        source_index = ref.get("index")
        contract = ref
        if source_index is not None:
            hits = [
                candidate for candidate in bpy.data.objects
                if candidate.type == "MESH"
                and int(candidate.get("pt_smd_object_index", -1)) == int(source_index)
            ]
            obj = hits[0] if len(hits) == 1 else None
            if obj is not None and str(obj.get("pt_smd_node_name") or obj.name).casefold() != name.casefold():
                obj = None
        else:
            obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            errors.append(f"MISSING_MESH:{name}#idx{source_index}")
            continue
        mesh = obj.data
        counts = [len(mesh.vertices), len(mesh.polygons)]
        expected_counts = [int(contract.get("vertices") or -1), int(contract.get("faces") or -1)]
        if counts != expected_counts:
            errors.append(f"COUNT_MISMATCH:{name}:{counts}!={expected_counts}")
        nonfinite = 0
        unweighted = 0
        for v in mesh.vertices:
            if not all(math.isfinite(float(x)) for x in v.co):
                nonfinite += 1
            if not v.groups:
                unweighted += 1
        if nonfinite:
            errors.append(f"NONFINITE_VERTEX:{name}:{nonfinite}")
        if unweighted:
            errors.append(f"UNWEIGHTED_VERTEX:{name}:{unweighted}")
        rows.append({
            "object": name,
            "object_index": source_index,
            "blender_object": obj.name,
            "vertices": len(mesh.vertices),
            "faces": len(mesh.polygons),
            "material_slots": len(obj.material_slots),
            "nonfinite_vertices": nonfinite,
            "unweighted_vertices": unweighted,
        })
    report = {
        "format": FORMAT,
        "status": "PASS" if not errors else "FAIL",
        "lod": expected.get("lod"),
        "expected_object_count": len(targets),
        "checked_object_count": len(rows),
        "objects": rows,
        "errors": errors,
    }
    path = pathlib.Path(ns.report).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError("; ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
