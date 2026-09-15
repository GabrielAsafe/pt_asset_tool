from __future__ import annotations

import collections
import json
from typing import Any

from .release_scope import MIXED_PHYSIQUE_RELEASE_1_SCOPE, MIXED_PHYSIQUE_RELEASE_1_BLOCKING

from .rigid_model_info import (
    classify_asset_model_info_context,
    lod_node_coverage, effective_lod_node_coverage,
    usable_model_info_configs,
    lod_model_info_configs,
)

FORMAT = "PT_ASSET_RELEASE_1_COVERAGE_V1"
PLAN_FORMAT = "PT_ASSET_RELEASE_1_AUTOMATED_GATE_PLAN_V1"

CONTENT_DOMAINS = ("PLAYER", "NPC", "MONSTER", "WEAPON_ITEM", "EFFECT", "MAP")
CAPABILITIES = (
    "MODEL062_RIGID",
    "MODEL062_STATIC",
    "MODEL062_MIXED",
    "SMB_EXISTING",
    "INX_MODERN_LEGACY_OUTLIERS",
    "BMP_TGA_PROPRIETARY",
    "STAGE072",
    "OBJECT_LOCAL_ANIMATION",
    "MULTILAYER_TEXLINK",
    "LOD",
    "MATERIALS",
    "TEXTURES",
    "RIGGING",
    "EXISTING_ANIMATION",
)


def content_domain_from_values(relative_path: str, category: str = "") -> str:
    """Classify a physical/catalog path into the Release 1.0 content contract.

    Keeping this independent from AssetRegistry objects lets physical corpus
    audits (object-local, TexLink, texture/support files) attribute evidence to
    the same PLAYER/NPC/MONSTER/WEAPON_ITEM/EFFECT/MAP matrix without guessing
    from a broader family count.
    """
    rel = str(relative_path or "").replace("\\", "/")
    lo = rel.casefold()
    category = str(category or "").upper()

    # The two canonical character roots are stronger evidence than the broad
    # inventory category heuristic.  This specifically avoids false MAP_STAGE
    # hits such as char/monster/Bear/Maplebear.smd.
    if lo.startswith("char/npc/"):
        return "NPC"
    if lo.startswith("char/monster/"):
        return "MONSTER"

    # Outside those roots, the explicit semantic category wins over the
    # physical folder.  Several real weapon/monster assets intentionally live
    # under Effect/, so path-first classification would misstate Release 1.0
    # coverage by content type.
    category_domain = {
        "NPC": "NPC",
        "MOB_MONSTER": "MONSTER",
        "WEAPON_ITEM": "WEAPON_ITEM",
        "EFFECT": "EFFECT",
        "CHARACTER": "PLAYER",
    }.get(category)
    if category_domain:
        return category_domain

    if lo.startswith("effect/") or "/effect/" in lo:
        return "EFFECT"
    if lo.startswith("weapons/") or "/items/" in lo or lo.startswith("items/"):
        return "WEAPON_ITEM"
    if lo.startswith("field/") or lo.startswith("maps/") or lo.startswith("game/maps/") or lo.startswith("cselect/"):
        return "MAP"
    if lo.startswith("char/"):
        return "PLAYER"
    # MAP_STAGE is the broadest inventory category heuristic (tokens such as
    # "field"/"map" can occur in effects or monster names), so use it only
    # after stronger semantic/path evidence has been exhausted.
    if category == "MAP_STAGE":
        return "MAP"
    return "OTHER"


def content_domain(asset) -> str:
    return content_domain_from_values(
        str(asset.primary_path or ""),
        str(getattr(asset, "category", "") or ""),
    )


def _cell(count: int, state: str, *, next_gate: str | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"asset_count": int(count), "state": state}
    if next_gate:
        row["next_gate"] = next_gate
    if evidence:
        row["evidence"] = evidence
    return row


