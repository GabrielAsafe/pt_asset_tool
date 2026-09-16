from __future__ import annotations

import json
import pathlib
from typing import Any, Iterable

from .animation_corpus import audit_animation_corpus
from .authoring import audit_model062_authoring
from .object_local_writer import audit_object_local_writer_corpus
from .binding_coverage import audit_binding_coverage
from .physique_audit import audit_physique_modes
from .profile_candidates import discover_profile_candidates
from .rigid_model_info import audit_rigid_model_info_contexts
from .release_1_coverage import build_release_1_coverage, content_domain
from .standalone_rigid_devtest import sibling_smb_candidates
from .workflow_dispatch import build_plan
from .writer_corpus_audit import (
    audit_inx_writer_corpus, audit_smb_writer_corpus,
    audit_inx_writer_edit_corpus, audit_smb_writer_edit_corpus,
    audit_motion_writer_semantic_edit_corpus,
)

FORMAT = "PT_ASSET_DEVELOPMENT_READINESS_V1"


def _stage(
    maturity: str,
    summary: str,
    *,
    evidence: dict[str, Any] | None = None,
    blockers: Iterable[str] = (),
    production_authorized: bool | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "maturity": str(maturity),
        "summary": str(summary),
        "evidence": dict(evidence or {}),
        "blockers": [str(x) for x in blockers],
    }
    if production_authorized is not None:
        row["production_authorized"] = bool(production_authorized)
    return row


