from __future__ import annotations

from typing import Any

FORMAT = "PT_ASSET_WORKFLOW_PLAN_V1"


def build_plan(asset) -> dict[str, Any]:
    path = str(asset.primary_path).replace("\\", "/")
    low = path.lower()
    base = {
        "format": FORMAT,
        "operation": "build",
        "asset_id": asset.asset_id,
        "asset": path,
        "kind": asset.kind,
        "family": asset.family,
        "authorized": False,
        "adapter": None,
        "client_write": False,
        "output_policy": "PT_BUILD_ONLY",
    }
    if low == "char/tmabcd/at_dragon.smd":
        return {
            **base,
            "authorized": True,
            "adapter": "RARE_RIGID_AT_DRAGON_CERTIFIED",
            "scope": "ONE_TO_FOUR_VERTEX_SINGLE_OBJECT_MULTIBONE_INTERIOR_TRANSACTION",
            "reason": "certified guarded saved-Blender writer is available",
        }
    if asset.kind == "SMD_STAGE_072":
        return {
            **base,
            "reason": "Stage0.72 has strict UV/geometry witness writers, but no generic saved-edit build writer is certified",
        }
    if asset.family == "SMD_MODEL_062_STATIC":
        return {
            **base,
            "reason": "static Model0.62 roundtrip witnesses exist, but arbitrary saved-Blender build is not certified",
        }
    if asset.visual_mode == "RIGID":
        return {
            **base,
            "reason": "rigid Physique import/animation context may exist, but generic geometry build is not certified for this asset",
        }
    return {**base, "reason": "no certified build adapter for this asset family"}