def _counts(registry) -> dict[str, Any]:
    by_domain = {d: collections.Counter() for d in CONTENT_DOMAINS}
    totals = collections.Counter()
    examples: dict[str, dict[str, list[str]]] = {d: collections.defaultdict(list) for d in CONTENT_DOMAINS}
    smb_by_parent: dict[str, list[str]] = collections.defaultdict(list)
    for record in registry.records:
        ext = str(record.get("extension") or "").lower()
        rel = str(record.get("relative_path") or "").replace("\\", "/").strip("/")
        category = str(record.get("category_hint") or "")
        domain = content_domain_from_values(rel, category)
        if domain in by_domain:
            if ext == ".smb":
                by_domain[domain]["PHYSICAL_SMB_FILE"] += 1
            elif ext == ".inx":
                by_domain[domain]["PHYSICAL_INX_FILE"] += 1
        if ext != ".smb":
            continue
        parent = str(__import__("pathlib").PurePosixPath(rel).parent).casefold()
        smb_by_parent[parent].append(rel)
    for asset in registry.assets:
        domain = content_domain(asset)
        if domain not in by_domain:
            continue
        fam = str(asset.family or "")
        by_domain[domain][fam] += 1
        totals[fam] += 1
        if len(examples[domain][fam]) < 3:
            examples[domain][fam].append(asset.primary_path)
        if asset.configs:
            by_domain[domain]["HAS_INX_CONFIG"] += 1
        if asset.binding_skeleton_smb:
            by_domain[domain]["HAS_SMB_BINDING"] += 1
        if asset.animation_binding_ready:
            by_domain[domain]["ANIMATION_BINDING_READY"] += 1
        if asset.rigid_binding_ready:
            by_domain[domain]["RIGGING_READY"] += 1
        elif asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            import pathlib as _pathlib
            p = _pathlib.PurePosixPath(str(asset.primary_path or "").replace("\\", "/"))
            siblings = smb_by_parent.get(p.parent.as_posix().casefold(), [])
            exact = [x for x in siblings if _pathlib.PurePosixPath(x).stem.casefold() == p.stem.casefold()]
            if len(exact) == 1 or len(siblings) == 1:
                by_domain[domain]["STANDALONE_SIBLING_SMB_HYPOTHESIS"] += 1
        if asset.textures:
            by_domain[domain]["HAS_TEXTURE_REFS"] += 1
            if asset.kind == "SMD_MODEL_062":
                by_domain[domain]["MODEL062_HAS_TEXTURE_REFS"] += 1
        if int(asset.material_count or 0) > 0:
            by_domain[domain]["HAS_MATERIALS"] += 1
            if asset.kind == "SMD_MODEL_062":
                by_domain[domain]["MODEL062_HAS_MATERIALS"] += 1
        if any(any((cfg.get("lod_groups") or {}).get(t) or [] for t in ("high", "default", "low")) for cfg in asset.configs):
            by_domain[domain]["HAS_LOD_GROUPS"] += 1
        if (
            str(asset.kind or "") == "SMD_MODEL_062"
            and int(asset.total_faces or 0) > 0
            and int((asset.source_record or {}).get("total_texlinks") or 0) > int(asset.total_faces or 0)
        ):
            by_domain[domain]["MULTILAYER_TEXLINK_CANDIDATE"] += 1

    # The inventory preserves enough fixed object-layout information to prove
    # that object-local key arrays exist without opening the client files.
    # Use that structural census for matrix presence; the physical corpus audit
    # remains authoritative for exact ROT/POS/SCALE/TmFrame subtype support.
    try:
        from .object_local_audit import audit_object_local
        object_local = audit_object_local(registry.records, limit=10**9)
        for row in object_local.get("candidates") or []:
            domain = content_domain_from_values(row.get("path") or "", row.get("category") or "")
            if domain in by_domain:
                by_domain[domain]["OBJECT_LOCAL_CANDIDATE"] += 1
    except Exception:
        # Coverage generation must remain usable with older/minimal registries.
        # In that case the cell explicitly remains discovery-pending below.
        pass
    return {
        "by_domain": {k: dict(v) for k, v in by_domain.items()},
        "family_totals": dict(totals),
        "examples": {d: {k: list(v) for k, v in fam.items()} for d, fam in examples.items()},
    }


