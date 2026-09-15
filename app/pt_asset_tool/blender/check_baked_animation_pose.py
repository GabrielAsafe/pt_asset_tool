from __future__ import annotations

import argparse
import json
import pathlib
import sys

import bpy
from mathutils import Matrix

FORMAT = "PT_BLENDER_BAKED_ANIMATION_POSE_CHECK_V1"


def _argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _row_to_col(values):
    if len(values) != 16:
        raise ValueError("matrix must contain 16 values")
    return Matrix((values[0:4], values[4:8], values[8:12], values[12:16])).transposed()


def _max_abs(a: Matrix, b: Matrix) -> float:
    return max(abs(float(a[r][c]) - float(b[r][c])) for r in range(4) for c in range(4))




def _expected_basis(arm, desired_pose: dict[str, Matrix], name: str) -> Matrix:
    pb = arm.pose.bones[name]
    bone = arm.data.bones[name]
    parent_pb = pb.parent
    target = desired_pose[name]
    if hasattr(bone, "convert_local_to_pose"):
        if parent_pb is None:
            return bone.convert_local_to_pose(target, bone.matrix_local, invert=True)
        parent_bone = arm.data.bones[parent_pb.name]
        return bone.convert_local_to_pose(
            target, bone.matrix_local,
            parent_matrix=desired_pose[parent_pb.name],
            parent_matrix_local=parent_bone.matrix_local,
            invert=True,
        )
    if parent_pb is None:
        return bone.matrix_local.inverted() @ target
    parent_bone = arm.data.bones[parent_pb.name]
    rest_local = parent_bone.matrix_local.inverted() @ bone.matrix_local
    pose_local = desired_pose[parent_pb.name].inverted() @ target
    return rest_local.inverted() @ pose_local


def _trs_reconstruction_error(matrix: Matrix) -> tuple[float, dict]:
    loc, rot, scale = matrix.decompose()
    rebuilt = Matrix.LocRotScale(loc, rot, scale)
    return _max_abs(matrix, rebuilt), {
        "location": [float(x) for x in loc],
        "scale": [float(x) for x in scale],
        "determinant_3x3": float(matrix.to_3x3().determinant()),
    }

def _armature():
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise RuntimeError(f"expected exactly one armature, got {len(arms)}")
    return arms[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--tolerance", type=float, default=2e-4)
    ns = ap.parse_args(_argv())
    payload = json.loads(pathlib.Path(ns.payload).read_text(encoding="utf-8"))
    tol = float(ns.tolerance)
    if not (0.0 < tol <= 0.01):
        raise ValueError("tolerance must be in (0, 0.01]")

    arm = _armature()
    arm.animation_data_create()
    try:
        affine_control_map = json.loads(str(arm.get("pt_affine_control_map", "{}")))
    except Exception:
        affine_control_map = {}
    if not isinstance(affine_control_map, dict):
        affine_control_map = {}
    bind = {b["name"]: _row_to_col(b["bind_tm"]) for b in payload["bones"]}
    missing = [n for n in bind if n not in arm.pose.bones]
    if missing:
        raise RuntimeError(f"armature missing source bones: {missing[:20]}")

    action_rows = []
    errors = []
    global_max = 0.0
    checked_frames = 0
    checked_bones = 0
    max_basis_trs_error = 0.0
    non_trs_basis_mismatch_count = 0
    for spec in payload.get("actions") or []:
        action = bpy.data.actions.get(spec["name"])
        if action is None:
            errors.append(f"ACTION_MISSING:{spec['name']}")
            continue
        arm.animation_data.action = action
        if hasattr(action, "slots") and len(action.slots):
            arm.animation_data.action_slot = action.slots[0]
        action_max = 0.0
        action_bad = []
        for fr in spec.get("frames") or []:
            scene_frame = int(fr["frame"])
            bpy.context.scene.frame_set(scene_frame)
            bpy.context.view_layer.update()
            frame_max = 0.0
            desired_pose = {}
            for idx in payload["tm_sort"]:
                bmeta = payload["bones"][idx]
                name = bmeta["name"]
                current = _row_to_col(fr["matrices"][idx])
                delta = current @ bind[name].inverted()
                desired_pose[name] = delta @ arm.data.bones[name].matrix_local
            for idx in payload["tm_sort"]:
                bmeta = payload["bones"][idx]
                name = bmeta["name"]
                expected = desired_pose[name]
                actual = arm.pose.bones[name].matrix.copy()
                err = _max_abs(actual, expected)
                frame_max = max(frame_max, err)
                checked_bones += 1
                ctrl_name = affine_control_map.get(name)
                if ctrl_name:
                    source_bone = arm.data.bones[name]
                    basis_trs_error = float(source_bone.get("pt_source_max_basis_trs_error", tol * 2.0))
                    basis_diag = {
                        "affine_split_control": ctrl_name,
                        "representation": str(arm.get("pt_affine_split_mode", "AFFINE_SPLIT")),
                        "source_basis_max_trs_error": basis_trs_error,
                    }
                else:
                    basis = _expected_basis(arm, desired_pose, name)
                    basis_trs_error, basis_diag = _trs_reconstruction_error(basis)
                max_basis_trs_error = max(max_basis_trs_error, basis_trs_error)
                if err > tol and basis_trs_error > tol:
                    non_trs_basis_mismatch_count += 1
                if err > tol and len(action_bad) < 20:
                    action_bad.append({
                        "frame": scene_frame, "bone": name, "max_abs_error": err,
                        "expected_basis_trs_reconstruction_error": basis_trs_error,
                        "expected_basis_trs_representable": basis_trs_error <= tol,
                        "affine_split_active": bool(ctrl_name),
                        "expected_basis_diagnostics": basis_diag,
                    })
            checked_frames += 1
            action_max = max(action_max, frame_max)
        global_max = max(global_max, action_max)
        if action_bad:
            errors.append(f"POSE_MISMATCH:{spec['name']}")
        action_rows.append({
            "action": spec["name"],
            "motion_index": int(spec.get("index") or 0),
            "state": spec.get("state_name"),
            "frame_count": len(spec.get("frames") or []),
            "max_abs_matrix_error": action_max,
            "mismatch_sample": action_bad,
        })

    report = {
        "format": FORMAT,
        "status": "PASS" if not errors else "FAIL",
        "armature": arm.name,
        "action_count": len(action_rows),
        "checked_frames": checked_frames,
        "checked_bone_frames": checked_bones,
        "tolerance": tol,
        "max_abs_matrix_error": global_max,
        "max_expected_basis_trs_reconstruction_error": max_basis_trs_error,
        "non_trs_basis_mismatch_count": non_trs_basis_mismatch_count,
        "pose_mismatch_diagnostic": (
            "AFFINE_SPLIT_EVALUATION_MISMATCH" if non_trs_basis_mismatch_count and affine_control_map
            else ("NON_TRS_SOURCE_BASIS" if non_trs_basis_mismatch_count else ("ACTION_EVALUATION_OR_PERSISTENCE" if errors else "NONE"))
        ),
        "affine_representation": str(arm.get("pt_affine_split_mode", "NONE")),
        "affine_split_bone_count": len(affine_control_map),
        "affine_split_bones": sorted(affine_control_map),
        "actions": action_rows,
        "errors": errors,
        "source_pose_reference": "GLOBAL_BIND",
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    rp = pathlib.Path(ns.report).resolve(); rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError(f"baked animation pose-space check failed: {errors[:8]}")
    print(json.dumps({k: report[k] for k in ("format","status","action_count","checked_frames","checked_bone_frames","max_abs_matrix_error","client_modified")}, indent=2))


if __name__ == "__main__":
    main()
