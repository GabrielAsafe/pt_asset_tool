from __future__ import annotations

import math
import pathlib
from typing import Any

from .motion_core import (
    analyze_prepared_motion,
    core_motion_subset,
    prepare_motion_source_audit,
)

FORMAT = "PT_ANIMATION_SOURCE_REGRESSION_V1"


def _finite_motion(report: dict[str, Any]) -> bool:
    numeric = []
    for key in ("first_frame_rigidity_score", "last_frame_rigidity_score"):
        if report.get(key) is not None:
            numeric.append(float(report[key]))
    worst = report.get("worst_rigidity") or {}
    for key in ("score", "scale_dev", "orth_error", "det", "det_dev"):
        if worst.get(key) is not None:
            numeric.append(float(worst[key]))
    return bool(report.get("frames", 0)) and all(math.isfinite(x) for x in numeric)


def audit_animation_source_regression(
    project_root: pathlib.Path,
    inx: pathlib.Path,
    smb: pathlib.Path,
    *,
    mode: str = "core",
) -> dict[str, Any]:
    """Run source-side motion sanity across a real INX/SMB pair.

    This is deliberately *not* a visual certification. It proves that the
    parser/evaluator can traverse selected motions, that INX->SMB segment
    references validate, and that the resulting rigidity diagnostics are
    finite. Blender pose-space correctness remains a separate gate.
    """
    project_root = pathlib.Path(project_root)
    inx = pathlib.Path(inx)
    smb = pathlib.Path(smb)
    # PT_RC6_12_MOTION_PREPARE_ONCE: parse the INX/SMB pair and compute bind
    # inverses once for the entire context. Motion/frame coverage is unchanged.
    prepared = prepare_motion_source_audit(project_root, inx, smb)
    parsed = prepared["parsed"]
    validation = prepared["inxcore"].validate_with_smb(parsed, smb)
    motions = prepared["motions"]
    active = prepared["active"]
    if mode == "core":
        chosen = core_motion_subset(motions)
    elif mode == "all":
        chosen = active
    else:
        raise ValueError("mode must be core or all")
    if not chosen:
        raise RuntimeError("no active motions available for source regression")

    # PT_RC6_12_MOTION_POSE_CACHE: cache only exact evaluator calls that are
    # requested more than once across the chosen motions. No frame is skipped.
    pose_key_counts: dict[tuple[int, int], int] = {}
    for motion in chosen:
        for logical in range(int(motion["global_start"]), int(motion["global_end"])):
            key=(int(logical)*160,int(motion["engine_end"]))
            pose_key_counts[key]=pose_key_counts.get(key,0)+1
    prepared["pose_cache_keys"]={k for k,v in pose_key_counts.items() if v>1}
    prepared["pose_cache"]={}

    rows = []
    for motion in chosen:
        # PT_RC6_11_MOTION_DEDUP removed repeated WALK/ATTACK references.
        # PT_RC6_12_MOTION_PREPARE_ONCE also removes repeated parse/bind setup.
        selected = analyze_prepared_motion(prepared, motion)
        selected = dict(selected)
        selected["finite"] = _finite_motion(selected)
        rows.append(selected)

    worst = max((float((row.get("worst_rigidity") or {}).get("score", 0.0)) for row in rows), default=0.0)
    source_sanity = (
        validation.get("check") == "PASS"
        and all(row.get("finite") for row in rows)
        and all(int(row.get("frames", 0)) > 0 for row in rows)
    )
    return {
        "format": FORMAT,
        "status": "PASS" if source_sanity else "FAIL",
        "scope": "SOURCE_SIDE_SANITY_NOT_VISUAL_CERTIFICATION",
        "inx": str(inx),
        "smb": str(smb),
        "layout": parsed["layout"]["name"],
        "motion_count": int(parsed["motion_count"]),
        "active_motion_count": len(active),
        "audited_motion_count": len(rows),
        "mode": mode,
        "inx_smb_validation": validation,
        "motions": rows,
        "worst_rigidity_score_observed": worst,
        "threshold_policy": "DIAGNOSTIC_ONLY_NO_PRODUCTION_THRESHOLD",
        "visual_certification": False,
        "blender_pose_space_certification": False,
        "client_modified": False,
    }