def build_release_1_coverage(registry, *, external_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    counts = _counts(registry)
    by_domain = counts["by_domain"]
    ext = dict(external_evidence or {})
    canonical_rigid_auto = set(ext.get("rigid_automated_pass_domains") or [])
    rigid_physical_parse_auto = set(ext.get("rigid_physical_parse_pass_domains") or [])
    rigid_physical_parse_available = "rigid_physical_parse_pass_domains" in ext
    rigid_context_census = {str(k): dict(v or {}) for k, v in (ext.get("rigid_context_census_by_domain") or {}).items()}
    rigid_context_census_available = "rigid_context_census_by_domain" in ext
    rigid_context_pass_domains = set(ext.get("rigid_context_census_pass_domains") or [])
    lod_corpus_pass_domains = set(ext.get("lod_corpus_pass_domains") or [])
    lod_content_inconsistent = {str(k): int(v or 0) for k, v in (ext.get("lod_content_inconsistent_by_domain") or {}).items()}
    lod_single_tier_full_container = {str(k): int(v or 0) for k, v in (ext.get("lod_single_tier_full_container_by_domain") or {}).items()}
    lod_assets_without_authorable = {str(k): int(v or 0) for k, v in (ext.get("lod_assets_without_authorable_config_by_domain") or {}).items()}
    lod_assets_with_outliers = {str(k): int(v or 0) for k, v in (ext.get("lod_assets_with_diagnosed_fail_closed_outliers_by_domain") or {}).items()}
    lod_fixed16 = {str(k): int(v or 0) for k, v in (ext.get("lod_fixed16_model_key_by_domain") or {}).items()}
    static_auto = set(ext.get("static_automated_pass_domains") or [])
    static_corpus_auto = set(ext.get("static_corpus_pass_domains") or [])
    static_corpus_available = "static_corpus_pass_domains" in ext
    static_physical_parse_auto = set(ext.get("static_physical_parse_pass_domains") or [])
    static_physical_parse_available = "static_physical_parse_pass_domains" in ext
    animation_auto = set(ext.get("animation_pose_pass_domains") or [])
    animated_smb_physical = {str(k): int(v or 0) for k, v in (ext.get("animated_smb_physical_by_domain") or {}).items()}
    smb_animation_census_available = "animated_smb_physical_by_domain" in ext
    material_auto = set(ext.get("model062_material_pass_domains") or [])
    model062_texture_presence_auto = set(ext.get("model062_texture_presence_pass_domains") or [])
    model062_texture_audit_auto = set(ext.get("model062_texture_audit_domains") or [])
    target_content_separated = bool(ext.get("target_content_readiness_separated"))
    stage_material_auto = set(ext.get("stage072_material_pass_domains") or [])
    stage_auto = set(ext.get("stage072_pass_domains") or [])
    object_local_auto = set(ext.get("object_local_pass_domains") or [])
    multilayer_auto = set(ext.get("multilayer_texlink_pass_domains") or [])
    texture_codec_auto = set(ext.get("texture_codec_pass_domains") or [])
    inx_auto = set(ext.get("inx_writer_pass_domains") or [])
    smb_auto = set(ext.get("smb_writer_pass_domains") or [])
    mixed_physical_certified = bool(ext.get("mixed_physical_certified"))
    mixed_physical_pass_domains = set(ext.get("mixed_physical_pass_domains") or [])
    object_local_physical = {str(k): int(v or 0) for k, v in (ext.get("object_local_physical_by_domain") or {}).items()}
    object_local_census_available = "object_local_physical_by_domain" in ext
    multilayer_physical = {str(k): int(v or 0) for k, v in (ext.get("multilayer_physical_by_domain") or {}).items()}
    multilayer_census_available = "multilayer_physical_by_domain" in ext

    matrix: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, str]] = []
    target_content_blockers: list[dict[str, str]] = []
    for domain in CONTENT_DOMAINS:
        c = by_domain[domain]
        rigid_count = int(c.get("SMD_MODEL_062_RIGID_PHYSIQUE", 0))
        static_count = int(c.get("SMD_MODEL_062_STATIC", 0))
        mixed_domain_count = int(c.get("SMD_MODEL_062_MIXED_PHYSIQUE", 0))
        stage_count = int(c.get("STAGE_072_MAP_SEPARATE", 0))
        domain_cells: dict[str, Any] = {}

        if rigid_count:
            sibling_hypotheses = int(c.get("STANDALONE_SIBLING_SMB_HYPOTHESIS", 0))
            rigid_rep_ok = domain in canonical_rigid_auto
            rigid_census_ok = (not rigid_context_census_available) or domain in rigid_context_pass_domains
            rigid_parse_ok = (not rigid_physical_parse_available) or domain in rigid_physical_parse_auto
            if rigid_rep_ok and rigid_census_ok and rigid_parse_ok:
                state = "PHYSICAL_CORPUS_PARSE_BLENDER_CANDIDATE_AND_CONTEXT_CENSUS_PASS"
                next_gate = "representative runtime/game acceptance"
            elif rigid_physical_parse_available and not rigid_parse_ok:
                state = "PHYSICAL_MODEL062_CORPUS_PARSE_FAILED"
                next_gate = "corpus-wide physical Model0.62 parser/layout gate"
                blockers.append({"domain": domain, "capability": "MODEL062_RIGID", "blocker": next_gate})
            elif rigid_rep_ok and rigid_context_census_available and not rigid_census_ok:
                state = "REPRESENTATIVE_PASS_CORPUS_CONTEXT_UNRESOLVED"
                next_gate = "resolve every rigid skeleton/model-info context in physical corpus"
                blockers.append({"domain": domain, "capability": "MODEL062_RIGID", "blocker": next_gate})
            elif sibling_hypotheses and int(c.get("RIGGING_READY", 0)) == 0:
                state = "STANDALONE_STRUCTURAL_AUTOMATION_WIRED_EXECUTION_PENDING"
                next_gate = "run sibling-SMB structural/build/reimport automatic gate"
                blockers.append({"domain": domain, "capability": "MODEL062_RIGID", "blocker": next_gate})
            else:
                state = "AUTOMATION_WIRED_EXECUTION_PENDING"
                next_gate = "run representative real-Blender automatic rigid gate"
                blockers.append({"domain": domain, "capability": "MODEL062_RIGID", "blocker": next_gate})
            domain_cells["MODEL062_RIGID"] = _cell(rigid_count, state, next_gate=next_gate, evidence={"rigging_ready": int(c.get("RIGGING_READY", 0)), "standalone_sibling_smb_hypotheses": sibling_hypotheses, "physical_corpus_parse_pass": rigid_parse_ok})
        else:
            domain_cells["MODEL062_RIGID"] = _cell(0, "NOT_PRESENT_IN_CANONICAL_CORPUS")

        if static_count:
            representative_ok = domain in static_auto
            static_specific_ok = (domain in static_corpus_auto) if static_corpus_available else False
            static_general_ok = (domain in static_physical_parse_auto) if static_physical_parse_available else False
            corpus_ok = static_specific_ok and static_general_ok
            if representative_ok and corpus_ok:
                state = "CORPUS_PARSE_AND_AUTOMATED_BLENDER_TOPOLOGY_CANDIDATE_PASS"
                next_gate = "representative runtime/game acceptance"
            elif not corpus_ok:
                state = "PHYSICAL_CORPUS_PARSE_PENDING_OR_FAILED"
                next_gate = "corpus-wide physical Model0.62 static parser/layout gate"
                blockers.append({"domain": domain, "capability": "MODEL062_STATIC", "blocker": next_gate})
            else:
                state = "CANDIDATE_NEEDS_AUTOMATED_CORPUS_EXECUTION"
                next_gate = "automatic Blender edit/build/reimport representative gate"
                blockers.append({"domain": domain, "capability": "MODEL062_STATIC", "blocker": next_gate})
            domain_cells["MODEL062_STATIC"] = _cell(static_count, state, next_gate=next_gate, evidence={"representative_pass": representative_ok, "corpus_parse_pass": corpus_ok, "static_specific_parse_pass": static_specific_ok, "model062_physical_parse_pass": static_general_ok})
        else:
            domain_cells["MODEL062_STATIC"] = _cell(0, "NOT_PRESENT_IN_CANONICAL_CORPUS")

        if mixed_domain_count:
            domain_cells["MODEL062_MIXED"] = _cell(
                mixed_domain_count, MIXED_PHYSIQUE_RELEASE_1_SCOPE,
                next_gate="post-1.0 physical Mixed-Physique certification backlog",
                evidence={
                    "mixed_dispatch_wired": True,
                    "physical_gate_certified": mixed_physical_certified and domain in mixed_physical_pass_domains,
                    "release_1_blocking": MIXED_PHYSIQUE_RELEASE_1_BLOCKING,
                    "rigid_adapter": "pt_blender_to_smd_free_mesh_v3.py",
                    "static_adapter": "pt_blender_to_smd_static_v1.py",
                },
            )
        else:
            domain_cells["MODEL062_MIXED"] = _cell(
                0, MIXED_PHYSIQUE_RELEASE_1_SCOPE,
                next_gate="post-1.0 physical Mixed-Physique certification backlog",
                evidence={"release_1_blocking": MIXED_PHYSIQUE_RELEASE_1_BLOCKING},
            )

        inx_count = int(c.get("PHYSICAL_INX_FILE", 0))
        smb_count = int(c.get("PHYSICAL_SMB_FILE", 0))
        lod_count = int(c.get("HAS_LOD_GROUPS", 0))
        registry_rig_count = int(c.get("RIGGING_READY", 0))
        census_row = rigid_context_census.get(domain) or {}
        census_total = int(census_row.get("TOTAL") or 0)
        census_unresolved = int(census_row.get("UNRESOLVED") or 0)
        rig_count = (census_total - census_unresolved) if rigid_context_census_available else registry_rig_count
        bound_animation_asset_count = int(c.get("ANIMATION_BINDING_READY", 0))
        animated_smb_file_count = int(animated_smb_physical.get(domain, 0)) if smb_animation_census_available else 0
        anim_count = animated_smb_file_count if smb_animation_census_available else bound_animation_asset_count
        mat_count = int(c.get("HAS_MATERIALS", 0))
        model062_mat_count = int(c.get("MODEL062_HAS_MATERIALS", 0))
        tex_count = int(c.get("HAS_TEXTURE_REFS", 0))
        model062_tex_count = int(c.get("MODEL062_HAS_TEXTURE_REFS", 0))
        proprietary_tex_count = sum(int(c.get(family, 0)) for family in (
            "BMP_PROTECTED_PREFIX14_EXACT",
            "BMP_PROTECTED_PREFIX14_VARIANT",
            "TGA_NONSTANDARD_OR_PROTECTED",
        ))
        if inx_count:
            inx_state = "AUTOMATED_NOOP_EDIT_SEMANTIC_CORPUS_PASS" if domain in inx_auto else "CANDIDATE_PARSER_WRITER_PRESENT"
            inx_gate = "representative runtime/game semantic acceptance" if domain in inx_auto else "automatic INX no-op/edit/semantic corpus gate"
            if domain not in inx_auto:
                blockers.append({"domain": domain, "capability": "INX_MODERN_LEGACY_OUTLIERS", "blocker": inx_gate})
            domain_cells["INX_MODERN_LEGACY_OUTLIERS"] = _cell(inx_count, inx_state, next_gate=inx_gate)
        else:
            domain_cells["INX_MODERN_LEGACY_OUTLIERS"] = _cell(0, "NOT_PRESENT_IN_CANONICAL_CORPUS")
        if smb_count:
            smb_state = "AUTOMATED_NOOP_EDIT_CORPUS_PASS" if domain in smb_auto else "CANDIDATE_PARSER_WRITER_PRESENT"
            smb_gate = "representative runtime/game semantic acceptance" if domain in smb_auto else "automatic SMB no-op/edit corpus gate"
            if domain not in smb_auto:
                blockers.append({"domain": domain, "capability": "SMB_EXISTING", "blocker": smb_gate})
            domain_cells["SMB_EXISTING"] = _cell(smb_count, smb_state, next_gate=smb_gate)
        else:
            domain_cells["SMB_EXISTING"] = _cell(0, "NOT_PRESENT_IN_CANONICAL_CORPUS")
        if lod_count:
            inconsistent_count = int(lod_content_inconsistent.get(domain,0))
            full_container_count = int(lod_single_tier_full_container.get(domain,0))
            assets_without_authorable = int(lod_assets_without_authorable.get(domain,0))
            assets_with_outliers = int(lod_assets_with_outliers.get(domain,0))
            if domain in lod_corpus_pass_domains:
                lod_state=(
                    "CORPUS_AUTHORABLE_WITH_DIAGNOSED_FAIL_CLOSED_CONFIG_OUTLIERS"
                    if assets_with_outliers else "CORPUS_MODEL_KEY_AUTHORABLE"
                )
                lod_gate="representative runtime/game LOD acceptance"
            elif assets_without_authorable:
                lod_state="CORPUS_HAS_ASSETS_WITHOUT_AUTHORABLE_LOD_CONFIG"
                lod_gate="resolve assets whose every LOD config is non-authorable without fuzzy aliasing"
                blockers.append({"domain":domain,"capability":"LOD","blocker":lod_gate})
            else:
                lod_state="STRUCTURAL_CONTEXT_PRESENT_CORPUS_AUDIT_PENDING"
                lod_gate="corpus-wide LOD model-key coverage classification"
                blockers.append({"domain":domain,"capability":"LOD","blocker":lod_gate})
            domain_cells["LOD"] = _cell(lod_count,lod_state,next_gate=lod_gate,evidence={
                "diagnosed_non_authorable_configs_fail_closed":inconsistent_count,
                "assets_with_diagnosed_fail_closed_config_outliers":assets_with_outliers,
                "assets_without_authorable_lod_config":assets_without_authorable,
                "single_tier_full_container_configs":full_container_count,
                "fixed16_model_key_configs":int(lod_fixed16.get(domain,0)),
            })
        else:
            domain_cells["LOD"] = _cell(0,"NOT_PRESENT")
        if rig_count:
            rig_state = "AUTOMATED_CORPUS_CONTEXT_PASS" if rigid_context_census_available and census_unresolved == 0 else "BINDING_MAPPED"
            rig_gate = "representative runtime pose acceptance" if rig_state == "AUTOMATED_CORPUS_CONTEXT_PASS" else "corpus-wide physical skeleton context census + runtime pose acceptance"
            if rigid_context_census_available and census_unresolved:
                blockers.append({"domain": domain, "capability": "RIGGING", "blocker": rig_gate})
            domain_cells["RIGGING"] = _cell(rig_count, rig_state, next_gate=rig_gate, evidence={
                "registry_binding_ready_assets": registry_rig_count,
                "physical_context_census_total": census_total,
                "physical_context_census_unresolved": census_unresolved,
            })
        else:
            domain_cells["RIGGING"] = _cell(0, "NOT_PRESENT", evidence={"registry_binding_ready_assets": registry_rig_count})
        if anim_count:
            anim_state = "AUTOMATED_POSE_SPACE_PASS" if domain in animation_auto else "SOURCE_PIPELINE_PRESENT"
            anim_gate = "representative runtime/game animation acceptance" if domain in animation_auto else "automatic bound/standalone SMB pose-space + representative runtime gate"
            if domain not in animation_auto:
                blockers.append({"domain": domain, "capability": "EXISTING_ANIMATION", "blocker": anim_gate})
            domain_cells["EXISTING_ANIMATION"] = _cell(
                anim_count, anim_state, next_gate=anim_gate,
                evidence={
                    "physical_animated_smb_files": animated_smb_file_count,
                    "model_assets_with_animation_binding": bound_animation_asset_count,
                    "presence_basis": "PHYSICAL_SMB_CENSUS" if smb_animation_census_available else "REGISTRY_BINDING_FALLBACK",
                },
            )
        else:
            domain_cells["EXISTING_ANIMATION"] = _cell(0, "NOT_PRESENT", evidence={
                "physical_animated_smb_files": animated_smb_file_count,
                "model_assets_with_animation_binding": bound_animation_asset_count,
            })

        if mat_count:
            needs_model062_material = model062_mat_count > 0
            needs_stage_material = stage_count > 0
            model062_material_ok = (not needs_model062_material) or domain in material_auto
            stage_material_ok = (not needs_stage_material) or domain in stage_material_auto
            material_ok = model062_material_ok and stage_material_ok
            if material_ok:
                mat_state = "AUTOMATED_MATERIAL_EDIT_PASS_ALL_PRESENT_FAMILIES"
                mat_gate = "representative runtime/game material acceptance"
            else:
                mat_state = "MATERIAL_CANDIDATE_PIPELINE_PRESENT_EXECUTION_PENDING"
                missing=[]
                if needs_model062_material and not model062_material_ok: missing.append("MODEL062")
                if needs_stage_material and not stage_material_ok: missing.append("STAGE072")
                mat_gate = "automatic material edit gate for present families: " + ",".join(missing)
                blockers.append({"domain": domain, "capability": "MATERIALS", "blocker": mat_gate})
            domain_cells["MATERIALS"] = _cell(
                mat_count, mat_state, next_gate=mat_gate,
                evidence={
                    "model062_material_assets": model062_mat_count,
                    "stage072_assets": stage_count,
                    "model062_material_gate_pass": model062_material_ok,
                    "stage072_material_gate_pass": stage_material_ok,
                },
            )
        else:
            domain_cells["MATERIALS"] = _cell(0, "NOT_PRESENT", evidence={"model062_material_assets": model062_mat_count, "stage072_assets": stage_count})

        texture_present = tex_count or proprietary_tex_count or stage_count
        model062_refs_ready = (model062_tex_count == 0) or (domain in model062_texture_presence_auto)
        model062_audit_ok = (model062_tex_count == 0) or (domain in model062_texture_audit_auto)
        # FIX24_RELEASE_CAPABILITY_TARGET_SEPARATION: missing physical target
        # textures are a target-readiness issue after the reference audit itself
        # has completed. They do not impersonate a codec/writer capability bug.
        model062_refs_ok = model062_audit_ok if target_content_separated else model062_refs_ready
        if target_content_separated and model062_tex_count and model062_audit_ok and not model062_refs_ready:
            target_content_blockers.append({
                "domain":domain,"capability":"TEXTURES","blocker":"MODEL062_REFERENCE_PRESENCE",
            })
        stage_refs_ok = (stage_count == 0) or (domain in stage_auto)
        codec_ok = (proprietary_tex_count == 0) or (domain in texture_codec_auto)
        texture_pipeline_ok = bool(texture_present) and model062_refs_ok and stage_refs_ok and codec_ok
        if texture_pipeline_ok:
            texture_state = "AUTOMATED_CAPABILITY_PASS_TARGET_CONTENT_GAPS" if (target_content_separated and not model062_refs_ready) else "AUTOMATED_REFERENCE_PRESENCE_AND_PROPRIETARY_CODEC_PASS"
            texture_gate = "target content remediation" if (target_content_separated and not model062_refs_ready) else "representative runtime/game texture acceptance"
        elif texture_present:
            texture_state = "TEXTURE_PIPELINE_PRESENT_AUTOMATION_INCOMPLETE"
            missing=[]
            if not model062_refs_ok: missing.append("MODEL062_REFERENCE_AUDIT")
            if not stage_refs_ok: missing.append("STAGE072_REFERENCE_PRESENCE")
            if not codec_ok: missing.append("PROPRIETARY_CODEC")
            texture_gate = "complete automatic texture gates: " + ",".join(missing)
            blockers.append({"domain": domain, "capability": "TEXTURES", "blocker": texture_gate})
        else:
            texture_state = "NOT_PRESENT"
            texture_gate = None
        domain_cells["TEXTURES"] = _cell(
            int(tex_count + proprietary_tex_count), texture_state, next_gate=texture_gate,
            evidence={
                "texture_reference_assets": tex_count,
                "model062_texture_reference_assets": model062_tex_count,
                "proprietary_texture_assets": proprietary_tex_count,
                "model062_reference_audit_gate_pass": model062_audit_ok,
                "model062_reference_presence_gate_pass": model062_refs_ready,
                "target_content_readiness_separated": target_content_separated,
                "stage072_reference_presence_gate_pass": stage_refs_ok,
                "proprietary_codec_gate_pass": codec_ok,
            },
        )
        if proprietary_tex_count:
            if domain in texture_codec_auto:
                prop_state = "AUTOMATED_DOMAIN_CODEC_EDIT_REBUILD_PASS"
                prop_gate = "representative runtime/game texture acceptance"
            else:
                prop_state = "DOMAIN_CODEC_AUTOMATION_PENDING"
                prop_gate = "automatic BMP/TGA representative decode/edit/rebuild by physical family"
                blockers.append({"domain": domain, "capability": "BMP_TGA_PROPRIETARY", "blocker": prop_gate})
            domain_cells["BMP_TGA_PROPRIETARY"] = _cell(proprietary_tex_count, prop_state, next_gate=prop_gate)
        else:
            domain_cells["BMP_TGA_PROPRIETARY"] = _cell(0, "NOT_PRESENT_IN_CANONICAL_CORPUS")

        registry_ol_count = int(c.get("OBJECT_LOCAL_CANDIDATE", 0))
        ol_count = int(object_local_physical.get(domain, 0)) if object_local_census_available else registry_ol_count
        if ol_count:
            if domain in object_local_auto:
                ol_state = "AUTOMATED_ROT_POS_SCALE_BLENDER_PASS"
                ol_gate = "representative runtime/game object-local acceptance"
            elif object_local_census_available:
                ol_state = "PHYSICAL_CORPUS_PRESENT_AUTOMATION_PENDING"
                ol_gate = "ROT/POS/SCALE/TmFrame physical corpus execution"
            else:
                ol_state = "STRUCTURAL_CANDIDATE_PRESENT_PHYSICAL_SUBTYPE_GATE_PENDING"
                ol_gate = "physical ROT/POS/SCALE/TmFrame corpus audit + automated Blender witness"
            if domain not in object_local_auto:
                blockers.append({"domain": domain, "capability": "OBJECT_LOCAL_ANIMATION", "blocker": ol_gate})
            domain_cells["OBJECT_LOCAL_ANIMATION"] = _cell(
                ol_count, ol_state, next_gate=ol_gate,
                evidence={"registry_structural_candidates": registry_ol_count, "physical_census_available": object_local_census_available},
            )
        else:
            domain_cells["OBJECT_LOCAL_ANIMATION"] = _cell(
                0,
                "NOT_PRESENT_IN_PHYSICAL_CORPUS" if object_local_census_available else "NOT_PRESENT_IN_REGISTRY_STRUCTURAL_CENSUS",
                evidence={"registry_structural_candidates": registry_ol_count, "physical_census_available": object_local_census_available},
            )

        registry_multilayer_count = int(c.get("MULTILAYER_TEXLINK_CANDIDATE", 0))
        multilayer_count = int(multilayer_physical.get(domain, 0)) if multilayer_census_available else registry_multilayer_count
        if multilayer_count:
            ml_state = "AUTOMATED_TEXLINK_EDIT_PASS" if domain in multilayer_auto else "PARSER_ROUNDTRIP_PIPELINE_PRESENT"
            ml_gate = "representative runtime/game multilayer acceptance" if domain in multilayer_auto else "representative writer/reimport gate"
            if domain not in multilayer_auto:
                blockers.append({"domain": domain, "capability": "MULTILAYER_TEXLINK", "blocker": ml_gate})
            domain_cells["MULTILAYER_TEXLINK"] = _cell(
                multilayer_count, ml_state, next_gate=ml_gate,
                evidence={
                    "registry_structural_candidates": registry_multilayer_count,
                    "physical_census_available": multilayer_census_available,
                },
            )
        else:
            domain_cells["MULTILAYER_TEXLINK"] = _cell(
                0,
                "NOT_PRESENT_IN_PHYSICAL_CORPUS" if multilayer_census_available else "NOT_PRESENT_IN_CANONICAL_CORPUS",
                evidence={
                    "registry_structural_candidates": registry_multilayer_count,
                    "physical_census_available": multilayer_census_available,
                },
            )

        if stage_count:
            stage_state = "AUTOMATED_GEOMETRY_UV_MATERIAL_PASS" if domain in stage_auto else "CANDIDATE_STRICT_EDIT_SET"
            stage_gate = "representative runtime/game map acceptance" if domain in stage_auto else "automated edited-map corpus + runtime acceptance"
            if domain not in stage_auto:
                blockers.append({"domain": domain, "capability": "STAGE072", "blocker": stage_gate})
            domain_cells["STAGE072"] = _cell(stage_count, stage_state, next_gate=stage_gate)
        else:
            domain_cells["STAGE072"] = _cell(0, "NOT_PRESENT")
        matrix[domain] = domain_cells

    mixed_count = int(counts["family_totals"].get("SMD_MODEL_062_MIXED_PHYSIQUE", 0))
    mixed_global_ready = bool(mixed_count > 0 and mixed_physical_certified)
    global_gates = [
        {
            "capability": "MODEL062_MIXED",
            "state": MIXED_PHYSIQUE_RELEASE_1_SCOPE,
            "count": mixed_count,
            "release_1_blocking": MIXED_PHYSIQUE_RELEASE_1_BLOCKING,
            "physical_mixed_certified": mixed_global_ready,
            "next_gate": "post-1.0 physical Mixed-Physique certification backlog",
        },
        {
            "capability": "RUNTIME_GAME_ACCEPTANCE",
            "state": "OUT_OF_SCOPE_PT_ASSET_TOOL_1_0",
            "release_1_blocking": False,
            "next_gate": None,
        },
        {
            "capability": "PUBLISH_RESTORE",
            "state": "POLICY_BLOCKED_UNTIL_WRITER_PROMOTION",
            "next_gate": "enable only after per-family automatic/runtime gates and explicit writer promotion",
        },
    ]

    # Mixed-Physique and gameplay/runtime acceptance are explicitly outside the
    # PT Asset Tool 1.0 support claim. Publish/restore remains safety-locked and
    # externally reported, but does not contaminate automatic tool capability.
    blockers.append({
        "domain": "GLOBAL",
        "capability": "PUBLISH_RESTORE",
        "blocker": global_gates[2]["next_gate"],
    })

    return {
        "format": FORMAT,
        "status": "PARTIAL" if blockers else "PASS",
        "release_target": "1.0",
        "development_state": "IN_PROGRESS",
        "content_domains": list(CONTENT_DOMAINS),
        "required_capabilities": list(CAPABILITIES),
        "inventory": counts,
        "matrix": matrix,
        "global_gates": global_gates,
        "blocking_gate_count": len(blockers),
        "blocking_gates": blockers,
        "target_content_blocking_gate_count": len(target_content_blockers),
        "target_content_blocking_gates": target_content_blockers,
        "policy": {
            "format_only_readiness_is_insufficient": True,
            "content_domain_and_capability_must_both_be_covered": True,
            "automatic_tests_preferred": True,
            "manual_review_reserved_for_visual_runtime_gates": True,
            "production_authorized": False,
            "client_write_authorized": False,
            "tool_capability_vs_target_content_separated": target_content_separated,
            "runtime_game_acceptance_for_tool_1_0": "OUT_OF_SCOPE",
        },
        "client_modified": False,
    }


