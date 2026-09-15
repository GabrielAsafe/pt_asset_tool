from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from .semantic_path import semantic_group_for_path
from .rigid_model_info import (
    classify_asset_model_info_context, config_semantic_id, equivalent_model_info_paths,
)

FORMAT = "PT_CHARACTER_PROFILE_CANDIDATE_DISCOVERY_V1"


def _stable_id(asset_path: str, inx_path: str) -> str:
    key = f"{asset_path.casefold()}\n{inx_path.casefold()}".encode("utf-8")
    return "PRC-" + hashlib.sha1(key).hexdigest()[:12].upper()


def _norm_groups(cfg: dict[str, Any]) -> dict[str, list[str]]:
    groups = cfg.get("lod_groups") or {}
    return {tier: list(groups.get(tier) or []) for tier in ("high", "default", "low")}


def discover_profile_candidates(
    registry,
    *,
    category: str | None = None,
    limit: int = 0,
    profile_registry=None,
) -> dict[str, Any]:
    """Discover profile/LOD candidates from registry-proven rigid assets.

    Discovery is evidence extraction only. It never creates a canonical profile
    and never turns LOD identity into writer authorization. One candidate is
    emitted per distinct asset+INX configuration with at least one LOD node.
    """
    category_q = str(category or "").strip().upper()
    rows: list[dict[str, Any]] = []
    binding_modes: Counter[str] = Counter()
    readiness: Counter[str] = Counter()
    semantic_groups: Counter[str] = Counter()
    context_states: Counter[str] = Counter()

    for asset in registry.assets:
        if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
            continue
        semantic_group = semantic_group_for_path(asset.primary_path, asset.category)
        if category_q and semantic_group != category_q:
            continue
        object_names = list(asset.source_record.get("object_names") or [])
        object_set = set(object_names)
        model_info_context = classify_asset_model_info_context(asset)
        context_states[model_info_context["state"]] += 1
        for cfg in asset.configs:
            groups = _norm_groups(cfg)
            if not any(groups.values()):
                continue
            inx = str(cfg.get("inx") or "").replace("\\", "/")
            if not inx:
                continue
            listed = [node for tier in ("high", "default", "low") for node in groups[tier] if node]
            missing_nodes = sorted({node for node in listed if node not in object_set}, key=str.casefold)
            duplicate_nodes = sorted({node for node in listed if listed.count(node) > 1}, key=str.casefold)
            tiers_present = [tier for tier in ("high", "default", "low") if groups[tier]]
            skeleton = str(cfg.get("motion_smb") or asset.binding_skeleton_smb or "").replace("\\", "/")
            binding_ready = bool(asset.rigid_binding_ready and skeleton)
            complete_lods = len(tiers_present) == 3
            nodes_present = not missing_nodes
            candidate_ready = bool(binding_ready and nodes_present and complete_lods)

            canonical_profiles = []
            if profile_registry is not None:
                for hit in profile_registry.match_asset(asset.primary_path):
                    try:
                        profile = profile_registry.get(hit["profile_id"])
                    except Exception:
                        continue
                    profile_inx = str(profile.model_info_inx or "").replace("\\", "/").strip("/")
                    associated = [str(c.get("inx") or "").replace("\\", "/").strip("/") for c in asset.configs if c.get("inx")]
                    if "/" in profile_inx:
                        matches = [path for path in associated if path.casefold() == profile_inx.casefold()]
                        evidence = "EXACT_ASSOCIATED_INX_PATH"
                    else:
                        matches = [path for path in associated if path.split("/")[-1].casefold() == profile_inx.casefold()]
                        evidence = "UNIQUE_ASSOCIATED_INX_BASENAME"
                    if len(matches) == 1 and matches[0].casefold() == inx.casefold():
                        canonical_profiles.append({
                            "profile_id": profile.profile_id,
                            "geometry_status": dict(profile.geometry_status or {}),
                            "exact_asset_match": True,
                            "model_info_match_evidence": evidence,
                            "resolved_model_info_inx": matches[0],
                        })

            runtime_proven = any(bool((p.get("geometry_status") or {}).get("all_lods_runtime_proven")) for p in canonical_profiles)
            state = (
                "CANONICAL_RUNTIME_PROVEN" if runtime_proven else
                "CANDIDATE_READY" if candidate_ready else
                "CANDIDATE_INCOMPLETE"
            )
            readiness[state] += 1
            binding_modes[str(asset.binding_mode or "NONE")] += 1
            semantic_groups[semantic_group] += 1
            rows.append({
                "candidate_id": _stable_id(asset.primary_path, inx),
                "asset_id": asset.asset_id,
                "asset": asset.primary_path,
                "semantic_group": semantic_group,
                "inx": inx,
                "skeleton_smb": skeleton or None,
                "semantic_context_id": config_semantic_id(cfg),
                "model_info_context_state": model_info_context["state"],
                "model_info_ambiguity_dimensions": list(model_info_context.get("ambiguity_dimensions") or []),
                "requires_explicit_model_info": bool(model_info_context["requires_explicit_model_info"]),
                "equivalent_model_info_inx": equivalent_model_info_paths(asset, cfg),
                "binding_mode": asset.binding_mode,
                "binding_source": asset.binding_source,
                "binding_ready": binding_ready,
                "lod_groups": groups,
                "tiers_present": tiers_present,
                "all_three_lod_tiers_present": complete_lods,
                "smd_object_count": len(object_names),
                "lod_node_count": len(listed),
                "lod_nodes_present_in_smd": nodes_present,
                "missing_lod_nodes": missing_nodes,
                "duplicate_lod_nodes": duplicate_nodes,
                "canonical_profiles": canonical_profiles,
                "runtime_proven": runtime_proven,
                "state": state,
                "authoring_authorized": False,
            })

    rows.sort(key=lambda r: (r["semantic_group"], r["asset"].casefold(), r["inx"].casefold()))
    total = len(rows)
    shown = rows if not limit or int(limit) <= 0 else rows[: int(limit)]
    return {
        "format": FORMAT,
        "status": "PASS",
        "scope": "PROFILE_DISCOVERY_ONLY_NO_AUTHORING_PROMOTION",
        "category_filter": category_q or None,
        "candidate_count": total,
        "shown_count": len(shown),
        "state_counts": dict(sorted(readiness.items())),
        "binding_mode_counts": dict(sorted(binding_modes.items())),
        "semantic_group_counts": dict(sorted(semantic_groups.items())),
        "model_info_context_state_counts": dict(sorted(context_states.items())),
        "candidates": shown,
        "policy": {
            "folder_or_basename_guessing": False,
            "lod_nodes_must_exist_in_smd": True,
            "binding_must_be_registry_proven": True,
            "ambiguous_multi_inx_requires_explicit_model_info": True,
            "semantic_context_id_uses_skeleton_and_full_lod_groups": True,
            "canonical_profile_basename_match_requires_unique_associated_inx": True,
            "discovery_authorizes_writer": False,
        },
        "client_modified": False,
    }
