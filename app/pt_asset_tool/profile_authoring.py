from __future__ import annotations

from typing import Any

from .rigid_model_info import normalize_lod_groups, lod_node_coverage, effective_lod_node_coverage

FORMAT = "PT_CHARACTER_PROFILE_AUTHORING_PLAN_V1"


def _norm(path: str | None) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def _component_path(verification: dict[str, Any], role: str) -> tuple[str | None, list[str]]:
    rows = [
        row for row in (verification.get("components") or [])
        if str(row.get("role") or "").casefold() == role.casefold() and row.get("status") == "PASS"
    ]
    if len(rows) != 1:
        return None, [f"PROFILE_{role.upper()}_COMPONENT_NOT_EXACTLY_ONE_PASS"]
    logical = _norm(rows[0].get("logical_path"))
    if not logical:
        return None, [f"PROFILE_{role.upper()}_LOGICAL_PATH_MISSING"]
    return logical, []


def plan_profile_authoring_context(
    profile_registry,
    profile_id: str,
    resolver,
    asset_registry,
    *,
    lod: str = "auto",
) -> dict[str, Any]:
    """Resolve one canonical profile into an exact rigid import context.

    This authorizes only a Blender import selection. It does not authorize a
    generic writer, production build, or client write. Exact resolved component
    paths are cross-checked against one registry INX configuration; basename
    similarity alone is never sufficient here.
    """
    profile = profile_registry.get(profile_id)
    verification = profile_registry.verify(profile_id, resolver, asset_registry=asset_registry)
    errors: list[str] = []
    if verification.get("status") != "PASS":
        errors.append("PROFILE_VERIFY_FAILED")

    try:
        asset = asset_registry.resolve(profile.roundtrip_target)
    except Exception:
        asset = None
        errors.append("PROFILE_TARGET_NOT_IN_REGISTRY")

    if asset is not None:
        if _norm(asset.primary_path).casefold() != _norm(profile.roundtrip_target).casefold():
            errors.append("PROFILE_TARGET_REGISTRY_PATH_MISMATCH")
        if getattr(asset, "family", None) != "SMD_MODEL_062_RIGID_PHYSIQUE":
            errors.append("PROFILE_TARGET_NOT_RIGID_MODEL062")

    model_info_logical, model_errors = _component_path(verification, "model_info")
    skeleton_logical, skeleton_errors = _component_path(verification, "skeleton")
    errors.extend(model_errors)
    errors.extend(skeleton_errors)

    selected_cfg = None
    profile_groups = normalize_lod_groups(profile.lod_groups)
    matching_cfgs: list[dict[str, Any]] = []
    if asset is not None and model_info_logical and skeleton_logical:
        for cfg in (getattr(asset, "configs", []) or []):
            if _norm(cfg.get("inx")).casefold() != model_info_logical.casefold():
                continue
            if _norm(cfg.get("motion_smb")).casefold() != skeleton_logical.casefold():
                continue
            if normalize_lod_groups(cfg.get("lod_groups") or {}) != profile_groups:
                continue
            matching_cfgs.append(cfg)
        if len(matching_cfgs) != 1:
            errors.append("PROFILE_EXACT_REGISTRY_CONTEXT_NOT_UNIQUE")
        else:
            selected_cfg = matching_cfgs[0]

    requested = str(lod or "auto").strip().lower()
    if requested not in {"auto", "high", "default", "low"}:
        errors.append("LOD_INVALID")
        actual_lod = None
    elif requested == "auto":
        actual_lod = next((tier for tier in ("default", "high", "low") if profile_groups.get(tier)), None)
    else:
        actual_lod = requested if profile_groups.get(requested) else None
    if actual_lod is None:
        errors.append("PROFILE_REQUESTED_LOD_EMPTY")

    lod_coverage = None
    if asset is not None and selected_cfg is not None and actual_lod is not None:
        lod_coverage = effective_lod_node_coverage(asset, selected_cfg, actual_lod)
        if lod_coverage.get("status") == "FAIL":
            errors.append("PROFILE_LOD_REFERENCES_MISSING_SMD_NODES")

    ready = not errors and selected_cfg is not None and actual_lod is not None
    return {
        "format": FORMAT,
        "status": "READY" if ready else "BLOCKED",
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "roundtrip_target": profile.roundtrip_target,
        "asset_id": getattr(asset, "asset_id", None) if asset is not None else None,
        "asset": getattr(asset, "primary_path", None) if asset is not None else None,
        "model_info_inx": model_info_logical,
        "skeleton_smb": skeleton_logical,
        "lod": actual_lod,
        "lod_groups": profile_groups,
        "selected_lod_nodes": list(profile_groups.get(actual_lod, [])) if actual_lod else [],
        "lod_node_coverage": lod_coverage,
        "profile_runtime_proven": bool((profile.geometry_status or {}).get("all_lods_runtime_proven")),
        "profile_verification_status": verification.get("status"),
        "exact_registry_context_match": len(matching_cfgs) == 1,
        "errors": sorted(set(errors)),
        "selection_basis": {
            "kind": "CANONICAL_PROFILE",
            "profile_id": profile.profile_id,
            "profile_version": profile.profile_version,
            "roundtrip_target": _norm(profile.roundtrip_target),
        },
        "import_context_authorized": ready,
        "writer_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
