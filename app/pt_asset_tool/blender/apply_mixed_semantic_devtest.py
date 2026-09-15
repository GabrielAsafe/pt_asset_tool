from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import bpy

FORMAT = "PT_MIXED_PHYSIQUE_AUTOMATED_EDIT_V1"


def _argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _bbox(obj):
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not pts:
        return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    return [
        [min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)],
        [max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)],
    ]


def _deform(obj, amplitude: float, seed: int):
    for vi, vertex in enumerate(obj.data.vertices):
        phase = (vi + 1) * (seed + 7)
        vertex.co.x += amplitude * math.sin(phase * 0.53)
        vertex.co.y += amplitude * 0.65 * math.cos(phase * 0.41)
        vertex.co.z += amplitude * 0.45 * math.sin(phase * 0.29 + 0.3)
    obj.data.update()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ns = ap.parse_args(_argv())
    plan = json.loads(pathlib.Path(ns.plan).read_text(encoding="utf-8"))
    targets = list(plan.get("targets") or [])
    amplitude = float(plan.get("amplitude") or 0.08)
    if not targets:
        raise RuntimeError("mixed semantic devtest has no targets")

    rows = []
    missing = []
    for index, target in enumerate(targets):
        name = str(target.get("object") or "")
        adapter = str(target.get("adapter") or "")
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            missing.append(name)
            continue
        before = _bbox(obj)
        counts = [len(obj.data.vertices), len(obj.data.polygons)]
        _deform(obj, amplitude, index)
        after = _bbox(obj)
        rows.append({
            "object": name,
            "adapter": adapter,
            "counts": counts,
            "bbox_before": before,
            "bbox_after": after,
            "bbox_changed": before != after,
        })
    if missing:
        raise RuntimeError(f"mixed semantic devtest missing objects: {missing}")
    if any(not row["bbox_changed"] for row in rows):
        raise RuntimeError("one or more mixed targets did not receive a geometric edit")
    adapters = {row["adapter"] for row in rows}
    if not {"RIGID", "STATIC"}.issubset(adapters):
        raise RuntimeError(f"mixed semantic devtest must exercise rigid and static adapters: {sorted(adapters)}")

    out = pathlib.Path(ns.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), check_existing=False)
    report = {
        "format": FORMAT,
        "status": "PASS",
        "target_count": len(rows),
        "targets": rows,
        "adapter_counts": {kind: sum(1 for row in rows if row["adapter"] == kind) for kind in ("RIGID", "STATIC")},
        "materials_intentionally_changed": False,
        "client_modified": False,
    }
    rp = pathlib.Path(ns.report).resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