def audit_development_readiness(
    project_root,
    client_root,
    registry,
    resolver,
    profile_registry,
    *,
    deep: bool = False,
    prefixes: Iterable[str] = ("char/npc", "char/monster"),
    animation_pair_limit: int = 0,
    sample_limit: int = 25,
) -> dict[str, Any]:
    """Build a machine-readable view of current product/reverse-engineering maturity.

    This is deliberately a *development* report, not an authorization gate.
    PARTIAL/CANDIDATE/DEFERRED are valid states.  Deep mode re-runs read-only
    corpus evidence for INX, SMB and animation; it still never promotes writers.
    """
    assets = list(registry.assets)
    family_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    for asset in assets:
        family_counts[asset.family] = family_counts.get(asset.family, 0) + 1
        kind_counts[asset.kind] = kind_counts.get(asset.kind, 0) + 1

    physique = audit_physique_modes(registry.records)
    mixed_count = int((physique.get("raw_mode_counts") or {}).get("MIXED", 0))

    npc_binding = audit_binding_coverage(registry, category="NPC", sample_limit=sample_limit)
    monster_binding = audit_binding_coverage(registry, category="MONSTER", sample_limit=sample_limit)

    profiles = profile_registry.list()
    runtime_proven_profiles = [
        p.profile_id for p in profiles
        if bool((p.geometry_status or {}).get("all_lods_runtime_proven"))
    ]

    profile_discovery = discover_profile_candidates(
        registry, limit=0, profile_registry=profile_registry
    )
    rigid_model_info = audit_rigid_model_info_contexts(registry, sample_limit=0)
    release1_coverage = build_release_1_coverage(registry, external_evidence={})
    unbound_rigid_by_domain = {}
    standalone_candidate_by_domain = {}
    for domain in ("EFFECT", "MAP"):
        rows = [a for a in assets if a.family == "SMD_MODEL_062_RIGID_PHYSIQUE" and content_domain(a) == domain and not a.rigid_binding_ready]
        unbound_rigid_by_domain[domain] = len(rows)
        standalone_candidate_by_domain[domain] = sum(1 for a in rows if sibling_smb_candidates(registry, a).get("candidate_available"))

    external_rigid_witnesses = []
    witness_path = pathlib.Path(project_root).resolve() / "pt_build" / "state" / "development_evidence" / "rigid_saved_blender_external_witnesses_v1.json"
    if witness_path.is_file():
        try:
            external_rigid_witnesses = list((json.loads(witness_path.read_text(encoding="utf-8")) or {}).get("witnesses") or [])
        except Exception:
            external_rigid_witnesses = []
    real_blender_reported = [
        row for row in external_rigid_witnesses
        if str(row.get("status") or "").startswith("PASS_REPORTED")
        and bool(row.get("edit_observed"))
        and not (row.get("verification_errors") or [])
        and not (row.get("non_target_changed") or [])
        and not (row.get("unknown_physique_bones") or [])
    ]

    plans = [build_plan(asset) for asset in assets]
    authorized_builds = [p for p in plans if p.get("authorized")]

    animation_ready_assets = sum(1 for asset in assets if asset.animation_binding_ready)
    physical_animation_ready_assets = sum(
        1 for asset in assets if asset.animation_binding_ready
        and registry.physical_dependency_status(asset).get("animation_binding_ready_physical")
    )

    stages: dict[str, dict[str, Any]] = {
        "application_core": _stage(
            "OPERATIONAL",
            "Standalone CLI/GUI, catalog, status/smoke/doctor, jobs, reports and read-only client policy are wired.",
            evidence={"asset_count": len(assets), "family_count": len(family_counts)},
            production_authorized=True,
        ),
        "catalog_entities": _stage(
            "OPERATIONAL",
            "Physical catalog plus folder/role taxonomy and NPC/Monster entity aggregation are available.",
            evidence={
                "npc_rigid_assets": npc_binding.get("rigid_asset_count", 0),
                "npc_binding_ready": npc_binding.get("rigid_binding_ready_count", 0),
                "monster_rigid_assets": monster_binding.get("rigid_asset_count", 0),
                "monster_binding_ready": monster_binding.get("rigid_binding_ready_count", 0),
            },
            production_authorized=True,
        ),
        "model062_static": _stage(
            "PARTIAL",
            "Static Model0.62 inspection/import and a provenance-gated saved-Blender candidate build path exist; production promotion still requires real Blender/runtime corpus evidence.",
            evidence={
                "asset_count": family_counts.get("SMD_MODEL_062_STATIC", 0),
                "saved_blender_candidate_wired": True,
                "object_local_rot_pos_scale_candidate_writer_wired": True,
                "static_semantic_automated_devtest_wired": True,
            },
            blockers=[
                "real Blender automated corpus execution of static candidate writer across weapon/item/effect/map representatives",
                "object-local ROT/POS/SCALE candidate corpus/runtime evidence",
                "object-local segmented TmFrame physical corpus execution",
                "family-wide runtime certification for arbitrary artist edits",
                "production promotion policy",
            ],
            production_authorized=False,
        ),
        "model062_rigid": _stage(
            "PARTIAL",
            "Rigid Physique binding/import/animation context is broadly mapped; a selected-context/provenance/skeleton-gated free-mesh candidate path is wired, while only rare scopes are production-certified.",
            evidence={
                "asset_count": family_counts.get("SMD_MODEL_062_RIGID_PHYSIQUE", 0),
                "animation_binding_ready_assets": animation_ready_assets,
                "physical_animation_ready_assets": physical_animation_ready_assets,
                "generic_build_authorized_assets": len(authorized_builds),
                "saved_blender_candidate_wired": True,
                "selected_context_manifest_wired": True,
                "selected_lod_candidate_scope_enforced": True,
                "candidate_require_edit_gate_available": True,
                "candidate_provenance_evidence_enriched": True,
                "rigid_candidate_review_registry_wired": True,
                "candidate_output_reimport_review_wired": True,
                "rigid_authoring_certification_plan_wired": True,
                "rigid_profile_stress_candidate_wired": True,
                "rigid_profile_automated_devtest_wired": True,
                "real_blender_controlled_edit_reported_count": len(real_blender_reported),
                "real_blender_human_reviewed_reported_count": sum(1 for row in real_blender_reported if bool(row.get("context_pass"))),
                "real_blender_controlled_edit_reported_contexts": [
                    {
                        "asset": row.get("asset"), "profile_id": row.get("profile_id"),
                        "lod": row.get("lod"), "object": row.get("object"),
                        "artifact_sha256": row.get("artifact_sha256"),
                        "independently_reverified_in_snapshot": False,
                    } for row in real_blender_reported
                ],
                "multi_inx_context_audit_wired": True,
                "single_config_assets": rigid_model_info.get("single_config_assets", 0),
                "multi_config_assets": rigid_model_info.get("multi_config_assets", 0),
                "equivalent_multi_config_assets": rigid_model_info.get("equivalent_multi_config_assets", 0),
                "ambiguous_multi_config_assets": rigid_model_info.get("ambiguous_multi_config_assets", 0),
                "no_usable_model_info_assets": rigid_model_info.get("no_usable_model_info_assets", 0),
                "ambiguity_dimension_counts": rigid_model_info.get("ambiguity_dimension_counts", {}),
                "release_1_cross_domain_coverage_wired": True,
                "unbound_rigid_by_domain": unbound_rigid_by_domain,
                "standalone_sibling_smb_candidate_by_domain": standalone_candidate_by_domain,
                "standalone_rigid_structural_gate_runner_wired": True,
            },
            blockers=["automatic physical standalone-sibling SMB structural/build/reimport gate for rigid EFFECT/MAP", "automated NPC/monster representative Blender coverage", "representative runtime/game acceptance beyond automated Blender structural gates", "production promotion policy"],
            production_authorized=False,
        ),
        "stage072": _stage(
            "PARTIAL",
            "Stage0.72 parse/preview/UV and geometry witnesses/Texture Paint are implemented; a strict saved-Blender candidate accepts UV-only or multi-vertex XYZ grid edits and an automated edited-map/reimport runner is wired, while topology/material/light changes remain fail-closed and production is not promoted.",
            evidence={
                "asset_count": kind_counts.get("SMD_STAGE_072", 0),
                "saved_blender_candidate_wired": True,
                "candidate_edit_modes": ["UV_ONLY", "GEOMETRY_GRID_MULTI"],
                "automated_semantic_devtest_wired": True,
            },
            blockers=["real Blender execution of automated Stage0.72 edited-map/reimport gate", "full edited-map runtime acceptance gate", "production promotion policy"],
            production_authorized=False,
        ),
        "animation": _stage(
            "PARTIAL",
            "INX/SMB motion context, source-side regression and an automated Blender pose-space matrix gate are wired; game/runtime acceptance remains external.",
            evidence={
                "registry_animation_ready_assets": animation_ready_assets,
                "physical_animation_ready_assets": physical_animation_ready_assets,
                "automated_blender_pose_space_gate_wired": True,
            },
            blockers=["execute automated Blender pose-space gate across representative player/NPC/monster rigs", "runtime/game acceptance for edited animation data"],
            production_authorized=False,
        ),
        "inx_writer": _stage(
            "CANDIDATE",
            "MotionInfo edits are preservation-aware and pt_build-only; production client writes remain unauthorized.",
            evidence={"deep_corpus_rerun": False},
            blockers=["runtime semantic acceptance of edited MotionInfo", "transactional publish/restore integration", "production policy/promotion gate"],
            production_authorized=False,
        ),
        "smb_writer": _stage(
            "CANDIDATE",
            "Existing SMB key edits are pt_build-only with no insert/delete; production client writes remain unauthorized.",
            evidence={"deep_corpus_rerun": False},
            blockers=["runtime semantic acceptance of edited SMB motion", "key insertion/deletion/segment editing if required", "transactional publish/restore integration", "production policy/promotion gate"],
            production_authorized=False,
        ),
        "profiles_lod": _stage(
            "PARTIAL",
            "Canonical profiles can now resolve an exact registry-proven INX+skeleton+LOD Blender import context; profile-driven generic build/promotion remains unauthorized.",
            evidence={
                "profile_count": len(profiles),
                "all_lods_runtime_proven_profiles": runtime_proven_profiles,
                "discovered_profile_candidates": profile_discovery.get("candidate_count", 0),
                "candidate_state_counts": profile_discovery.get("state_counts", {}),
                "model_info_context_state_counts": profile_discovery.get("model_info_context_state_counts", {}),
                "profile_driven_import_context_wired": True,
                "profile_selection_persisted_in_selected_context": True,
            },
            blockers=["profile-driven generic candidate build/promotion beyond import", "runtime gates for profiles still marked unproven"],
            production_authorized=False,
        ),
        "mixed_physique": _stage(
            "IMPLEMENTED_SYNTHETIC_AWAITING_REAL_REPRESENTATIVE" if mixed_count == 0 else "PHYSICAL_GATE_REQUIRED",
            "Mixed-Physique per-object rigid/static dispatch and combined verification are implemented fail-closed; the canonical corpus still has no real representative for physical certification." if mixed_count == 0 else "Mixed-Physique representatives exist; run the physical import/build/reimport gate before promotion.",
            evidence={
                "model062_total": physique.get("smd_model_062_total"),
                "mixed_count": mixed_count,
                "compatibility_gate": physique.get("compatibility_gate"),
                "mixed_dispatch_wired": True,
                "synthetic_mixed_verifier_covered": True,
                "rigid_adapter": "pt_blender_to_smd_free_mesh_v3.py",
                "static_adapter": "pt_blender_to_smd_static_v1.py",
            },
            blockers=["authoritative real Mixed-Physique representative required for physical Release 1.0 certification"] if mixed_count == 0 else ["physical mixed import/build/reimport gate"],
            production_authorized=False,
        ),
        "generic_publish_restore": _stage(
            "BLOCKED_BY_POLICY_AND_WRITER_PROMOTION",
            "Deployment plan/prepare/verify/simulate now prove pt_build-contained provenance, verified backup material, drift detection, atomic replacement, post-write identity and rollback in a sandbox; real client apply/restore remain disabled until writer promotion and real-client policy are proven.",
            evidence={
                "client_source_write_default": False,
                "deployment_plan_only": False,
                "transaction_prepare_available": True,
                "transaction_verify_available": True,
                "transaction_simulation_available": True,
                "atomic_replace_sandbox_contract": True,
                "postwrite_verification_sandbox_contract": True,
                "failure_injection_rollback_sandbox_contract": True,
                "client_state_classifier_available": True,
                "restore_plan_available": True,
                "unknown_client_drift_fail_closed": True,
                "verified_backup_staging_contract": True,
                "build_provenance_sidecar_required": True,
                "build_provenance_snapshotted_in_transaction": True,
                "selected_context_transaction_wired": True,
                "apply_mode_available": False,
            },
            blockers=[
                "per-family production writer authorization",
                "real-client-filesystem atomic replace + postwrite verification policy",
                "explicit app-level apply/restore promotion gate after production-writer coverage",
                "real-client restore execution + post-restore verification remains unpromoted",
            ],
            production_authorized=False,
        ),
    }

    deep_results: dict[str, Any] = {}
    if deep:
        prefix_list = [str(x) for x in prefixes]
        inx = audit_inx_writer_corpus(client_root, prefixes=prefix_list, sample_limit=sample_limit)
        smb = audit_smb_writer_corpus(project_root, client_root, prefixes=prefix_list, sample_limit=sample_limit)
        inx_edit = audit_inx_writer_edit_corpus(client_root, prefixes=prefix_list, sample_limit=sample_limit)
        smb_edit = audit_smb_writer_edit_corpus(project_root, client_root, prefixes=prefix_list, sample_limit=sample_limit)
        motion_semantic_edit = audit_motion_writer_semantic_edit_corpus(
            project_root, registry, resolver,
            pair_limit=int(animation_pair_limit or 0), sample_limit=sample_limit,
        )
        authoring = audit_model062_authoring(registry, resolver, sample_limit=sample_limit)
        object_local_writer = audit_object_local_writer_corpus(project_root, registry, resolver, sample_limit=sample_limit)
        anim = audit_animation_corpus(
            project_root,
            registry,
            resolver,
            mode="core",
            pair_limit=int(animation_pair_limit or 0),
            sample_limit=sample_limit,
        )
        deep_results = {
            "inx_writer_corpus": inx, "smb_writer_corpus": smb,
            "inx_writer_edit_corpus": inx_edit, "smb_writer_edit_corpus": smb_edit,
            "motion_writer_semantic_edit_corpus": motion_semantic_edit,
            "model062_authoring": authoring,
            "object_local_writer_corpus": object_local_writer,
            "animation_corpus": anim,
        }
        fam_maturity = authoring.get("family_maturity_counts") or {}
        stages["model062_static"]["evidence"]["deep_authoring_maturity_counts"] = fam_maturity.get("SMD_MODEL_062_STATIC", {})
        stages["model062_rigid"]["evidence"]["deep_authoring_maturity_counts"] = fam_maturity.get("SMD_MODEL_062_RIGID_PHYSIQUE", {})
        stages["model062_static"]["evidence"]["candidate_asset_count"] = int((authoring.get("family_candidate_asset_counts") or {}).get("SMD_MODEL_062_STATIC", 0))
        stages["model062_static"]["evidence"]["candidate_object_count"] = int((authoring.get("family_candidate_object_counts") or {}).get("SMD_MODEL_062_STATIC", 0))
        stages["model062_static"]["evidence"].update({
            "object_local_writer_corpus_status": object_local_writer.get("status"),
            "object_local_writer_editable_files": object_local_writer.get("editable_file_count"),
            "object_local_writer_pass_count": object_local_writer.get("pass_count"),
            "object_local_rotation_only_files": object_local_writer.get("rotation_only_file_count"),
        })
        if object_local_writer.get("status") == "PASS" and int(object_local_writer.get("editable_file_count") or 0) > 0:
            stages["model062_static"]["evidence"]["object_local_writer_maturity"] = "CANDIDATE_EDIT_CORPUS_PROVEN"
            stages["model062_static"]["blockers"] = [
                x for x in stages["model062_static"]["blockers"]
                if x != "object-local POS/SCALE candidate corpus/runtime evidence"
            ]
        elif object_local_writer.get("status") == "EMPTY":
            stages["model062_static"]["evidence"]["object_local_writer_maturity"] = "CANDIDATE_IMPLEMENTED_NO_PHYSICAL_SAMPLE"
        stages["model062_rigid"]["evidence"]["candidate_asset_count"] = int((authoring.get("family_candidate_asset_counts") or {}).get("SMD_MODEL_062_RIGID_PHYSIQUE", 0))
        stages["model062_rigid"]["evidence"]["candidate_object_count"] = int((authoring.get("family_candidate_object_counts") or {}).get("SMD_MODEL_062_RIGID_PHYSIQUE", 0))
        if inx.get("status") == "PASS":
            stages["inx_writer"]["maturity"] = (
                "CANDIDATE_EDIT_CORPUS_PROVEN" if inx_edit.get("status") == "PASS" else "CANDIDATE_CORPUS_PROVEN"
            )
            stages["inx_writer"]["evidence"].update({
                "deep_corpus_rerun": True,
                "file_count": inx.get("file_count"),
                "pass_count": inx.get("pass_count"),
                "layout_counts": inx.get("layout_counts"),
                "semantic_variant_file_count": inx.get("semantic_variant_file_count"),
                "edit_corpus_status": inx_edit.get("status"),
                "edited_file_count": inx_edit.get("edited_file_count"),
                "no_editable_record_count": inx_edit.get("no_editable_record_count"),
                "source_semantic_edit_status": motion_semantic_edit.get("status"),
                "source_semantic_edit_pass": motion_semantic_edit.get("inx_semantic_edit_pass"),
            })
            if (
                inx_edit.get("status") == "PASS"
                and motion_semantic_edit.get("status") == "PASS"
                and int(motion_semantic_edit.get("inx_semantic_edit_pass") or 0) > 0
            ):
                stages["inx_writer"]["maturity"] = "CANDIDATE_SOURCE_SEMANTIC_EDIT_PROVEN"
        else:
            stages["inx_writer"]["evidence"].update({"deep_corpus_rerun": True, "corpus_status": inx.get("status")})
            stages["inx_writer"]["blockers"].insert(0, "candidate corpus preservation regression")
        if smb.get("status") == "PASS":
            stages["smb_writer"]["maturity"] = (
                "CANDIDATE_EDIT_CORPUS_PROVEN" if smb_edit.get("status") == "PASS" else "CANDIDATE_CORPUS_PROVEN"
            )
            stages["smb_writer"]["evidence"].update({
                "deep_corpus_rerun": True,
                "file_count": smb.get("file_count"),
                "pass_count": smb.get("pass_count"),
                "external_parent_file_count": smb.get("external_parent_file_count"),
                "edit_corpus_status": smb_edit.get("status"),
                "edited_file_count": smb_edit.get("edited_file_count"),
                "no_editable_key_file_count": smb_edit.get("no_editable_key_file_count"),
                "source_semantic_edit_status": motion_semantic_edit.get("status"),
                "source_semantic_edit_pass": motion_semantic_edit.get("smb_semantic_edit_pass"),
            })
            if (
                smb_edit.get("status") == "PASS"
                and motion_semantic_edit.get("status") == "PASS"
                and int(motion_semantic_edit.get("smb_semantic_edit_pass") or 0) > 0
            ):
                stages["smb_writer"]["maturity"] = "CANDIDATE_SOURCE_SEMANTIC_EDIT_PROVEN"
        else:
            stages["smb_writer"]["evidence"].update({"deep_corpus_rerun": True, "corpus_status": smb.get("status")})
            stages["smb_writer"]["blockers"].insert(0, "candidate corpus preservation regression")
        stages["animation"]["evidence"].update({
            "deep_corpus_rerun": True,
            "source_corpus_status": anim.get("status"),
            "unique_motion_contexts": anim.get("unique_motion_contexts"),
            "audited_contexts": anim.get("audited_contexts"),
            "failed_contexts": anim.get("failed_contexts"),
            "total_audited_motions": anim.get("total_audited_motions"),
            "candidate_writer_semantic_edit_status": motion_semantic_edit.get("status"),
            "candidate_inx_semantic_edit_pass": motion_semantic_edit.get("inx_semantic_edit_pass"),
            "candidate_smb_semantic_edit_pass": motion_semantic_edit.get("smb_semantic_edit_pass"),
        })

    remaining = []
    for key, row in stages.items():
        for blocker in row.get("blockers") or []:
            remaining.append({"area": key, "blocker": blocker})

    priorities = [
        {
            "priority": "P0",
            "area": "animation",
            "goal": "close representative Blender pose-space/visual gates without changing source parsing unless evidence requires it",
        },
        {
            "priority": "P0",
            "area": "generic_model_authoring",
            "goal": "promote safe saved-Blender build paths for common Model0.62 static/rigid scopes",
        },
        {
            "priority": "P1",
            "area": "inx_smb_writers",
            "goal": "move corpus-proven candidates through runtime-semantic and production-policy gates",
        },
        {
            "priority": "P1",
            "area": "profiles_lod",
            "goal": "turn exact profile/LOD evidence into a generic authoring workflow without basename guessing",
        },
        {
            "priority": "P1",
            "area": "stage072",
            "goal": "bridge specialized witnesses/paint into a guarded saved-edit build path",
        },
        {
            "priority": "P2",
            "area": "generic_publish_restore",
            "goal": "integrate transactional dry-run/backup/drift/rollback only after per-family writers are production-authorized",
        },
    ]

    return {
        "format": FORMAT,
        "release_1_coverage": {
            "format": release1_coverage.get("format"),
            "blocking_gate_count": release1_coverage.get("blocking_gate_count"),
            "content_domains": release1_coverage.get("content_domains"),
            "required_capabilities": release1_coverage.get("required_capabilities"),
        },
        "status": "PASS",
        "development_state": "IN_PROGRESS" if remaining else "READY_FOR_PROMOTION",
        "deep": bool(deep),
        "asset_count": len(assets),
        "family_counts": dict(sorted(family_counts.items())),
        "kind_counts": dict(sorted(kind_counts.items())),
        "stages": stages,
        "priorities": priorities,
        "remaining_blocker_count": len(remaining),
        "remaining_blockers": remaining,
        "deep_results": deep_results,
        "policy": {
            "client_source_write_default": False,
            "candidate_writer_roundtrip_is_production_authorization": False,
            "mixed_physique_without_representative_is_supported": False,
        },
        "client_modified": False,
    }
