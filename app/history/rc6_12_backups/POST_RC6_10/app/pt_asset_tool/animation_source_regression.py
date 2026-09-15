from __future__ import annotations

import math
import pathlib
from typing import Any

from .motion_core import (
    audit_motion_source,
    core_motion_subset,
    enrich_motions,
    load_motion_system,
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
    evaluator, inxcore = load_motion_system(project_root)
    parsed = inxcore.parse_inx(inx)
    smb_parsed = evaluator.parse_smb(smb)
    validation = inxcore.validate_with_smb(parsed, smb)
    motions = enrich_motions(parsed, smb_parsed)
    active = [m for m in motions if m.get("active_container")]
    if mode == "core":
        chosen = core_motion_subset(motions)
    elif mode == "all":
        chosen = active
    else:
        raise ValueError("mode must be core or all")
    if not chosen:
        raise RuntimeError("no active motions available for source regression")

    rows = []
    for motion in chosen:
        one = audit_motion_source(project_root, inx, smb, selector=str(motion["index"]))
        selected = next(
            (x for x in one.get("motions", []) if int(x.get("index", -1)) == int(motion["index"])),
            None,
        )
        if selected is None:
            raise AssertionError(f"selected source audit result missing motion {motion['index']}")
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
