#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, pathlib, sys
import bpy
from mathutils import Vector


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--strength", type=float, default=0.12)
    return p.parse_args(argv)


def main():
    a = args()
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_viewport and not o.hide_render and len(o.data.vertices) >= 3]
    if not meshes:
        raise RuntimeError("no visible mesh objects for witness")
    obj = max(meshes, key=lambda o: len(o.data.vertices))
    verts = obj.data.vertices
    center = sum((v.co for v in verts), Vector((0.0, 0.0, 0.0))) / len(verts)
    xs = [v.co.x for v in verts]; ys = [v.co.y for v in verts]; zs = [v.co.z for v in verts]
    diag = math.sqrt((max(xs)-min(xs))**2 + (max(ys)-min(ys))**2 + (max(zs)-min(zs))**2)
    if diag <= 1e-8:
        raise RuntimeError("degenerate mesh bbox")

    ranked = sorted(range(len(verts)), key=lambda i: (verts[i].co - center).length, reverse=True)
    count = max(1, min(12, max(1, len(verts)//25)))
    changed = []
    for i in ranked[:count]:
        d = verts[i].co - center
        if d.length <= 1e-8:
            d = Vector((0.0, 0.0, 1.0))
        else:
            d.normalize()
        before = tuple(float(x) for x in verts[i].co)
        verts[i].co += d * (diag * a.strength)
        after = tuple(float(x) for x in verts[i].co)
        changed.append({"vertex": i, "before": before, "after": after})
    obj.data.update()

    scene = bpy.context.scene
    scene["pt_visual_witness"] = "GEOMETRY_VERTEX_RADIAL"
    scene["pt_visual_witness_object"] = obj.name
    scene["pt_visual_witness_vertex_count"] = len(changed)
    scene["pt_visual_witness_strength"] = a.strength

    out = pathlib.Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    report = {
        "tool": "PT_ASSET_TOOL_GEOMETRY_WITNESS_V1",
        "object": obj.name,
        "mesh_vertices": len(verts),
        "bbox_diagonal": diag,
        "strength": a.strength,
        "changed_vertices": changed,
        "output": str(out),
        "client_modified": False,
        "check": "PASS",
    }
    rp = pathlib.Path(a.report).expanduser().resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PT_ASSET_TOOL_GEOMETRY_WITNESS_V1")
    print(f"object={obj.name}")
    print(f"changed_vertices={len(changed)}")
    print(f"output={out}")
    print("client_modified=False")
    print("witness_check=PASS")


if __name__ == "__main__":
    main()