def _valid_lod_cfg(asset, cfg: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    valid_lods: list[str] = []
    for lod in ("high", "default", "low"):
        groups = (cfg.get("lod_groups") or {}).get(lod) or []
        if not groups:
            continue
        cov = effective_lod_node_coverage(asset, cfg, lod)
        if cov.get("status") == "PASS":
            valid_lods.append(lod)
            score += len(groups)
    return score, valid_lods


def _choose_rigid_representatives(registry, domain: str, *, limit: int = 4) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for asset in registry.assets:
        if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE" or content_domain(asset) != domain:
            continue
        if not asset.rigid_binding_ready:
            continue
        cls = classify_asset_model_info_context(asset)
        for cfg in lod_model_info_configs(asset):
            score, lods = _valid_lod_cfg(asset, cfg)
            if not lods:
                continue
            skeleton = str(cfg.get("motion_smb") or asset.binding_skeleton_smb or "").replace("\\", "/")
            if not skeleton:
                continue
            context_state = cls.get("state") if cfg.get("motion_smb") else "LOD_CONFIG_WITH_RESOLVED_SKELETON"
            candidates.append({
                "asset_id": asset.asset_id,
                "asset": asset.primary_path,
                "domain": domain,
                "model_info_inx": str(cfg.get("inx") or "").replace("\\", "/"),
                "skeleton_smb": skeleton,
                "explicit_skeleton_lod": not bool(cfg.get("motion_smb")),
                "model_info_context_state": context_state,
                "requires_explicit_model_info": bool(cls.get("requires_explicit_model_info")) if cfg.get("motion_smb") else True,
                "valid_lods": lods,
                "lod_node_count": score,
                "config_count": int(cls.get("config_count") or len(lod_model_info_configs(asset))),
                "ambiguity_dimensions": list(cls.get("ambiguity_dimensions") or []),
            })
    # Cover context states first, then prefer more LOD/node coverage and stable path ordering.
    state_rank = {"AMBIGUOUS_MODEL_INFO_CONFIG": 0, "LOD_CONFIG_WITH_RESOLVED_SKELETON": 1, "SEMANTICALLY_EQUIVALENT": 2, "SINGLE_CONFIG": 3}
    candidates.sort(key=lambda r: (state_rank.get(str(r["model_info_context_state"]), 9), -len(r["valid_lods"]), -r["lod_node_count"], r["asset"].casefold(), r["model_info_inx"].casefold()))
    out: list[dict[str, Any]] = []
    seen_assets: set[str] = set()
    # First pass deliberately covers each context state once. This prevents the
    # highest-ranked ambiguous class from consuming the whole representative
    # budget before equivalent/single-config contexts are exercised.
    for wanted in ("AMBIGUOUS_MODEL_INFO_CONFIG", "LOD_CONFIG_WITH_RESOLVED_SKELETON", "SEMANTICALLY_EQUIVALENT", "SINGLE_CONFIG"):
        for row in candidates:
            if str(row["model_info_context_state"]) != wanted or row["asset_id"] in seen_assets:
                continue
            out.append(row); seen_assets.add(row["asset_id"]); break
        if len(out) >= int(limit):
            return out
    # Second pass fills the remaining budget by coverage score/order.
    for row in candidates:
        if row["asset_id"] in seen_assets:
            continue
        out.append(row); seen_assets.add(row["asset_id"])
        if len(out) >= int(limit):
            break
    return out


def _choose_static_representatives(registry, domain: str, *, limit: int = 4) -> list[dict[str, Any]]:
    rows = []
    for asset in registry.assets:
        if asset.family != "SMD_MODEL_062_STATIC" or content_domain(asset) != domain:
            continue
        rows.append({
            "asset_id": asset.asset_id,
            "asset": asset.primary_path,
            "domain": domain,
            "object_count": int(asset.object_count or 0),
            "material_count": int(asset.material_count or 0),
            "total_vertices": int(asset.total_vertices or 0),
            "total_faces": int(asset.total_faces or 0),
            "size": int(asset.size or 0),
        })
    if not rows or int(limit) <= 0:
        return []
    # Cover both the smallest/simple and largest/complex assets first.  Static
    # authoring bugs tend to cluster at both ends (minimal one-object drops and
    # large multi-object/material props), so a complexity-only sort is weak.
    complexity=lambda r:(r["object_count"],r["material_count"],r["total_faces"],r["size"],r["asset"].casefold())
    ordered=sorted(rows,key=complexity)
    picks=[]; seen=set()
    for row in (ordered[0], ordered[-1]):
        if row["asset_id"] not in seen:
            picks.append(row); seen.add(row["asset_id"])
        if len(picks)>=int(limit): return picks
    # Fill with roughly even quantiles rather than adjacent near-duplicates.
    if len(ordered)>2:
        slots=max(0,int(limit)-len(picks))
        for i in range(1,slots+1):
            idx=round(i*(len(ordered)-1)/(slots+1))
            row=ordered[idx]
            if row["asset_id"] in seen: continue
            picks.append(row); seen.add(row["asset_id"])
            if len(picks)>=int(limit): break
    for row in reversed(ordered):
        if len(picks)>=int(limit): break
        if row["asset_id"] not in seen:
            picks.append(row); seen.add(row["asset_id"])
    return picks


def _choose_stage072_representatives(registry, *, limit: int = 3) -> list[dict[str, Any]]:
    rows=[{
        "asset_id":a.asset_id,"asset":a.primary_path,"domain":"MAP","size":int(a.size or 0),
    } for a in registry.assets if a.family=="STAGE_072_MAP_SEPARATE" or a.kind=="SMD_STAGE_072"]
    if not rows or int(limit)<=0: return []
    rows.sort(key=lambda r:(r["size"],r["asset"].casefold()))
    idxs=[0,len(rows)//2,len(rows)-1]
    out=[]; seen=set()
    for idx in idxs:
        row=rows[idx]
        if row["asset_id"] not in seen:
            out.append(row); seen.add(row["asset_id"])
        if len(out)>=int(limit): return out
    for row in rows:
        if row["asset_id"] not in seen:
            out.append(row); seen.add(row["asset_id"])
        if len(out)>=int(limit): break
    return out



def _choose_animation_representatives(registry, domain: str, *, limit: int = 2) -> list[dict[str, Any]]:
    rows=[]
    for row in _choose_rigid_representatives(registry, domain, limit=max(8, int(limit)*4)):
        try:
            asset=registry.by_id[row["asset_id"]]
        except Exception:
            asset=next((a for a in registry.assets if a.asset_id==row["asset_id"]), None)
        if asset is None or not bool(getattr(asset, "animation_binding_ready", False)):
            continue
        rows.append(dict(row))
        if len(rows)>=int(limit): break
    return rows

def build_release_1_automated_gate_plan(registry, *, rigid_per_domain: int = 4, static_per_domain: int = 4) -> dict[str, Any]:
    # Cover every content-domain/family combination that actually exists in the
    # canonical corpus.  Release 1.0 is a cross-product contract, not a
    # character-only format claim.  Empty domains simply yield no reps.
    rigid = {d: _choose_rigid_representatives(registry, d, limit=rigid_per_domain) for d in CONTENT_DOMAINS}
    static = {d: _choose_static_representatives(registry, d, limit=static_per_domain) for d in CONTENT_DOMAINS}
    animation = {d: _choose_animation_representatives(registry, d, limit=2) for d in ("PLAYER", "NPC", "MONSTER")}
    return {
        "format": PLAN_FORMAT,
        "status": "PASS",
        "rigid_representatives": rigid,
        "static_representatives": static,
        "animation_representatives": animation,
        "stage072_representatives": _choose_stage072_representatives(registry, limit=3),
        "external_requirements": [
            "real configured client root for physical source files",
            "Blender runtime for automated import/edit/reimport",
        ],
        "automatic_only": True,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def write_json(path, payload: dict[str, Any]):
    from pathlib import Path
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
