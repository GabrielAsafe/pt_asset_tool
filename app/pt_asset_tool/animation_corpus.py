from __future__ import annotations

import collections
import pathlib
from typing import Any

from .animation_source_regression import audit_animation_source_regression
from .motion_core import resolve_asset_motion_context
from .semantic_path import semantic_group_for_path

FORMAT = "PT_ANIMATION_SOURCE_CORPUS_V1"


def audit_animation_corpus(
    project_root: pathlib.Path,
    registry,
    resolver,
    *,
    category: str | None = None,
    mode: str = "core",
    pair_limit: int = 0,
    sample_limit: int = 50,
) -> dict[str, Any]:
    """Audit unique registry-proven INX/SMB animation contexts source-side.

    The audit is diagnostic/read-only. It deduplicates assets that share the
    same authoritative motion INX/SMB context, so a full client run measures
    format/context coverage rather than repeatedly evaluating identical roots.
    """
    category_q = str(category or "").strip().upper()
    assets = [a for a in registry.assets if a.animation_binding_ready]
    if category_q:
        assets = [a for a in assets if semantic_group_for_path(a.primary_path, a.category) == category_q]

    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for asset in assets:
        physical = registry.physical_dependency_status(asset)
        if not physical.get("animation_binding_ready_physical"):
            unresolved.append({
                "asset_id": asset.asset_id,
                "asset": asset.primary_path,
                "reason": "MISSING_PHYSICAL_DEPENDENCY",
                "missing": list(physical.get("missing") or []),
            })
            continue
        try:
            ctx = resolve_asset_motion_context(asset, resolver, require_physical=True)
        except Exception as exc:
            unresolved.append({
                "asset_id": asset.asset_id,
                "asset": asset.primary_path,
                "reason": "MOTION_CONTEXT_RESOLUTION_FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        key = (ctx["motion_inx"].casefold(), ctx["motion_smb"].casefold())
        row = contexts.setdefault(key, {
            "motion_inx": ctx["motion_inx"],
            "motion_smb": ctx["motion_smb"],
            "inx_path": ctx["inx_path"],
            "smb_path": ctx["smb_path"],
            "assets": [],
            "categories": set(),
        })
        row["assets"].append(asset.primary_path)
        row["categories"].add(semantic_group_for_path(asset.primary_path, asset.category))

    ordered = sorted(contexts.values(), key=lambda r: (str(r["motion_inx"]).casefold(), str(r["motion_smb"]).casefold()))
    if pair_limit and pair_limit > 0:
        ordered = ordered[: int(pair_limit)]

    rows = []
    failures = []
    layouts = collections.Counter()
    states = collections.Counter()
    total_audited_motions = 0
    for ctx in ordered:
        try:
            report = audit_animation_source_regression(
                pathlib.Path(project_root),
                pathlib.Path(ctx["inx_path"]),
                pathlib.Path(ctx["smb_path"]),
                mode=mode,
            )
            row = {
                "status": report.get("status"),
                "motion_inx": ctx["motion_inx"],
                "motion_smb": ctx["motion_smb"],
                "asset_count": len(ctx["assets"]),
                "assets": list(ctx["assets"]),
                "categories": sorted(ctx["categories"]),
                "layout": report.get("layout"),
                "motion_count": report.get("motion_count"),
                "active_motion_count": report.get("active_motion_count"),
                "audited_motion_count": report.get("audited_motion_count"),
                "worst_rigidity_score_observed": report.get("worst_rigidity_score_observed"),
                "inx_smb_validation": (report.get("inx_smb_validation") or {}).get("check"),
                "motions": [
                    {
                        "index": m.get("index"),
                        "state": m.get("state") or m.get("state_name"),
                        "frames": m.get("frames"),
                        "finite": m.get("finite"),
                    }
                    for m in (report.get("motions") or [])
                ],
            }
            if row["layout"]:
                layouts[str(row["layout"])] += 1
            total_audited_motions += int(row.get("audited_motion_count") or 0)
            for m in row["motions"]:
                if m.get("state"):
                    states[str(m["state"])] += 1
            rows.append(row)
            if row["status"] != "PASS":
                failures.append(row)
        except Exception as exc:
            row = {
                "status": "FAIL",
                "motion_inx": ctx["motion_inx"],
                "motion_smb": ctx["motion_smb"],
                "asset_count": len(ctx["assets"]),
                "assets": list(ctx["assets"]),
                "categories": sorted(ctx["categories"]),
                "error": f"{type(exc).__name__}: {exc}",
            }
            rows.append(row)
            failures.append(row)

    status = "PASS" if not failures else "FAIL"
    coverage = "COMPLETE_FOR_SELECTED_REGISTRY_SET" if not unresolved and (not pair_limit or pair_limit >= len(contexts)) else "PARTIAL"
    return {
        "format": FORMAT,
        "status": status,
        "scope": "SOURCE_SIDE_CORPUS_SANITY_NOT_VISUAL_CERTIFICATION",
        "category_filter": category_q or None,
        "mode": mode,
        "registry_animation_ready_assets": len(assets),
        "unique_motion_contexts": len(contexts),
        "audited_contexts": len(rows),
        "passed_contexts": sum(1 for r in rows if r.get("status") == "PASS"),
        "failed_contexts": len(failures),
        "unresolved_physical_assets": len(unresolved),
        "coverage": coverage,
        "layout_counts": dict(sorted(layouts.items())),
        "audited_state_counts": dict(sorted(states.items())),
        "total_audited_motions": total_audited_motions,
        "rows": rows,
        "failure_sample": failures[: max(0, int(sample_limit))],
        "unresolved_sample": unresolved[: max(0, int(sample_limit))],
        "visual_certification": False,
        "blender_pose_space_certification": False,
        "binding_promotion": False,
        "client_modified": False,
    }
