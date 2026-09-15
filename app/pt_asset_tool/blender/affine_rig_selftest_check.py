from __future__ import annotations

"""Save/reopen evaluation check for the affine animation self-test rig."""

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

FORMAT = "PT_BLENDER_AFFINE_RIG_SELFTEST_CHECK_V1"


def _argv() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _matrix(values: list[float]) -> Matrix:
    if len(values) != 16:
        raise ValueError("expected 16 matrix values")
    return Matrix((values[0:4], values[4:8], values[8:12], values[12:16]))


def _max_abs(a: Matrix, b: Matrix) -> float:
    return max(abs(float(a[r][c]) - float(b[r][c])) for r in range(4) for c in range(4))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--report", required=True)
    ns = ap.parse_args(_argv())
    expected = json.loads(Path(ns.expected).read_text(encoding="utf-8"))
    tol = float(expected.get("tolerance") or 2e-4)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise RuntimeError(f"expected one armature after reopen, found {len(arms)}")
    arm = arms[0]
    source = str(expected["source_bone"])
    helper = str(expected["helper_bone"])
    action_name = str(expected["action"])
    if source not in arm.pose.bones or helper not in arm.pose.bones:
        raise RuntimeError("affine source/helper bones missing after reopen")
    if arm.data.bones[helper].use_deform:
        raise RuntimeError("affine helper became deformable after reopen")
    if arm.pose.bones[source].parent is None or arm.pose.bones[source].parent.name != helper:
        raise RuntimeError("affine source/helper parent relation did not persist")
    action = bpy.data.actions.get(action_name)
    if action is None:
        raise RuntimeError("affine selftest action missing after reopen")
    arm.animation_data_create()
    arm.animation_data.action = action
    if hasattr(action, "slots") and len(action.slots):
        arm.animation_data.action_slot = action.slots[0]

    rows = []
    global_max = 0.0
    failures = []
    for case in expected.get("cases") or []:
        frame = int(case["frame"])
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        actual = arm.pose.bones[source].matrix.copy()
        target = _matrix(case["source_matrix"])
        err = _max_abs(actual, target)
        global_max = max(global_max, err)
        row = {"frame": frame, "label": case.get("label"), "rank": case.get("rank"), "max_abs_matrix_error": err}
        rows.append(row)
        if err > tol:
            failures.append(row)

    report = {
        "format": FORMAT,
        "status": "PASS" if not failures else "FAIL",
        "blender_version": bpy.app.version_string,
        "action": action_name,
        "source_bone": source,
        "helper_bone": helper,
        "checked_cases": len(rows),
        "max_abs_matrix_error": global_max,
        "tolerance": tol,
        "cases": rows,
        "failures": failures,
        "client_modified": False,
        "server_modified": False,
    }
    rp = Path(ns.report).resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise RuntimeError(f"affine save/reopen selftest failed: {failures}")
    print("PT_AFFINE_RIG_SELFTEST_CHECK=PASS")


if __name__ == "__main__":
    main()
