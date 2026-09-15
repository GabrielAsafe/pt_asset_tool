from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
import bmesh

FORMAT = "PT_RARE_RIGID_VISIBLE_TRANSACTION_SELECTION_V2"


def parse_args():
    argv = sys.argv
    tail = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--object-index", type=int, required=True)
    p.add_argument("--vertices", required=True)
    p.add_argument("--object-name")
    p.add_argument("--report", required=True)
    return p.parse_args(tail)


def prop_index(obj):
    exact = {"pt_object_index", "smd_object_index", "object_index", "source_object_index"}
    candidates = []
    for owner in (obj, obj.data):
        for key in owner.keys():
            lk = str(key).lower()
            if lk in exact or ("object" in lk and "index" in lk):
                try:
                    candidates.append(int(owner[key]))
                except Exception:
                    pass
    return sorted(set(candidates))


def selected_indices_object_data(obj):
    return [v.index for v in obj.data.vertices if v.select]


def resolve_target(object_index, vertices, object_name):
    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if object_name:
        exact = [o for o in mesh_objects if o.name == object_name or o.data.name == object_name]
        if len(exact) == 1:
            return exact[0], "baseline_exact_name"
        # SMD head names are sometimes embedded in Blender-generated names.
        embedded = [o for o in mesh_objects if object_name in o.name or object_name in o.data.name]
        if len(embedded) == 1:
            return embedded[0], "baseline_embedded_name"

    by_prop = [o for o in mesh_objects if object_index in prop_index(o)]
    if len(by_prop) == 1:
        return by_prop[0], "object_index_custom_property"

    wanted = set(vertices)
    by_saved_selection = []
    for o in mesh_objects:
        if len(o.data.vertices) <= max(vertices):
            continue
        if wanted.issubset(set(selected_indices_object_data(o))):
            by_saved_selection.append(o)
    if len(by_saved_selection) == 1:
        return by_saved_selection[0], "persisted_vertex_selection"

    active = bpy.context.view_layer.objects.active
    if (
        active is not None and active.type == "MESH"
        and len(active.data.vertices) > max(vertices)
        and wanted.issubset(set(selected_indices_object_data(active)))
    ):
        return active, "active_object_with_persisted_selection"

    raise RuntimeError(
        "AMBIGUOUS_TRANSACTION_OBJECT: no unique baseline name, object-index property, "
        "or persisted default-transaction selection"
    )


def main():
    args = parse_args()
    vertices = [int(x) for x in args.vertices.split(",") if x.strip()]
    if vertices != sorted(set(vertices)) or not (2 <= len(vertices) <= 4):
        raise RuntimeError(f"INVALID_TRANSACTION_VERTICES:{vertices}")

    target, method = resolve_target(args.object_index, vertices, args.object_name)
    if len(target.data.vertices) <= max(vertices):
        raise RuntimeError("TARGET_VERTEX_RANGE_INVALID")

    # Record geometry before touching UI state. Selection/mode are the only authorized changes.
    before = [(v.index, tuple(v.co)) for v in target.data.vertices]

    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    for v in target.data.vertices:
        v.select = v.index in vertices

    bpy.context.tool_settings.mesh_select_mode = (True, False, False)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(target.data)
    for v in bm.verts:
        v.select_set(v.index in vertices)
    bmesh.update_edit_mesh(target.data, loop_triangles=False, destructive=False)

    selected_edit = sorted(v.index for v in bm.verts if v.select)
    if selected_edit != vertices:
        raise RuntimeError(f"EDIT_SELECTION_MISMATCH:{selected_edit}!={vertices}")

    # Save while still in EDIT_MESH so reopening shows the vertex selection directly.
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.blend)))

    # Confirm geometry coordinates did not change in-memory.
    bm_after = bmesh.from_edit_mesh(target.data)
    after_map = {v.index: tuple(v.co) for v in bm_after.verts}
    geometry_unchanged = all(after_map[i] == co for i, co in before)
    if not geometry_unchanged:
        raise RuntimeError("GEOMETRY_CHANGED_DURING_SELECTION_PREP")

    report = {
        "format": FORMAT,
        "status": "PASS",
        "blend": str(Path(args.blend)),
        "object_index": args.object_index,
        "object_name": target.name,
        "mesh_name": target.data.name,
        "resolution_method": method,
        "selected_vertex_indices": vertices,
        "mode_after_raw": target.mode,
        "mode_after": "EDIT_MESH" if target.mode == "EDIT" else target.mode,
        "active_object": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        "vertex_select_mode": bool(bpy.context.tool_settings.mesh_select_mode[0]),
        "geometry_positions_unchanged": geometry_unchanged,
        "selection_only_change": True,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PT_SELECTION_REPORT=" + json.dumps(report, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PT_SELECTION_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise
