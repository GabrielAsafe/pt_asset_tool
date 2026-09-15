from __future__ import annotations

import pathlib
from collections import Counter, defaultdict
from typing import Any

from .release_1_coverage import CONTENT_DOMAINS, content_domain
from .standalone_rigid_devtest import (
    authorable_lod_model_info_contexts as exact_lod_model_info_contexts,
    explicit_skeleton_candidate,
    model_info_lod_context_available,
    model_info_lod_config_available,
)

FORMAT = "PT_RIGID_CONTEXT_CENSUS_V1"


def _norm(value: str | None) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def _structural_check(
    source: pathlib.Path,
    skeleton: pathlib.Path,
    *,
    smd_cache: dict[str, Any] | None = None,
    smb_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Reuse the physically-proven parser/gate rather than maintaining a second
    # interpretation of Physique or SMB node blocks.
    from pt_character_structural_gate_v2 import parse_smd, parse_smb

    skey = str(pathlib.Path(source).resolve())
    bkey = str(pathlib.Path(skeleton).resolve())
    if smd_cache is not None and skey in smd_cache:
        smd = smd_cache[skey]
    else:
        smd = parse_smd(source)
        if smd_cache is not None:
            smd_cache[skey] = smd
    if smb_cache is not None and bkey in smb_cache:
        smb = smb_cache[bkey]
    else:
        smb = parse_smb(skeleton)
        if smb_cache is not None:
            smb_cache[bkey] = smb
    missing = sorted(
        x for x in smd["bind_bone_names"]
        if x and x not in smb["bone_names"]
    )
    parent_errors = list(smb.get("parent_errors") or [])
    return {
        "status": "PASS" if not missing and not parent_errors else "FAIL",
        "missing_bind_bones": missing,
        "parent_error_count": len(parent_errors),
        "bind_bones_used": len(smd["bind_bone_names"]),
        "skeleton_bones": len(smb["bones"]),
    }


def audit_rigid_context_census(
    registry,
    resolver=None,
    *,
    physical: bool = False,
    sample_limit: int = 50,
) -> dict[str, Any]:
    """Classify every Release-1 rigid Model0.62 asset into an authoring path.

    This is deliberately corpus-wide. Blender mutation/reimport is sampled by
    the semantic devtests, while this census proves that every rigid asset in
    PLAYER/NPC/MONSTER/WEAPON_ITEM/EFFECT/MAP has an unambiguous supported
    context class or is reported explicitly as unresolved.

    When ``physical`` is true, standalone sibling hypotheses are promoted only
    after the structural Physique-vs-SMB gate passes on the actual files. No
    filename/directory relation becomes binding evidence by itself.
    """
    physical = bool(physical)
    by_domain: dict[str, Counter] = {d: Counter() for d in CONTENT_DOMAINS}
    unresolved: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    smd_cache: dict[str, Any] = {}
    smb_cache: dict[str, Any] = {}

    for asset in registry.assets:
        if str(asset.family or "") != "SMD_MODEL_062_RIGID_PHYSIQUE":
            continue
        domain = content_domain(asset)
        if domain not in by_domain:
            continue

        row: dict[str, Any] = {
            "asset_id": asset.asset_id,
            "asset": asset.primary_path,
            "domain": domain,
            "binding_mode": str(asset.binding_mode or "NONE"),
            "binding_source": str(asset.binding_source or "NONE"),
            "binding_skeleton_smb": _norm(asset.binding_skeleton_smb),
            "config_count": len(asset.configs or []),
        }
        by_domain[domain]["TOTAL"] += 1

        if model_info_lod_context_available(asset):
            row["context_class"] = "MODEL_INFO_LOD"
            if not physical:
                row["status"] = "PASS"
                by_domain[domain]["MODEL_INFO_LOD"] += 1
                rows.append(row)
                continue
            if resolver is None:
                row["status"] = "FAIL"
                row["reason"] = "PHYSICAL_CENSUS_REQUIRES_RESOLVER"
                by_domain[domain]["UNRESOLVED"] += 1
                failures.append(row)
                rows.append(row)
                continue
            # A normal INX->SMB context is not exempt from the physical gate.
            # Validate every distinct exact authoring context exposed by this
            # asset; otherwise one good config could hide a stale/corrupt sibling
            # config in the same model-info set.
            contexts = exact_lod_model_info_contexts(asset, require_motion_smb=True)
            unique: dict[tuple[str, str], dict[str, Any]] = {}
            for ctx in contexts:
                key = (_norm(ctx.get("inx")).casefold(), _norm(ctx.get("motion_smb")).casefold())
                if key[0] and key[1]:
                    unique.setdefault(key, ctx)
            try:
                if not unique:
                    raise RuntimeError("MODEL_INFO_LOD_CONTEXT_DISAPPEARED")
                source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
                physical_contexts=[]
                for ctx in unique.values():
                    inx_logical = _norm(ctx.get("inx"))
                    smb_logical = _norm(ctx.get("motion_smb"))
                    inx_path = pathlib.Path(resolver.resolve(inx_logical, required=True)).resolve()
                    skeleton = pathlib.Path(resolver.resolve(smb_logical, required=True)).resolve()
                    structural = _structural_check(
                        source, skeleton, smd_cache=smd_cache, smb_cache=smb_cache,
                    )
                    physical_contexts.append({
                        "model_info_inx": inx_logical,
                        "model_info_path": str(inx_path),
                        "skeleton_smb": smb_logical,
                        "skeleton_path": str(skeleton),
                        "structural_gate": structural,
                    })
                    if structural.get("status") != "PASS":
                        raise RuntimeError(f"STRUCTURAL_GATE_FAIL:{smb_logical}")
                row["physical_source"] = str(source)
                row["physical_contexts"] = physical_contexts
                row["status"] = "PASS"
                by_domain[domain]["MODEL_INFO_LOD"] += 1
            except Exception as exc:
                row["status"] = "FAIL"
                row["reason"] = f"{type(exc).__name__}: {exc}"
                by_domain[domain]["UNRESOLVED"] += 1
                failures.append(row)
            rows.append(row)
            continue

        has_exact_lod_config = model_info_lod_config_available(asset)
        row["exact_lod_config_available"] = bool(has_exact_lod_config)
        probe = explicit_skeleton_candidate(registry, asset)
        row["candidate_skeleton_smb"] = _norm(probe.get("candidate_smb"))
        row["candidate_basis"] = str(probe.get("candidate_basis") or "")
        if not probe.get("candidate_available"):
            row["context_class"] = "UNRESOLVED"
            row["status"] = "FAIL"
            row["reason"] = "NO_UNAMBIGUOUS_SKELETON_CONTEXT"
            by_domain[domain]["UNRESOLVED"] += 1
            unresolved.append(row)
            rows.append(row)
            continue

        if has_exact_lod_config:
            row["context_class"] = "MODEL_INFO_LOD_EXPLICIT_SKELETON"
            if not physical and probe.get("binding_proven"):
                row["status"] = "PASS_OFFLINE_EVIDENCE"
                by_domain[domain]["MODEL_INFO_LOD_EXPLICIT_SKELETON"] += 1
                rows.append(row)
                continue
            if not physical:
                row["status"] = "PENDING_PHYSICAL_STRUCTURAL_GATE"
                by_domain[domain]["MODEL_INFO_LOD_EXPLICIT_SKELETON_PENDING"] += 1
                rows.append(row)
                continue
        elif probe.get("binding_proven"):
            row["context_class"] = "RESOLVED_SKELETON"
            if not physical:
                row["status"] = "PASS_OFFLINE_EVIDENCE"
                by_domain[domain]["RESOLVED_SKELETON"] += 1
                rows.append(row)
                continue

        else:
            row["context_class"] = "STANDALONE_STRUCTURAL"
            if not physical:
                row["status"] = "PENDING_PHYSICAL_STRUCTURAL_GATE"
                by_domain[domain]["STANDALONE_PENDING"] += 1
                rows.append(row)
                continue

        # Physical validation for both a registry-resolved skeleton and an
        # adjacency-only standalone hypothesis. This catches stale caches too.
        if resolver is None:
            row["status"] = "FAIL"
            row["reason"] = "PHYSICAL_CENSUS_REQUIRES_RESOLVER"
            by_domain[domain]["UNRESOLVED"] += 1
            failures.append(row)
            rows.append(row)
            continue
        try:
            source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
            skeleton = pathlib.Path(resolver.resolve(row["candidate_skeleton_smb"], required=True)).resolve()
            structural = _structural_check(
                source, skeleton, smd_cache=smd_cache, smb_cache=smb_cache,
            )
            row["physical_source"] = str(source)
            row["physical_skeleton"] = str(skeleton)
            row["structural_gate"] = structural
            if structural.get("status") != "PASS":
                raise RuntimeError("STRUCTURAL_GATE_FAIL")
            row["status"] = "PASS"
            if has_exact_lod_config:
                by_domain[domain]["MODEL_INFO_LOD_EXPLICIT_SKELETON"] += 1
            elif probe.get("binding_proven"):
                by_domain[domain]["RESOLVED_SKELETON"] += 1
            else:
                by_domain[domain]["STANDALONE_STRUCTURAL_PASS"] += 1
        except Exception as exc:
            row["status"] = "FAIL"
            row["reason"] = f"{type(exc).__name__}: {exc}"
            by_domain[domain]["UNRESOLVED"] += 1
            failures.append(row)
        rows.append(row)

    total = sum(c.get("TOTAL", 0) for c in by_domain.values())
    unresolved_count = sum(c.get("UNRESOLVED", 0) for c in by_domain.values())
    pending_count = sum(c.get("STANDALONE_PENDING", 0) for c in by_domain.values())
    status = "PASS" if unresolved_count == 0 and (not physical or pending_count == 0) else "FAIL"
    return {
        "format": FORMAT,
        "status": status,
        "physical": physical,
        "rigid_asset_count": total,
        "unresolved_count": unresolved_count,
        "standalone_pending_count": pending_count,
        "by_domain": {d: dict(sorted(c.items())) for d, c in by_domain.items()},
        "unresolved_sample": (unresolved + failures)[: max(0, int(sample_limit))],
        "rows": rows,
        "policy": {
            "corpus_wide_context_classification": True,
            "filename_similarity_is_binding_evidence": False,
            "standalone_hypothesis_requires_physical_structural_pass": True,
            "blender_sampling_is_separate_from_context_census": True,
            "production_authorized": False,
            "client_write_authorized": False,
        },
        "client_modified": False,
    }
