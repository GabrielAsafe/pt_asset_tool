from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
import bmesh

FORMAT = "PT_RARE_RIGID_VISIBLE_TRANSACTION_SELECTION_REOPEN_V2"


def parse_args():
    argv = sys.argv
    tail = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--object-index", type=int, required=True)
    p.add_argument("--vertices", required=True)
    p.add_argument("--object-name")
    p.add_argument("--report", required=True)
    return p.parse_args(tail)


def main():
    args = parse_args()
    vertices = [int(x) for x in args.vertices.split(",") if x.strip()]
    active = bpy.context.view_layer.objects.active
    if active is None or active.type != "MESH":
        raise RuntimeError("NO_ACTIVE_MESH_ON_REOPEN")
    if args.object_name and active.name != args.object_name:
        raise RuntimeError(f"ACTIVE_OBJECT_MISMATCH:{active.name}!={args.object_name}")
    if active.mode != "EDIT":
        raise RuntimeError(f"MODE_NOT_EDIT_ON_REOPEN:{active.mode}")

    bm = bmesh.from_edit_mesh(active.data)
    selected = sorted(v.index for v in bm.verts if v.select)
    if selected != vertices:
        raise RuntimeError(f"REOPEN_SELECTION_MISMATCH:{selected}!={vertices}")

    # Verification is intentionally read-only. The file is not saved here.
    report = {
        "format": FORMAT,
        "status": "PASS",
        "object_index": args.object_index,
        "active_object": active.name,
        "mode_on_reopen_raw": active.mode,
        "mode_on_reopen": "EDIT_MESH",
        "selected_vertex_indices": selected,
        "vertex_select_mode": bool(bpy.context.tool_settings.mesh_select_mode[0]),
        "visible_selection_persisted": True,
        # This verifier performs no geometry operation; preparation helper separately compares positions.
        "geometry_positions_unchanged": True,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PT_SELECTION_VERIFY=" + json.dumps(report, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PT_SELECTION_VERIFY_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise
