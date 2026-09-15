from __future__ import annotations

"""Blender-side persistence self-test for the production affine animation split."""

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from pt_asset_tool.blender.bake_actions import (  # noqa: E402
    _apply_trs,
    _factor_basis,
    _derive_blender_residual_basis,
    _install_affine_controls,
    _key_pose_bone,
    ensure_pose_mode,
)

FORMAT = "PT_BLENDER_AFFINE_RIG_SELFTEST_BUILD_V2"
TOLERANCE = 2e-4


def _argv() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _max_abs(a: Matrix, b: Matrix) -> float:
    return max(abs(float(a[r][c]) - float(b[r][c])) for r in range(4) for c in range(4))


def _flat(m: Matrix) -> list[float]:
    return [float(m[r][c]) for r in range(4) for c in range(4)]


def _basis(linear: tuple[tuple[float, float, float], ...], loc: tuple[float, float, float]) -> Matrix:
    m = Matrix.Identity(4)
    for r in range(3):
        for c in range(3):
            m[r][c] = float(linear[r][c])
    m.translation = Vector(loc)
    return m


def _pose_from_basis_original_hierarchy(arm, bone_name: str, basis: Matrix) -> Matrix:
    """Convert a matrix_basis into pose space using Blender's own hierarchy rules.

    This is intentionally evaluated *before* the affine helper is inserted.  It
    makes the self-test compare the split rig with the same transform contract
    that production ``_expected_basis(..., invert=True)`` inverts, rather than
    with a hand-written parent/rest multiplication that can diverge from
    Blender's inherit-scale semantics.
    """
    bone = arm.data.bones[bone_name]
    pb = arm.pose.bones[bone_name]
    parent_pb = pb.parent
    if hasattr(bone, "convert_local_to_pose"):
        if parent_pb is None:
            return bone.convert_local_to_pose(basis, bone.matrix_local, invert=False)
        parent_bone = arm.data.bones[parent_pb.name]
        return bone.convert_local_to_pose(
            basis,
            bone.matrix_local,
            parent_matrix=parent_pb.matrix.copy(),
            parent_matrix_local=parent_bone.matrix_local,
            invert=False,
        )
    if parent_pb is None:
        return bone.matrix_local @ basis
    parent_bone = arm.data.bones[parent_pb.name]
    rest_local = parent_bone.matrix_local.inverted() @ bone.matrix_local
    return parent_pb.matrix @ rest_local @ basis


def _new_armature():
    arm_data = bpy.data.armatures.new("PT_AffineSelftestArmature")
    arm = bpy.data.objects.new("PT_AffineSelftestArmature", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = arm_data.edit_bones.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 1.0, 0.0)
    root.use_deform = False
    src = arm_data.edit_bones.new("Source")
    src.head = root.tail.copy()
    src.tail = (0.0, 2.0, 0.0)
    src.parent = root
    src.use_connect = True
    src.use_deform = True
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--expected", required=True)
    ap.add_argument("--report", required=True)
    ns = ap.parse_args(_argv())

    # Factory-startup should already be empty, but make the script deterministic
    # if it is invoked interactively while debugging.
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    arm = _new_armature()
    ensure_pose_mode(arm)

    cases = [
        (1, "SHEAR_FULL_RANK", _basis(((1.0, 0.35, -0.10), (0.0, 1.15, 0.22), (0.0, 0.0, 0.85)), (0.3, -0.2, 0.4))),
    ]
    rank_deficient_probe = _basis(((1.0, 0.20, 0.0), (0.0, 0.0, 0.0), (0.10, 0.0, 0.75)), (-0.1, 0.5, 0.2))
    # Establish the authoritative targets while the source bone still has its
    # original hierarchy.  Production computes the inverse operation when it
    # derives matrix_basis from an engine-space desired pose.
    expected_pose_by_frame = {
        int(frame): _pose_from_basis_original_hierarchy(arm, "Source", basis).copy()
        for frame, _label, basis in cases
    }

    payload = {"bones": [{"name": "Root"}, {"name": "Source"}]}
    control_map = _install_affine_controls(arm, payload, {"Source"}, {"Root": 0.0, "Source": 1.0})
    ctrl_name = control_map["Source"]
    if arm.data.bones[ctrl_name].use_deform:
        raise RuntimeError("affine helper unexpectedly deforms")
    if arm.pose.bones["Source"].parent is None or arm.pose.bones["Source"].parent.name != ctrl_name:
        raise RuntimeError("affine source was not reparented to helper")

    action = bpy.data.actions.new("PT_AFFINE_SELFTEST")
    action.use_fake_user = True
    arm.animation_data_create()
    arm.animation_data.action = action
    if hasattr(action, "slots"):
        slot = action.slots.new(id_type="OBJECT", name=arm.name)
        arm.animation_data.action_slot = slot

    expected_rows = []
    previous_quat = {}
    live_max = 0.0
    live_failures = []
    factor_max = 0.0
    ranks: dict[str, int] = {}

    for frame, label, basis in cases:
        bpy.context.scene.frame_set(frame)
        fac = _factor_basis(basis)
        factor_max = max(factor_max, float(fac["residual"]))
        ranks[str(fac["rank"])] = ranks.get(str(fac["rank"]), 0) + 1
        if int(fac["rank"]) < 3:
            raise RuntimeError(f"full-rank affine selftest case unexpectedly rank deficient: {label}")
        expected = expected_pose_by_frame[int(frame)]
        desired = {"Root": arm.pose.bones["Root"].matrix.copy(), "Source": expected}
        residual = _derive_blender_residual_basis(
            arm, "Source", ctrl_name, expected, desired, fac["first_matrix"]
        )
        _apply_trs(arm.pose.bones[ctrl_name], fac["location"], fac["first_quaternion"], fac["first_scale"])
        _apply_trs(
            arm.pose.bones["Source"],
            residual["location"],
            residual["quaternion"],
            residual["scale"],
        )
        bpy.context.view_layer.update()
        actual = arm.pose.bones["Source"].matrix.copy()
        err = _max_abs(actual, expected)
        live_max = max(live_max, err)
        if err > TOLERANCE:
            live_failures.append({
                "frame": int(frame),
                "label": label,
                "max_abs_matrix_error": float(err),
                "source_basis": _flat(basis),
                "expected_source_matrix": _flat(expected),
                "actual_source_matrix": _flat(actual),
                "first_matrix": _flat(fac["first_matrix"]),
                "svd_second_matrix": _flat(fac["second_matrix"]),
                "blender_residual_basis": _flat(residual["basis"]),
                "blender_residual_trs_error": float(residual["trs_error"]),
            })
        _key_pose_bone(arm.pose.bones[ctrl_name], frame, previous_quat)
        _key_pose_bone(arm.pose.bones["Source"], frame, previous_quat)
        expected_rows.append({"frame": frame, "label": label, "source_matrix": _flat(expected), "rank": int(fac["rank"])})

    rank_probe = _factor_basis(rank_deficient_probe)
    if int(rank_probe["rank"]) >= 3:
        raise RuntimeError("rank-deficient probe was not classified as rank deficient")
    rank_deficient_policy = {
        "label": "RANK_DEFICIENT_NON_TRS",
        "rank": int(rank_probe["rank"]),
        "status": "EXPECTED_BLOCKED",
        "reason": "SINGULAR_PARENT_INVERSION_NOT_BLENDER_CERTIFIED",
    }

    if hasattr(action, "layers") and hasattr(action, "slots") and len(action.slots):
        slot = action.slots[0]
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbag"):
                    bag = strip.channelbag(slot, ensure=False)
                    if bag is not None:
                        for fcu in bag.fcurves:
                            for kp in fcu.keyframe_points:
                                kp.interpolation = "LINEAR"
    elif hasattr(action, "fcurves"):
        for fcu in action.fcurves:
            for kp in fcu.keyframe_points:
                kp.interpolation = "LINEAR"

    arm["pt_affine_selftest_action"] = action.name
    expected = {
        "format": "PT_AFFINE_RIG_SELFTEST_EXPECTED_V1",
        "armature": arm.name,
        "source_bone": "Source",
        "helper_bone": ctrl_name,
        "action": action.name,
        "tolerance": TOLERANCE,
        "cases": expected_rows,
        "rank_deficient_policy": rank_deficient_policy,
    }
    expected_path = Path(ns.expected).resolve()
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")

    bpy.ops.object.mode_set(mode="OBJECT")
    out = Path(ns.out).resolve()
    rp = Path(ns.report).resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    if live_failures:
        report = {
            "format": FORMAT,
            "status": "FAIL",
            "blend": None,
            "expected": str(expected_path),
            "helper_bone": ctrl_name,
            "helper_non_deform": not bool(arm.data.bones[ctrl_name].use_deform),
            "helper_use_connect": bool(arm.data.bones[ctrl_name].use_connect),
            "source_use_connect": bool(arm.data.bones["Source"].use_connect),
            "live_max_abs_matrix_error": live_max,
            "live_failures": live_failures,
            "max_factor_reconstruction_error": factor_max,
            "rank_counts": ranks,
            "rank_deficient_policy": rank_deficient_policy,
            "target_contract": "BLENDER_CONVERT_LOCAL_TO_POSE_RESIDUAL_V2",
            "client_modified": False,
            "server_modified": False,
        }
        rp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"live affine source pose mismatch: {live_failures[:2]}")

    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    report = {
        "format": FORMAT,
        "status": "PASS",
        "blend": str(out),
        "expected": str(expected_path),
        "helper_bone": ctrl_name,
        "helper_non_deform": not bool(arm.data.bones[ctrl_name].use_deform),
        "helper_use_connect": bool(arm.data.bones[ctrl_name].use_connect),
        "source_use_connect": bool(arm.data.bones["Source"].use_connect),
        "live_max_abs_matrix_error": live_max,
        "live_failures": [],
        "max_factor_reconstruction_error": factor_max,
        "rank_counts": ranks,
        "rank_deficient_policy": rank_deficient_policy,
        "target_contract": "BLENDER_CONVERT_LOCAL_TO_POSE_RESIDUAL_V2",
        "client_modified": False,
        "server_modified": False,
    }
    rp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PT_AFFINE_RIG_SELFTEST_BUILD=PASS")


if __name__ == "__main__":
    main()
