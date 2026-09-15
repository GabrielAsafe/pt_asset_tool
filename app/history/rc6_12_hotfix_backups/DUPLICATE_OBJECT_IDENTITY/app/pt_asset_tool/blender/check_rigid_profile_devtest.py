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
    errors = []
    rows = []
    for name, contract in objects.items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            errors.append(f"MISSING_MESH:{name}")
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
        "expected_object_count": len(objects),
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
