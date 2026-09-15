from __future__ import annotations

import hashlib
import json
from typing import Any

FORMAT = "PT_RIGID_MODEL_INFO_CONTEXT_AUDIT_V1"


def normalize_lod_groups(groups: dict[str, Any] | None) -> dict[str, list[str]]:
    groups = groups or {}
    return {tier: [str(x) for x in (groups.get(tier) or [])] for tier in ("high", "default", "low")}


def config_semantic_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "motion_smb": str(cfg.get("motion_smb") or "").replace("\\", "/"),
        "lod_groups": normalize_lod_groups(cfg.get("lod_groups") or {}),
    }


def config_semantic_signature(cfg: dict[str, Any]) -> tuple:
    payload = config_semantic_payload(cfg)
    return (
        payload["motion_smb"].casefold(),
        tuple(
            (tier, tuple(str(x).casefold() for x in payload["lod_groups"][tier]))
            for tier in ("high", "default", "low")
        ),
    )


def config_semantic_id(cfg: dict[str, Any]) -> str:
    payload = config_semantic_payload(cfg)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).casefold().encode("utf-8")
    return "RIC-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def logical_smd_node_names(asset) -> list[str]:
    """Return serialized SMD NodeName values known from the canonical inventory.

    Blender datablock names are intentionally irrelevant here: INX model groups
    address the serialized SMD NodeName values.  Duplicate chunks are retained
    because one INX name may legitimately select more than one serialized chunk.
    """
    record = getattr(asset, "source_record", {}) or {}
    names = record.get("object_names")
    if isinstance(names, list) and names:
        return [str(x) for x in names if str(x)]
    objects = record.get("objects")
    if isinstance(objects, list):
        out = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            name = obj.get("node_name") or obj.get("name")
            if name:
                out.append(str(name))
        if out:
            return out
    return []


def model_info_inx_configs(asset) -> list[dict[str, Any]]:
    """Return every registry-associated INX config for an asset.

    LOD coverage is independent from whether the INX also resolves a motion
    skeleton.  Equipment/model-info INX files commonly carry valid model
    groups while ``motion_smb`` is intentionally empty, so corpus audits must
    not silently discard them.
    """
    return [cfg for cfg in (getattr(asset, "configs", []) or []) if cfg.get("inx")]


def lod_model_info_configs(asset) -> list[dict[str, Any]]:
    """Return every associated INX that declares at least one LOD/model group."""
    out: list[dict[str, Any]] = []
    for cfg in model_info_inx_configs(asset):
        groups = normalize_lod_groups(cfg.get("lod_groups") or {})
        if any(groups[tier] for tier in ("high", "default", "low")):
            out.append(cfg)
    return out


def _latin1_key(value: str) -> bytes:
    return str(value).encode("latin-1", errors="replace").lower()


def inx_model_name_matches_node_name(inx_name: str, node_name: str) -> bool:
    """Return the deterministic effective key match for an INX model slot.

    The serialized INX slot is exactly 16 bytes while SMD NodeName is 32
    bytes.  Shipped assets repeatedly use a completely full 16-byte INX slot
    for longer SMD names; some deliberately repeat that same slot to cover
    multiple SMD chunks sharing the 16-byte prefix.  Therefore a *full* INX
    slot is compared against the first 16 serialized bytes of NodeName.

    Shorter INX names remain exact case-insensitive matches.  This is a fixed
    field-width rule only -- never fuzzy/alias matching.  Non-prefix legacy
    names still fail closed.  Runtime/game acceptance remains a separate 1.0
    gate; this rule only makes the authoring candidate reproduce the format's
    representable model-name key.
    """
    ikey = _latin1_key(inx_name)
    nkey = _latin1_key(node_name)
    if len(ikey) == 16:
        return nkey[:16] == ikey
    return nkey == ikey


def _lod_node_match_rows(requested: list[str], node_names: list[str]) -> list[dict[str, Any]]:
    """Describe exact, fixed-width-key, and genuinely missing relationships."""
    exact: dict[str, list[str]] = {}
    for name in node_names:
        exact.setdefault(str(name).casefold(), []).append(str(name))
    rows: list[dict[str, Any]] = []
    for raw in requested:
        name = str(raw)
        direct = list(exact.get(name.casefold(), []))
        if direct:
            rows.append({
                "requested": name, "match_kind": "EXACT_CASE_INSENSITIVE",
                "matched_nodes": direct, "authoring_match": True,
                "effective_key_bytes": len(_latin1_key(name)),
            })
            continue
        width_matches: list[str] = []
        if len(_latin1_key(name)) == 16:
            width_matches = [n for n in node_names if inx_model_name_matches_node_name(name, str(n))]
        if len(width_matches) == 1:
            kind = "INX_16BYTE_FIXED_KEY_UNIQUE"
        elif len(width_matches) > 1:
            kind = "INX_16BYTE_FIXED_KEY_MULTIPLE"
        else:
            kind = "MISSING"
        rows.append({
            "requested": name, "match_kind": kind,
            "matched_nodes": [str(x) for x in width_matches],
            "authoring_match": bool(width_matches),
            "effective_key_bytes": len(_latin1_key(name)),
        })
    return rows

def lod_node_coverage(asset, cfg: dict[str, Any], lod: str) -> dict[str, Any]:
    """Check whether an INX LOD group is representable by the SMD model key.

    Exact names and deterministic full-16-byte field-key matches are accepted.
    Non-prefix aliases/missing names remain fail-closed.
    """
    lod = str(lod)
    groups = normalize_lod_groups(cfg.get("lod_groups") or {})
    requested = [str(x) for x in groups.get(lod, []) if str(x)]
    node_names = logical_smd_node_names(asset)
    if not node_names:
        return {
            "status": "UNKNOWN",
            "lod": lod,
            "requested_nodes": requested,
            "missing_nodes": [],
            "matched_chunk_count": 0,
            "inventory_node_names_available": False,
            "match_rows": [],
            "fixed_width_key_nodes": [],
            "fixed_width_multi_match_nodes": [],
            "unexplained_missing_nodes": [],
        }
    match_rows = _lod_node_match_rows(requested, node_names)
    missing = [r["requested"] for r in match_rows if not r.get("authoring_match")]
    fixed_width = [
        r["requested"] for r in match_rows
        if str(r.get("match_kind") or "").startswith("INX_16BYTE_FIXED_KEY_")
    ]
    fixed_width_multi = [
        r["requested"] for r in match_rows
        if r.get("match_kind") == "INX_16BYTE_FIXED_KEY_MULTIPLE"
    ]
    unexplained = [r["requested"] for r in match_rows if r.get("match_kind") == "MISSING"]
    matched_chunk_count = sum(len(r.get("matched_nodes") or []) for r in match_rows if r.get("authoring_match"))
    return {
        "status": "PASS" if not missing else "FAIL",
        "lod": lod,
        "requested_nodes": requested,
        "missing_nodes": missing,
        "matched_chunk_count": matched_chunk_count,
        "inventory_node_names_available": True,
        "match_rows": match_rows,
        "fixed_width_key_nodes": fixed_width,
        "fixed_width_multi_match_nodes": fixed_width_multi,
        "unexplained_missing_nodes": unexplained,
    }


def usable_model_info_configs(asset) -> list[dict[str, Any]]:
    return [cfg for cfg in (getattr(asset, "configs", []) or []) if cfg.get("inx") and cfg.get("motion_smb")]


def classify_asset_model_info_context(asset) -> dict[str, Any]:
    configs = usable_model_info_configs(asset)
    if not configs:
        return {
            "state": "NO_USABLE_MODEL_INFO",
            "config_count": 0,
            "semantic_signature_count": 0,
            "skeleton_signature_count": 0,
            "lod_signature_count": 0,
            "ambiguity_dimensions": [],
            "requires_explicit_model_info": False,
            "auto_selection_safe": False,
        }
    if len(configs) == 1:
        return {
            "state": "SINGLE_CONFIG",
            "config_count": 1,
            "semantic_signature_count": 1,
            "skeleton_signature_count": 1,
            "lod_signature_count": 1,
            "ambiguity_dimensions": [],
            "requires_explicit_model_info": False,
            "auto_selection_safe": True,
        }
    signatures = {config_semantic_signature(cfg) for cfg in configs}
    skeleton_signatures = {str(cfg.get("motion_smb") or "").replace("\\", "/").casefold() for cfg in configs}
    lod_signatures = {
        tuple((tier, tuple(x.casefold() for x in normalize_lod_groups(cfg.get("lod_groups") or {})[tier])) for tier in ("high", "default", "low"))
        for cfg in configs
    }
    equivalent = len(signatures) == 1
    dimensions = []
    if len(skeleton_signatures) > 1:
        dimensions.append("SKELETON")
    if len(lod_signatures) > 1:
        dimensions.append("LOD_GROUPS")
    return {
        "state": "SEMANTICALLY_EQUIVALENT" if equivalent else "AMBIGUOUS_MODEL_INFO_CONFIG",
        "config_count": len(configs),
        "semantic_signature_count": len(signatures),
        "skeleton_signature_count": len(skeleton_signatures),
        "lod_signature_count": len(lod_signatures),
        "ambiguity_dimensions": dimensions,
        "requires_explicit_model_info": not equivalent,
        "auto_selection_safe": equivalent,
    }


def equivalent_model_info_paths(asset, cfg: dict[str, Any]) -> list[str]:
    sig = config_semantic_signature(cfg)
    return sorted(
        [
            str(other.get("inx") or "").replace("\\", "/")
            for other in usable_model_info_configs(asset)
            if config_semantic_signature(other) == sig
        ],
        key=str.casefold,
    )


def audit_rigid_model_info_contexts(registry, *, category: str | None = None, sample_limit: int = 50) -> dict[str, Any]:
    assets = registry.list_assets(category=category, family="SMD_MODEL_062_RIGID_PHYSIQUE")
    rows: list[dict[str, Any]] = []
    counts = {
        "single_config_assets": 0,
        "equivalent_multi_config_assets": 0,
        "ambiguous_multi_config_assets": 0,
        "no_usable_model_info_assets": 0,
    }
    ambiguity_dimension_counts = {"SKELETON": 0, "LOD_GROUPS": 0}
    assets_with_missing_lod_nodes: set[str] = set()
    choices_with_missing_lod_nodes = 0
    for asset in assets:
        cls = classify_asset_model_info_context(asset)
        state = cls["state"]
        if state == "NO_USABLE_MODEL_INFO":
            counts["no_usable_model_info_assets"] += 1
            continue
        if state == "SINGLE_CONFIG":
            counts["single_config_assets"] += 1
            continue
        if state == "SEMANTICALLY_EQUIVALENT":
            counts["equivalent_multi_config_assets"] += 1
        else:
            counts["ambiguous_multi_config_assets"] += 1
            for dimension in cls.get("ambiguity_dimensions") or []:
                ambiguity_dimension_counts[dimension] = ambiguity_dimension_counts.get(dimension, 0) + 1
        configs = usable_model_info_configs(asset)
        choices = []
        for cfg in sorted(configs, key=lambda x: str(x.get("inx") or "").casefold()):
            groups = normalize_lod_groups(cfg.get("lod_groups") or {})
            actual = next((lod for lod in ("default", "high", "low") if groups.get(lod)), None)
            coverage = {
                tier: lod_node_coverage(asset, cfg, tier)
                for tier in ("high", "default", "low") if groups.get(tier)
            }
            if any(row.get("status") == "FAIL" for row in coverage.values()):
                choices_with_missing_lod_nodes += 1
                assets_with_missing_lod_nodes.add(asset.asset_id)
            choices.append({
                "inx": str(cfg.get("inx") or "").replace("\\", "/"),
                "motion_smb": str(cfg.get("motion_smb") or "").replace("\\", "/"),
                "auto_lod": actual,
                "lod_groups": groups,
                "semantic_context_id": config_semantic_id(cfg),
                "lod_node_coverage": coverage,
            })
        rows.append({
            "asset_id": asset.asset_id,
            "asset": asset.primary_path,
            "category": asset.category,
            "config_count": cls["config_count"],
            "semantic_signature_count": cls["semantic_signature_count"],
            "skeleton_signature_count": cls["skeleton_signature_count"],
            "lod_signature_count": cls["lod_signature_count"],
            "ambiguity_dimensions": list(cls.get("ambiguity_dimensions") or []),
            "state": state,
            "requires_explicit_model_info": cls["requires_explicit_model_info"],
            "choices": choices,
        })
    rows.sort(key=lambda x: (x["state"] != "AMBIGUOUS_MODEL_INFO_CONFIG", x["asset"].casefold()))
    limited = rows if int(sample_limit) <= 0 else rows[: int(sample_limit)]
    return {
        "format": FORMAT,
        "status": "PASS",
        "rigid_asset_count": len(assets),
        **counts,
        "multi_config_assets": counts["equivalent_multi_config_assets"] + counts["ambiguous_multi_config_assets"],
        "rows_total": len(rows),
        "ambiguity_dimension_counts": ambiguity_dimension_counts,
        "assets_with_missing_lod_nodes": len(assets_with_missing_lod_nodes),
        "choices_with_missing_lod_nodes": choices_with_missing_lod_nodes,
        "rows": limited,
        "policy": {
            "ambiguous_requires_explicit_model_info": True,
            "equivalence_compares_full_lod_groups_and_skeleton": True,
            "semantic_context_id_ignores_inx_filename": True,
            "generic_import_missing_lod_nodes_fail_closed": True,
            "client_write_authorized": False,
        },
        "client_modified": False,
    }



def effective_lod_node_coverage(asset, cfg: dict[str, Any], lod: str) -> dict[str, Any]:
    """Return authoring-effective coverage without fuzzy alias matching.

    A legacy config with exactly one declared tier has no alternative LOD to
    select.  When its labels do not map to serialized SMD NodeName keys, the
    safe authoring behavior is to keep the whole source container visible,
    preserving every shipped chunk and the INX bytes unchanged.  Multi-tier
    mismatches remain fail-closed.
    """
    cov=dict(lod_node_coverage(asset,cfg,lod))
    if cov.get("status") != "FAIL":
        cov.setdefault("selection_mode","MODEL_GROUP_KEYS")
        cov.setdefault("effective_selected_nodes",list(cov.get("requested_nodes") or []))
        return cov
    groups=normalize_lod_groups(cfg.get("lod_groups") or {})
    nonempty=[tier for tier in ("high","default","low") if groups.get(tier)]
    if len(nonempty)==1 and nonempty[0]==str(lod):
        seen=set(); nodes=[]
        for raw in logical_smd_node_names(asset):
            key=str(raw).casefold()
            if key in seen: continue
            seen.add(key); nodes.append(str(raw))
        if nodes:
            cov.update({
                "status":"PASS",
                "selection_mode":"SINGLE_TIER_FULL_CONTAINER",
                "effective_selected_nodes":nodes,
                "legacy_unmapped_model_labels":list(cov.get("missing_nodes") or []),
                "full_container_preserves_unmapped_labels":True,
            })
    return cov

def audit_rigid_lod_context_corpus(registry, *, sample_limit: int = 100) -> dict[str, Any]:
    """Classify every associated rigid INX and each declared LOD/model tier.

    This deliberately audits INX model groups even when ``motion_smb`` is not
    resolved. LOD identity and skeleton resolution are separate contracts.
    Full 16-byte INX slots use the proven serialized fixed-width model key.
    Non-prefix mismatches remain fail-closed and are separated into single-tier
    legacy labels versus multi-tier content inconsistencies.
    """
    rows=[]
    assets=registry.list_assets(family="SMD_MODEL_062_RIGID_PHYSIQUE")
    config_count=lod_config_count=importable=inconsistent=legacy_single_tier_alias=prefix_unverified=single_tier_full_container=no_lod=unknown=0
    tier_count=tier_pass=tier_missing=tier_unknown=0
    for asset in assets:
        for cfg in model_info_inx_configs(asset):
            config_count += 1
            groups=normalize_lod_groups(cfg.get("lod_groups") or {})
            coverage={
                lod: effective_lod_node_coverage(asset,cfg,lod)
                for lod in ("high","default","low") if groups.get(lod)
            }
            if coverage:
                lod_config_count += 1
            tier_count += len(coverage)
            for cov in coverage.values():
                st=str(cov.get("status") or "UNKNOWN")
                if st=="PASS": tier_pass += 1
                elif st=="FAIL": tier_missing += 1
                else: tier_unknown += 1
            if not coverage:
                state="NO_LOD_GROUPS"; no_lod += 1
            elif any(str(c.get("status"))=="UNKNOWN" for c in coverage.values()):
                state="UNKNOWN"; unknown += 1
            elif any(str(c.get("status"))=="FAIL" for c in coverage.values()):
                nonempty_tiers = [tier for tier in ("high", "default", "low") if groups.get(tier)]
                if len(nonempty_tiers) == 1:
                    state="LEGACY_SINGLE_TIER_MODEL_ALIAS_FAIL_CLOSED"; legacy_single_tier_alias += 1
                else:
                    state="MISSING_SMD_NODES_FAIL_CLOSED"; inconsistent += 1
            else:
                uses_full_container = any(c.get("selection_mode") == "SINGLE_TIER_FULL_CONTAINER" for c in coverage.values())
                uses_fixed_width = any(c.get("fixed_width_key_nodes") for c in coverage.values())
                if uses_full_container:
                    state="AUTHORABLE_SINGLE_TIER_FULL_CONTAINER"; single_tier_full_container += 1
                elif uses_fixed_width:
                    state="IMPORTABLE_FIXED16_MODEL_KEY"; prefix_unverified += 1
                else:
                    state="IMPORTABLE"
                importable += 1
            rows.append({
                "asset_id":asset.asset_id,"asset":asset.primary_path,"category":asset.category,
                "inx":str(cfg.get("inx") or "").replace("\\","/"),
                "motion_smb":str(cfg.get("motion_smb") or "").replace("\\","/"),
                "motion_smb_resolved":bool(cfg.get("motion_smb")),
                "semantic_context_id":config_semantic_id(cfg),"state":state,
                "lod_groups":groups,"lod_node_coverage":coverage,
                "missing_nodes":sorted({n for c in coverage.values() for n in (c.get("missing_nodes") or [])},key=str.casefold),
                "fixed_width_key_nodes":sorted({n for c in coverage.values() for n in (c.get("fixed_width_key_nodes") or [])},key=str.casefold),
                "fixed_width_multi_match_nodes":sorted({n for c in coverage.values() for n in (c.get("fixed_width_multi_match_nodes") or [])},key=str.casefold),
                "unexplained_missing_nodes":sorted({n for c in coverage.values() for n in (c.get("unexplained_missing_nodes") or [])},key=str.casefold),
            })
    bad=[r for r in rows if r["state"] in {
        "MISSING_SMD_NODES_FAIL_CLOSED","LEGACY_SINGLE_TIER_MODEL_ALIAS_FAIL_CLOSED","UNKNOWN"
    }]
    authorable_states={"IMPORTABLE","IMPORTABLE_FIXED16_MODEL_KEY","AUTHORABLE_SINGLE_TIER_FULL_CONTAINER"}
    asset_rows={}
    for row in rows:
        if not any((row.get("lod_groups") or {}).get(t) for t in ("high","default","low")):
            continue
        asset_rows.setdefault(str(row.get("asset")),[]).append(row)
    asset_summary=[]
    for asset_path, cfg_rows in sorted(asset_rows.items(), key=lambda kv: kv[0].casefold()):
        authorable=[r for r in cfg_rows if str(r.get("state")) in authorable_states]
        failed=[r for r in cfg_rows if str(r.get("state")) == "MISSING_SMD_NODES_FAIL_CLOSED"]
        unknown_rows=[r for r in cfg_rows if str(r.get("state")) == "UNKNOWN"]
        asset_summary.append({
            "asset":asset_path,
            "lod_config_count":len(cfg_rows),
            "authorable_config_count":len(authorable),
            "fail_closed_config_count":len(failed),
            "unknown_config_count":len(unknown_rows),
            "authorable":bool(authorable) and not unknown_rows,
            "authorable_with_diagnosed_fail_closed_outliers":bool(authorable) and bool(failed) and not unknown_rows,
            "authorable_inx":[r.get("inx") for r in authorable],
            "fail_closed_inx":[r.get("inx") for r in failed],
        })
    assets_without_authorable=[r for r in asset_summary if not r["authorable"]]
    assets_with_diagnosed_outliers=[r for r in asset_summary if r["authorable_with_diagnosed_fail_closed_outliers"]]
    return {
        "format":"PT_RIGID_LOD_CONTEXT_CORPUS_V3",
        "status":"PASS" if assets and unknown==0 and tier_unknown==0 else ("EMPTY" if not assets else "FAIL"),
        "rigid_asset_count":len(assets),"config_count":config_count,"lod_config_count":lod_config_count,
        "lod_asset_count":len(asset_summary),
        "authorable_lod_asset_count":sum(1 for r in asset_summary if r["authorable"]),
        "assets_without_authorable_lod_config_count":len(assets_without_authorable),
        "assets_with_diagnosed_fail_closed_config_outliers_count":len(assets_with_diagnosed_outliers),
        "diagnosed_fail_closed_config_outlier_count":sum(int(r["fail_closed_config_count"]) for r in assets_with_diagnosed_outliers),
        "importable_config_count":importable,"content_inconsistent_config_count":inconsistent,
        "legacy_single_tier_alias_config_count":legacy_single_tier_alias,
        "single_tier_full_container_config_count":single_tier_full_container,
        "fixed_width_model_key_config_count":prefix_unverified,
        "no_lod_group_config_count":no_lod,"unknown_config_count":unknown,
        "lod_tier_count":tier_count,"lod_tier_pass_count":tier_pass,
        "lod_tier_missing_node_count":tier_missing,"lod_tier_unknown_count":tier_unknown,
        "classified_exception_sample":bad[:max(0,int(sample_limit))],
        "assets_without_authorable_lod_config":assets_without_authorable[:max(0,int(sample_limit))],
        "assets_with_diagnosed_fail_closed_config_outliers":assets_with_diagnosed_outliers[:max(0,int(sample_limit))],
        "asset_summary":asset_summary,
        "rows":rows,
        "policy":{
            "missing_smd_nodes_are_fail_closed_content_inconsistency":True,
            "missing_nodes_are_never_synthesized_or_guessed":True,
            "inx_full_16byte_slot_uses_serialized_16byte_model_key":True,
            "inx_fixed16_rule_is_not_fuzzy_or_alias_matching":True,
            "non_prefix_missing_names_remain_fail_closed":True,
            "single_tier_unmapped_labels_use_full_container_without_alias_guessing":True,
            "multi_tier_missing_names_are_content_inconsistencies":True,
            "lod_audit_requires_motion_smb":False,
            "single_and_multi_config_assets_are_both_audited":True,
            "production_authorized":False,"client_write_authorized":False,
        },
        "client_modified":False,
    }

