from __future__ import annotations
import argparse, collections, json, os, pathlib, shutil, subprocess, sys
from . import __version__
from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .validation import ValidationContext, ValidationRunner, audit_rigid_model_info_contexts
from .physique_audit import audit_physique_modes
from .object_local_audit import audit_object_local
from .app_config import configured_contract_donor_clients, configured_contract_donor_servers
from .object_local import compact_report, parse_object_local_smd
from .object_local_writer import patch_existing_object_local_key, audit_object_local_writer_corpus
from .object_local_corpus import audit_object_local_physical_corpus
from .texlink_corpus import audit_multilayer_texlink_corpus, parse_texlink_file
from .multilayer_texlink import audit_multilayer_semantics_corpus, compact_semantics, parse_multilayer_semantics
from .stage072_corpus import audit_stage072_physical_corpus
from .stage072_texture_audit import audit_stage072_texture_presence
from .stage072_area import audit_stage072_stagearea_rebuild
from .stage072_normals import audit_stage072_normals
from .rare_outliers import audit_rare_outliers_and_tga
from .rare_support import audit_rare_support
from .rare_rigid_context import audit_rare_rigid_context
from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_preview import audit_rare_rigid_preview, view_rare_rigid_preview
from .rare_rigid_geometry import audit_rare_rigid_geometry_preflight
from .rare_rigid_roundtrip import audit_rare_rigid_single_bone_roundtrip
from .rare_rigid_normal_bridge import audit_rare_rigid_normal_provenance_roundtrip
from .rare_rigid_extent_bridge import audit_rare_rigid_outward_extent_roundtrip
from .rare_rigid_multibone_bridge import audit_rare_rigid_multibone_bridge
from .rare_rigid_multibone_roundtrip import audit_rare_rigid_guarded_multibone_roundtrip
from .rare_rigid_edit import prepare_at_dragon_edit_workspace, write_at_dragon_edit_workspace, audit_rare_rigid_edit_workflow
from .blender_workspace import blender_edit_root, write_workspace_info, asset_workspace_name
from .inx_writer import validate_noop_roundtrip, patch_motion
from .animation_source_regression import audit_animation_source_regression
from .animation_corpus import audit_animation_corpus
from .animation_certification import build_animation_certification_plan
from .workflow_dispatch import build_plan
from .smb_writer import validate_track_roundtrip, patch_key
from .profile_registry import CharacterProfileRegistry
from .profile_candidates import discover_profile_candidates
from .profile_authoring import plan_profile_authoring_context
from .binding_coverage import audit_binding_coverage
from .writer_corpus_audit import (
    audit_inx_writer_corpus, audit_smb_writer_corpus,
    audit_inx_writer_edit_corpus, audit_smb_writer_edit_corpus,
    audit_motion_writer_semantic_edit_corpus,
)
from .development_readiness import audit_development_readiness
from .deployment import plan_deployment, prepare_deployment_transaction, verify_deployment_transaction, simulate_deployment_transaction, classify_client_transaction_state, plan_restore_transaction
from .workspace_bundle_deploy import (
    APPLY_CONFIRMATION as WORKSPACE_BUNDLE_APPLY_CONFIRMATION,
    RESTORE_CONFIRMATION as WORKSPACE_BUNDLE_RESTORE_CONFIRMATION,
    prepare_workspace_bundle, apply_workspace_bundle_transaction,
    verify_workspace_bundle_transaction, workspace_bundle_status,
    restore_workspace_bundle_transaction, bundle_history,
    publish_workspace_bundle, restore_latest_workspace_bundle, restore_latest_workspace_model,
    check_latest_workspace_bundle,
)
from .authoring import authoring_plan, audit_model062_authoring, verify_workspace_manifest
from .static_authoring_candidate import plan_static_saved_blender_candidate, validate_static_candidate_output, build_static_candidate_blender_command
from .rigid_authoring_candidate import plan_rigid_saved_blender_candidate, validate_rigid_candidate_output, build_rigid_candidate_blender_command, inspect_rigid_candidate_scope
from .rigid_authoring_stress import plan_rigid_profile_stress_candidate, validate_rigid_profile_stress_output
from .mixed_authoring_candidate import plan_mixed_saved_blender_candidate, validate_mixed_candidate_output, build_mixed_candidate_step_command
from .model062_material_writer import rebuild_material_fields, verify_material_candidate
from .stage072_material_writer import rebuild_stage_material_fields, verify_stage_material_candidate
from .rigid_profile_devtest import run_rigid_profile_automated_devtest_batch
from .release_1_coverage import build_release_1_coverage, build_release_1_automated_gate_plan
from .release_1_auto import run_release_1_automated_gate
from .environment_validation import run_environment_validation
from .server_environment_validation import run_server_environment_validation
from .server_inventory import audit_server_inventory
from .server_bundle_census import audit_server_entity_bundles
from .server_field_census import audit_server_field_bundles
from .server_item_census import audit_server_item_bundles
from .skill_contract_census import TARGET_CLASSES, audit_player_class_contracts
from .aggregation import build_player_class_aggregation
from .superset_aggregation import build_client_superset, build_server_superset, build_summit_superset
from .source_contract_census import audit_source_contracts
from .general_asset_census import audit_general_asset_census
from .class_ui_alias_audit import audit_class_ui_aliases
from .class_ui_alias_canonicalize import canonicalize_class_ui_alias_only
from .general_asset_recovery import recover_closed_general_asset_bundles
from .server_design_auto import run_server_design_auto
from .physical_regression_auto import run_physical_regression_auto
from .integration_regression_auto import run_integration_regression_auto
from .enrichment_vendor_adapter import generate_migration_plan, build_dependency_graph
from .stage072_authoring_candidate import (
    plan_stage072_saved_blender_candidate,
    build_stage072_edit_extract_command,
    apply_stage072_candidate_witness,
)
from .build_provenance import write_build_provenance, sha256_file
from .rigid_authoring_evidence import (
    AUTOMATIC_LAYER, AUTOMATIC_TEST, HUMAN_LAYER,
    build_candidate_provenance_evidence, build_rigid_authoring_certification_plan,
    prepare_rigid_candidate_review_workspace, rigid_candidate_context_key,
    verify_rigid_candidate_artifact, verify_rigid_candidate_review_workspace,
)
from .entity_catalog import entity_detail, load_entity_seed, query_entities
from .client_enrichment import audit_client_enrichment
from .asset_contract_registry import registry_summary, get_contract, schema_for_contract
from .legacy_management_contracts import classify_item_code, legacy_management_summary, verify_management_root
from .item_runtime_catalog import lookup_item_runtime
from .legacy_management_audit import audit_legacy_management
from .legacy_authoring import authoring_capabilities, inspect_authoring, stage_authoring, publish_authoring, restore_authoring
from .asset_compiler import compiler_capabilities, plan_compiler_input, compile_compiler_input
from .asset_bundle_deploy import (
    APPLY_CONFIRM as ASSET_BUNDLE_APPLY_CONFIRM,
    RESTORE_CONFIRM as ASSET_BUNDLE_RESTORE_CONFIRM,
    latest_bundle_manifest, publish_asset_bundle, restore_asset_bundle, asset_bundle_deploy_status,
)
from .ui_catalog import CatalogIndex, UIStateStore
from .utils import norm_path, run_logged


def make_context(a):
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    resolver = ClientResolver(s.client_root)
    reg = AssetRegistry(s.inventory, s.pairing, resolver=resolver)
    cert = CertificationRegistry(s.certifications_dir)
    return s, reg, cert, resolver


def table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = min(80, max(widths[i], len(str(val))))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        vals = []
        for i, val in enumerate(row):
            s = str(val)
            if len(s) > widths[i]:
                s = s[:max(1, widths[i]-1)] + "…"
            vals.append(s.ljust(widths[i]))
        print("  ".join(vals))


def cmd_doctor(a):
    s, reg, cert, resolver = make_context(a)
    checks = []
    def add(name, ok, detail): checks.append((name, "PASS" if ok else "FAIL", detail))
    add("project_root", s.project_root.is_dir(), s.project_root)
    add("inventory", s.inventory.is_file(), s.inventory)
    add("pairing", s.pairing.is_file(), s.pairing)
    add("canonical_records", len(reg.records) > 0, len(reg.records))
    physique_audit = audit_physique_modes(reg.records)
    pm = physique_audit["raw_mode_counts"]
    add(
        "model062_physique_partition",
        physique_audit["compatibility_gate"] == "PASS",
        f"RIGID={pm['RIGID']} STATIC={pm['STATIC']} MIXED={pm['MIXED']} UNKNOWN={pm['UNKNOWN']} objects={physique_audit['object_headers_audited']}",
    )
    required = [
        "pt_character_structural_gate_v2.py", "pt_inx_motion_core_v2.py",
        "pt_character_texture_v1_4.py", "pt_blender_bind_editable_texture_v2.py",
        "pt_protected_tga_v1.py", "pt_asset_tool/blender_workspace.py",
        "pt_smd_static_capability_probe_v1.py", "pt_smd_blender_import_v4_generic.py",
        "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py",
        "pt_asset_tool/blender/witness_geometry.py",
        "pt_asset_tool/blender/bake_actions.py", "pt_asset_tool/motion_core.py",
        "summit_workspace_asset_bridge_v1_2.py", "summit_roundtrip_restore_v4.py",
        "pt_asset_tool/deployment.py", "pt_asset_tool/build_provenance.py", "pt_asset_tool/development_readiness.py",
        "pt_asset_tool/rigid_authoring_evidence.py",
        "pt_asset_tool/rigid_authoring_stress.py",
        "pt_asset_tool/rigid_profile_devtest.py",
        "pt_asset_tool/rigid_semantic_devtest.py",
        "pt_asset_tool/standalone_rigid_devtest.py",
        "pt_asset_tool/rigid_context_census.py",
        "pt_asset_tool/standalone_animation_devtest.py",
        "pt_asset_tool/mixed_authoring_candidate.py",
        "pt_asset_tool/mixed_synthetic_devtest.py",
        "pt_asset_tool/model062_material_writer.py",
        "pt_asset_tool/model062_material_devtest.py",
        "pt_asset_tool/model062_texture_audit.py",
        "pt_asset_tool/static_semantic_devtest.py",
        "pt_asset_tool/stage072_semantic_devtest.py",
        "pt_asset_tool/stage072_material_writer.py",
        "pt_asset_tool/stage072_material_devtest.py",
        "pt_asset_tool/animation_pose_devtest.py",
        "pt_asset_tool/texture_codec_devtest.py",
        "pt_asset_tool/object_local_devtest.py",
        "pt_asset_tool/texlink_devtest.py",
        "pt_asset_tool/release_1_coverage.py",
        "pt_asset_tool/release_1_auto.py",
        "pt_asset_tool/environment_validation.py",
        "pt_asset_tool/blender/apply_rigid_profile_devtest.py",
        "pt_asset_tool/blender/check_rigid_profile_devtest.py",
        "pt_asset_tool/blender/apply_static_semantic_devtest.py",
        "pt_asset_tool/blender/check_static_semantic_devtest.py",
        "pt_asset_tool/blender/apply_stage072_semantic_devtest.py",
        "pt_asset_tool/blender/check_baked_animation_pose.py",
        "pt_asset_tool/profile_candidates.py", "pt_asset_tool/animation_certification.py",
        "pt_blender_to_smd_static_v1.py", "pt_blender_to_smd_free_mesh_v3.py", "pt_asset_tool/static_roundtrip.py",
        "pt_asset_tool/blender/write_static_witness.py",
        "pt_asset_tool/object_local.py", "pt_asset_tool/object_local_corpus.py", "pt_asset_tool/blender/bake_object_local.py",
        "pt_asset_tool/texlink_corpus.py", "pt_asset_tool/multilayer_texlink.py",
        "pt_asset_tool/texlink_roundtrip.py",
        "pt_asset_tool/stage072_corpus.py",
        "pt_asset_tool/stage072_texture_audit.py",
        "pt_asset_tool/stage072_roundtrip.py",
        "pt_asset_tool/stage072_area.py",
        "pt_asset_tool/stage072_normals.py",
        "pt_asset_tool/stage072_geometry.py",
        "pt_asset_tool/stage072_authoring_candidate.py",
        "pt_asset_tool/rare_outliers.py",
        "pt_asset_tool/rare_support.py",
        "pt_asset_tool/rare_rigid_context.py",
        "pt_asset_tool/rare_rigid_binding.py",
        "pt_asset_tool/rare_rigid_preview.py",
        "pt_asset_tool/rare_rigid_geometry.py",
        "pt_asset_tool/rare_rigid_roundtrip.py",
        "pt_asset_tool/rare_rigid_normal_bridge.py",
        "pt_asset_tool/rare_rigid_extent_bridge.py",
        "pt_asset_tool/rare_rigid_multibone_bridge.py",
        "pt_asset_tool/rare_rigid_multibone_roundtrip.py",
        "pt_asset_tool/rare_rigid_edit.py",
        "pt_asset_tool/rare_rigid_multivertex.py",
        "pt_asset_tool/rare_rigid_large_production.py",
        "pt_asset_tool/rare_rigid_cross_object_probe.py",
        "pt_asset_tool/rare_rigid_cross_object_saved_blender_candidate.py",
        "pt_asset_tool/rare_rigid_cross_object_live_writer_candidate.py",
        "pt_asset_tool/rare_rigid_cross_object_interactive_candidate.py",
        "pt_asset_tool/rare_rigid_cross_object_production.py",
        "pt_asset_tool/rare_rigid_cross_object_production_promotion.py",
        "pt_asset_tool/blender/import_stage072.py",
        "pt_asset_tool/blender/open_stage072_preview.py",
        "pt_asset_tool/blender/open_stage072_paint.py",
        "pt_asset_tool/blender/import_rare_rigid_context.py",
        "pt_asset_tool/blender/check_rare_rigid_context.py",
        "pt_asset_tool/blender/open_rare_rigid_preview.py",
        "pt_asset_tool/blender/witness_rare_rigid_geometry.py",
        "pt_asset_tool/blender/check_rare_rigid_geometry_witness.py",
        "pt_asset_tool/blender/prepare_rare_rigid_edit.py",
        "pt_asset_tool/blender/canonicalize_rare_rigid_edit.py",
        "pt_asset_tool/blender/capture_rare_rigid_edit_baseline.py",
        "pt_asset_tool/blender/extract_rare_rigid_edit.py",
        "pt_asset_tool/blender/apply_rare_rigid_artist_witness.py",
        "pt_asset_tool/blender/apply_rare_rigid_transaction_witness.py",
        "pt_asset_tool/blender/check_rare_rigid_transaction.py",
        "pt_asset_tool/blender/open_rare_rigid_edit.py",
        "pt_asset_tool/blender/check_stage072_transport.py",
        "pt_asset_tool/blender/witness_stage072_uv.py",
        "pt_asset_tool/blender/write_stage072_uv.py",
        "pt_asset_tool/blender/witness_stage072_geometry.py",
        "pt_asset_tool/blender/write_stage072_geometry.py",
        "pt_asset_tool/blender/extract_stage072_saved_edit.py",
        "pt_asset_tool/blender/apply_multilayer_texlink.py",
        "pt_asset_tool/blender/witness_multilayer_texlink.py",
        "pt_asset_tool/blender/write_multilayer_texlink.py",
    ]
    for rel in required:
        add(rel, (s.project_root / rel).is_file(), s.project_root / rel)
    add("client_root", s.client_root.is_dir(), s.client_root)
    add("python", bool(shutil.which("python3")), shutil.which("python3") or "not found")
    bc = s.blender_command()
    if bc and bc[0] == "flatpak":
        ok = bool(shutil.which("flatpak"))
        detail = " ".join(bc)
        if ok and "org.blender.Blender" in bc:
            probe = subprocess.run(["flatpak", "info", "org.blender.Blender"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ok = probe.returncode == 0
    else:
        ok = bool(bc and shutil.which(bc[0]))
        detail = " ".join(bc)
    add("blender_command", ok, detail)
    table(checks, ["CHECK", "STATUS", "DETAIL"])
    failed = [x for x in checks if x[1] == "FAIL"]
    print(f"\nassets={len(reg.assets)} canonical_records={len(reg.records)} certifications={len(cert.records())}")
    if reg.duplicate_relpaths:
        print(f"doctor_note=canonical case-only relative-path pairs: {len(reg.duplicate_relpaths)} (exact-case resolver enabled)")
    print(f"doctor_check={'PASS' if not failed else 'FAIL'}")
    return 0 if not failed else 2


def cmd_audit_physique(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_physique_modes(reg.records)
    if a.output:
        out = pathlib.Path(a.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "physique_audit=" + result["status"] +
        f" rigid={result['raw_mode_counts']['RIGID']}" +
        f" static={result['raw_mode_counts']['STATIC']}" +
        f" mixed={result['raw_mode_counts']['MIXED']}"
    )
    return 0 if result["compatibility_gate"] == "PASS" else 3


def cmd_audit_animation_certification_plan(a):
    s, reg, cert, resolver = make_context(a)
    result = build_animation_certification_plan(
        s.project_root, reg, resolver, category=a.category,
        context_limit=int(a.context_limit or 0),
        motions_per_context=int(a.motions_per_context),
        sample_limit=int(a.sample_limit),
    )
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "PARTIAL"} else 3


def cmd_audit_object_local(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_object_local(reg.records, limit=a.limit)
    if a.output:
        out = pathlib.Path(a.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "object_local_audit=" + result["status"] +
        f" files={result['object_local_candidate_files']}" +
        f" objects={result['object_local_candidate_objects']}"
    )
    return 0 if result["discovery_gate"] == "PASS" else 3


def cmd_audit_object_local_corpus(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_object_local_physical_corpus(
        reg.records, resolver, bundle=a.bundle, per_subtype=a.per_subtype
    )
    if a.output:
        out = pathlib.Path(a.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    summary = {k: v for k, v in result.items() if k != "rows"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        "object_local_corpus_audit=" + result["status"] +
        f" audited={result['physical_files_audited']}/{result['candidate_files_expected']}" +
        f" animated_child={result['animated_child_files']}" +
        f" segmented={result['segmented_tmframe_files']}" +
        f" complete_candidate={str(result['object_local_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_texlink_corpus(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_multilayer_texlink_corpus(
        reg.records, resolver, bundle=a.bundle, per_profile=a.per_profile
    )
    if a.output:
        out = pathlib.Path(a.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    summary = {k: v for k, v in result.items() if k != "rows"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        "multilayer_texlink_corpus_audit=" + result["status"] +
        f" audited={result['physical_files_audited']}/{result['candidate_files_expected']}" +
        f" max_depths={result['max_layer_depth_counts']}" +
        f" full={result['full_face_multilayer_files']}" +
        f" partial={result['partial_face_multilayer_files']}" +
        f" complete_candidate={str(result['multilayer_two_stage_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_stage072_corpus(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_stage072_physical_corpus(
        reg.records, resolver, bundle=a.bundle, per_profile=a.per_profile
    )
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result)
    shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "stage072_corpus_audit=" + result["status"] +
        f" audited={result['physical_files_audited']}/{result['candidate_files_expected']}" +
        f" full_parse={result['full_parse_pass_files']}" +
        f" depths={result['max_texlink_depth_file_counts']}" +
        f" area={result['area_encoding_file_counts']}" +
        f" depth3={result.get('files_with_depth3', 0)}" +
        f" opaque={result.get('files_with_opaque_trailing', 0)}" +
        f" complete_candidate={str(result['stage072_physical_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_stage072_stagearea(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_stage072_stagearea_rebuild(reg.records, resolver, bundle=a.bundle)
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result); shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "stage072_stagearea_rebuild_audit=" + result["status"] +
        f" audited={result['physical_files_audited']}/{result['candidate_files_expected']}" +
        f" rebuilt={result['reconstruction_pass_files']}" +
        f" encodings={result['area_encoding_file_counts']}" +
        f" capacity_models={result['capacity_model_file_counts']}" +
        f" max_span={result['max_face_area_cell_span']}/{result['area_list_capacity']}" +
        f" complete_candidate={str(result['stagearea_rebuild_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_stage072_textures(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_stage072_texture_presence(
        reg.records, resolver, bundle=a.bundle
    )
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result)
    shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "stage072_texture_reference_audit=" + result["status"] +
        f" audited={result['physical_files_audited']}/{result['candidate_files_expected']}" +
        f" unique={result['unique_face_material_scoped_texture_references']}" +
        f" exact_missing={result['exact_missing_unique_texture_references']}" +
        f" aliases={result['runtime_alias_present_unique_texture_references']}" +
        f" invalid={result['serialized_invalid_unique_texture_references']}" +
        f" client_missing={result['client_missing_unique_texture_references']}" +
        f" classification_complete={str(result['texture_reference_classification_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_support(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_usable_family_support_v075"
    result = audit_rare_support(resolver, work=work)
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result); shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "rare_support=" + result["status"] +
        f" prepared={result['prepared_usable_outliers']}/{result['expected_usable_outliers']}" +
        f" model062={result['model062_prepared']}" +
        f" alt_magic={result['model062_alt_magic_prepared']}" +
        f" legacy_name_mismatch={result['model062_legacy_name_mismatch_prepared']}" +
        f" ship_bmp={result['ship_bmp_prepared']}" +
        f" complete={str(result['usable_family_support_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_outliers(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_rare_outliers_and_tga(reg.records, resolver, bundle=a.bundle)
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        full = dict(result)
        full["report"] = str(out)
        out.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result); shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "rare_outliers_tga_census=" + result["status"] +
        f" outliers={result['known_outliers_physically_audited']}/{result['known_outliers_expected']}" +
        f" tga_scanned={result['tga_physical_files_scanned']}" +
        f" tga_unresolved={result['tga_unresolved_support_count']}" +
        f" tga_support_issues={result['tga_support_issue_count']}" +
        f" outlier_families_complete={str(result['rare_outlier_family_classification_complete_candidate']).lower()}" +
        f" tga_families_complete={str(result['tga_family_classification_complete_candidate']).lower()}" +
        f" census_complete={str(result['rare_physical_census_complete_candidate']).lower()}" +
        " support_complete=false"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_rigid_context(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_context_v076"
    result = audit_rare_rigid_context(reg, resolver, work=work, bundle=a.bundle)
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        full = dict(result)
        full["report"] = str(out)
        out.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result); shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_context=" + result["status"] +
        f" audited={result['physically_audited']}/{result['expected_rare_model062']}" +
        f" rigid={result['rigid_physique_files']}" +
        f" head_only={result['head_only_bip01_head_files']}" +
        f" body_rigid={result['body_rigid_files']}" +
        f" pairings={result['files_with_exact_pairing_context']}" +
        f" binding_complete={str(result['rare_rigid_binding_resolution_complete_candidate']).lower()}" +
        f" preview_authorized={str(result['preview_integration_authorized']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_rigid_binding(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_binding_v077"
    result = audit_rare_rigid_binding(reg, resolver, project_root=s.project_root, work=work, bundle=a.bundle)
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        full = dict(result); full["report"] = str(out)
        out.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result); shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_binding=" + result["status"] +
        f" audited={result['physically_audited']}/{result['expected_rare_model062']}" +
        f" verified={result['verified_binding_files']}" +
        f" links={result['verified_source_links']}" +
        f" motions={result['resolved_motion_smb_count']}" +
        f" binding_complete={str(result['rare_rigid_binding_resolution_complete_candidate']).lower()}" +
        f" preview_authorized={str(result['preview_integration_authorized']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_rigid_preview(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_preview_v078"
    result = audit_rare_rigid_preview(
        reg, resolver, cert, s, project_root=s.project_root, work=work
    )
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        full = dict(result); full["report"] = str(out)
        out.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result); shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_preview=" + result["status"] +
        f" audited={result['audited']}/{result['expected']}" +
        f" preview_pass={result['preview_pass']}" +
        f" head_accessory={result['head_accessory_preview']}" +
        f" source_inx_exact={result['source_inx_exact_preview']}" +
        f" texture_errors={result['texture_load_error_total']}" +
        f" physique_bad={result['physique_mismatch_total']}" +
        f" complete={str(result['preview_integration_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3



def cmd_audit_rare_rigid_geometry(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_geometry_v079"
    result = audit_rare_rigid_geometry_preflight(
        reg, resolver, project_root=s.project_root, work=work
    )
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        full = dict(result); full["report"] = str(out)
        out.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    shown = dict(result); shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_geometry=" + result["status"] +
        f" audited={result.get('audited',0)}/{result.get('expected',0)}" +
        f" single_bone_candidates={result.get('single_bone_candidate_count',0)}" +
        f" mixed_bone_faces={result.get('mixed_bone_faces',0)}" +
        f" pos_roundtrip_max={result.get('position_forward_inverse',{}).get('max_abs',0)}" +
        f" normal_roundtrip_max={result.get('normal_endpoint_forward_inverse',{}).get('max_abs',0)}" +
        f" write_authorized={str(result.get('geometry_write_authorized',False)).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3

def cmd_audit_rare_rigid_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_single_bone_roundtrip_v080"
    result = audit_rare_rigid_single_bone_roundtrip(
        reg, resolver, cert, s, project_root=s.project_root, work=work
    )
    if a.output:
        op = pathlib.Path(a.output)
        if not op.is_absolute(): op = s.project_root / op
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["output"] = str(op)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_geometry_roundtrip=" + result["status"] +
        f" audited={result.get('audited',0)}/{result.get('expected',0)}" +
        f" pass={result.get('roundtrip_pass',0)}" +
        f" reimport_error_fixed={result.get('max_requested_reimport_error_fixed',0)}" +
        f" normal_vector_drift_fixed={result.get('max_world_normal_vector_delta_fixed',0)}" +
        f" position_write_authorized={str(result.get('single_bone_position_write_authorized',False)).lower()}" +
        f" arbitrary_geometry={str(result.get('arbitrary_geometry_write_authorized',False)).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_rigid_normal_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_normal_provenance_v081"
    result = audit_rare_rigid_normal_provenance_roundtrip(
        reg, resolver, cert, s, project_root=s.project_root, work=work
    )
    if a.output:
        op = pathlib.Path(a.output)
        if not op.is_absolute(): op = s.project_root / op
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["output"] = str(op)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_normal_roundtrip=" + result["status"] +
        f" audited={result.get('audited',0)}/{result.get('expected',0)}" +
        f" pass={result.get('roundtrip_pass',0)}" +
        f" source_normal_delta_fixed={result.get('max_current_source_normal_delta_fixed',0)}" +
        f" normal_reimport_error_fixed={result.get('max_target_reimport_normal_error_fixed',0)}" +
        f" normal_write_authorized={str(result.get('single_bone_normal_provenance_write_authorized',False)).lower()}" +
        f" extent_write={str(result.get('extent_changing_geometry_write_authorized',False)).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_rigid_extent_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_outward_extent_v082"
    result = audit_rare_rigid_outward_extent_roundtrip(
        reg, resolver, cert, s, project_root=s.project_root, work=work
    )
    if a.output:
        op = pathlib.Path(a.output)
        if not op.is_absolute(): op = s.project_root / op
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["output"] = str(op)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_extent_roundtrip=" + result["status"] +
        f" audited={result.get('audited',0)}/{result.get('expected',0)}" +
        f" pass={result.get('roundtrip_pass',0)}" +
        f" bound_coverage={','.join(result.get('bound_field_coverage') or [])}" +
        f" reimport_error_fixed={result.get('max_requested_reimport_error_fixed',0)}" +
        f" normal_reimport_error_fixed={result.get('max_target_reimport_normal_error_fixed',0)}" +
        f" outward_extent_write={str(result.get('single_bone_outward_extent_write_authorized',False)).lower()}" +
        f" contraction_write={str(result.get('extent_contraction_write_authorized',False)).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_rigid_multibone(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_multibone_v083"
    result = audit_rare_rigid_multibone_bridge(
        reg, resolver, project_root=s.project_root, work=work
    )
    if a.output:
        op = pathlib.Path(a.output)
        if not op.is_absolute(): op = s.project_root / op
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["output"] = str(op)
    shown = dict(result)
    shown.pop("object_rows", None)
    shown.pop("mixed_combo_face_counts", None)
    shown.pop("representative_witnesses", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_multibone=" + result["status"] +
        f" mixed_faces={result.get('mixed_bone_faces',0)}" +
        f" mixed_vertices={result.get('mixed_boundary_vertices',0)}" +
        f" safe_vertices={result.get('safe_mixed_boundary_vertices',0)}" +
        f" safe_faces={result.get('mixed_faces_with_safe_vertex',0)}" +
        f" combos={result.get('safe_mixed_bone_combinations',0)}/{result.get('distinct_mixed_bone_combinations',0)}" +
        f" reps2={str(result.get('representative_2bone_found',False)).lower()}" +
        f" reps3={str(result.get('representative_3bone_found',False)).lower()}" +
        f" reps4={str(result.get('representative_4bone_found',False)).lower()}" +
        f" writer_candidate={str(result.get('guarded_multibone_writer_candidate',False)).lower()}" +
        f" write_authorized={str(result.get('multibone_geometry_write_authorized',False)).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_audit_rare_rigid_multibone_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_multibone_roundtrip_v084"
    result = audit_rare_rigid_guarded_multibone_roundtrip(
        reg, resolver, cert, s, project_root=s.project_root, work=work
    )
    if a.output:
        op = pathlib.Path(a.output)
        if not op.is_absolute(): op = s.project_root / op
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["output"] = str(op)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_multibone_roundtrip=" + result["status"] +
        f" audited={result.get('audited_representatives',0)}/{result.get('expected_representatives',0)}" +
        f" pass={result.get('roundtrip_pass',0)}" +
        f" bone_counts={','.join(str(x) for x in result.get('representative_bone_counts') or [])}" +
        f" safe_vertices={result.get('safe_mixed_boundary_vertices',0)}" +
        f" blocked_vertices={result.get('blocked_mixed_boundary_vertices',0)}" +
        f" normal_reimport_error_fixed={result.get('max_target_reimport_normal_error_fixed',0)}" +
        f" guarded_write={str(result.get('guarded_multibone_position_normal_write_authorized',False)).lower()}" +
        f" universal_write={str(result.get('universal_at_dragon_geometry_write_authorized',False)).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_view_rare_model(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_view_v078"
    result = view_rare_rigid_preview(
        reg, resolver, cert, s, project_root=s.project_root, target=a.target, work=work
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _print_asset_table_legend():
    print("\nLegend:")
    print("  PENDING = this certification/gate has not been completed yet; it does not mean the file is bad.")
    print("  N/A     = the check does not apply to this asset type (for example animation on a texture/static asset).")
    print("  CONTEXT = rigid model context exists, but no final human animation certification is recorded yet.")
    print("  PASS/FAIL/SKIP = recorded certification result.")
    print("  Binding NONE = no skeleton/motion relation is expected or resolved for this asset.")
    print("  SELF_CONTAINED = this model's config directly resolves its motion/skeleton SMB.")
    print("  ROOT_SKELETON_BOUND = this model reuses a verified root skeleton/motion context.")
    print("  CONFIG_ONLY = config exists, but a unique animation root is not sufficiently resolved; animation stays fail-closed.")
    print("  Tip: `python3 pt_asset.py explain bindings` and `python3 pt_asset.py explain statuses`.")


def cmd_assets_list(a):
    s, reg, cert, resolver = make_context(a)
    assets = reg.list_assets(category=a.category, family=a.family, extension=a.ext, visual_only=a.visual_only)
    rows = []
    if getattr(a, "gates", False):
        latest = cert.latest()
        for asset in assets[:a.limit]:
            geometry = latest.get((asset.asset_id, "VISUAL_GEOMETRY", "HUMAN_VISUAL"), {}).get("result", "PENDING")
            texture = latest.get((asset.asset_id, "VISUAL_TEXTURE_MATERIAL", "HUMAN_VISUAL"), {}).get("result", "PENDING") if asset.textures else "N/A"
            visual = latest.get((asset.asset_id, "VISUAL_ASSET", "HUMAN_VISUAL"), {}).get("result", "PENDING")
            animation = latest.get((asset.asset_id, "VISUAL_ANIMATION_ASSET", "HUMAN_VISUAL"), {}).get("result", "PENDING") if asset.animation_binding_ready else ("CONTEXT" if asset.visual_mode == "RIGID" else "N/A")
            structural = latest.get((asset.asset_id, "STRUCTURAL", "AUTOMATIC"), {}).get("result", "PENDING")
            rows.append((asset.asset_id, asset.category, asset.family, asset.binding_mode, structural, geometry, texture, visual, animation, asset.primary_path))
        table(rows, ["ID", "CATEGORY", "FAMILY", "BINDING", "STRUCT", "GEOM", "TEX/MAT", "VISUAL", "ANIM", "PATH"])
        print(f"\nshown={len(rows)} matching={len(assets)}")
        _print_asset_table_legend()
    else:
        for asset in assets[:a.limit]:
            rows.append((asset.asset_id, asset.category, asset.family, asset.binding_mode, asset.primary_path))
        table(rows, ["ID", "CATEGORY", "FAMILY", "BINDING", "PATH"])
        print(f"\nshown={len(rows)} matching={len(assets)}")
        print("Tip: add `--gates` to show STRUCT/GEOM/TEX-MAT/VISUAL/ANIM certification coverage; PENDING means not yet certified, not broken.")
    return 0


def _profile_registry(s):
    return CharacterProfileRegistry(s.project_root / "pt_build" / "state" / "character_profiles")


def cmd_profiles_list(a):
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    registry = _profile_registry(s)
    rows = []
    for p in registry.list():
        rows.append((p.profile_id, p.owner_name, len(p.lod_groups.get("high", [])), len(p.lod_groups.get("default", [])), len(p.lod_groups.get("low", [])), p.roundtrip_target))
    table(rows, ["PROFILE", "OWNER", "HIGH", "DEFAULT", "LOW", "MODEL"] )
    print(f"\nprofiles={len(rows)}")
    return 0


def cmd_profiles_inspect(a):
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    profile = _profile_registry(s).get(a.profile_id)
    print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_profiles_lod(a):
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    profile = _profile_registry(s).get(a.profile_id)
    objects = profile.lod(a.lod)
    result = {
        "format": "PT_CHARACTER_PROFILE_LOD_SELECTION_V1",
        "status": "PASS",
        "profile_id": profile.profile_id,
        "lod": a.lod,
        "objects": objects,
        "object_count": len(objects),
        "runtime_proven": bool(profile.geometry_status.get("all_lods_runtime_proven")) if a.lod == "all" else bool(profile.geometry_status.get(f"{a.lod}_lod_runtime_proven", profile.geometry_status.get("single_object_runtime_proven", False))),
        "client_modified": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_profiles_discover(a):
    s, reg, cert, resolver = make_context(a)
    result = discover_profile_candidates(
        reg, category=a.category, limit=int(a.limit or 0),
        profile_registry=_profile_registry(s),
    )
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0



def cmd_profiles_authoring_plan(a):
    s, reg, cert, resolver = make_context(a)
    result = plan_profile_authoring_context(
        _profile_registry(s), a.profile_id, resolver, reg, lod=a.lod
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "READY" else 3

def cmd_profiles_verify(a):
    s, reg, cert, resolver = make_context(a)
    registry = _profile_registry(s)
    if not a.all and not a.profile_id:
        raise ValueError("profile_id or --all is required")
    ids = [p.profile_id for p in registry.list()] if a.all else [a.profile_id]
    results = [registry.verify(profile_id, resolver, asset_registry=reg) for profile_id in ids]
    overall = "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL"
    report = {
        "format": "PT_CHARACTER_PROFILE_VERIFY_BATCH_V1",
        "status": overall,
        "profile_count": len(results),
        "results": results,
        "client_modified": False,
    }
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = (s.project_root / out).resolve()
        else:
            out = out.resolve()
        build = (s.project_root / "pt_build").resolve()
        if out != build and build not in out.parents:
            raise RuntimeError("profile verify output must remain under pt_build")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["output"] = str(out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 3


def _entity_catalog_context(s, reg):
    state = UIStateStore(s.project_root / "pt_build" / "ui_state.json")
    catalog = CatalogIndex(s.client_root, state)
    catalog.rebuild()
    seed = load_entity_seed(s.project_root)
    return catalog, seed


def cmd_entities_list(a):
    s, reg, cert, resolver = make_context(a)
    catalog, seed = _entity_catalog_context(s, reg)
    report = query_entities(
        catalog.assets,
        seed,
        group=a.group or "",
        q=a.q or "",
        limit=a.limit,
        registry=reg,
    )
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    rows = []
    for e in report["items"]:
        rows.append((
            e["semantic_group"],
            e["display_name"],
            e["asset_count"],
            len(e.get("model_paths") or []),
            len(e.get("config_paths") or []),
            len(e.get("animation_paths") or []),
            e.get("registry_asset_count", 0),
            e.get("rigid_binding_ready_count", 0),
            e.get("animation_binding_ready_count", 0),
            e["folder_root"],
        ))
    table(rows, ["GROUP", "ENTITY", "FILES", "MODEL", "CONFIG", "ANIM", "REG", "BIND", "ANIM-RDY", "FOLDER"])
    print(f"\nshown={len(rows)} live_entities={report['live_entity_count']} known_seed={report['known_seed_entity_count']}")
    return 0


def cmd_entities_inspect(a):
    s, reg, cert, resolver = make_context(a)
    catalog, seed = _entity_catalog_context(s, reg)
    group = str(a.group).upper()
    query = str(a.entity).strip()
    report = query_entities(catalog.assets, seed, group=group, q=query, limit=2000, registry=reg)
    candidates = [
        e for e in report["items"]
        if e["semantic_group"] == group and (
            str(e["display_name"]).casefold() == query.casefold()
            or str(e["folder_root"]).casefold() == query.casefold()
            or str(e["entity_key"]).casefold() == query.casefold()
        )
    ]
    if not candidates:
        raise KeyError(f"entity not found: {group} {a.entity}")
    if len(candidates) > 1:
        raise RuntimeError(f"ambiguous entity: {group} {a.entity}; matches={len(candidates)}")
    detail = entity_detail(catalog.assets, seed, candidates[0]["entity_key"], registry=reg)
    print(json.dumps(detail, ensure_ascii=False, indent=2))
    return 0


def cmd_audit_binding_coverage(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_binding_coverage(reg, category=a.category, sample_limit=a.sample_limit)
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = (s.project_root / out).resolve()
        else:
            out = out.resolve()
        build = (s.project_root / "pt_build").resolve()
        if out != build and build not in out.parents:
            raise RuntimeError("binding coverage output must remain under pt_build")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["output"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _write_read_only_audit_result(s, result: dict, raw_output: str | None) -> None:
    if not raw_output:
        return
    out = pathlib.Path(raw_output).expanduser()
    if not out.is_absolute():
        out = (s.project_root / out).resolve()
    else:
        out = out.resolve()
    build = (s.project_root / "pt_build").resolve()
    if out != build and build not in out.parents:
        raise RuntimeError("audit output must remain under pt_build")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["output"] = str(out)


def cmd_audit_inx_writer_corpus(a):
    s, reg, cert, resolver = make_context(a)
    prefixes = a.prefix or ["char/npc", "char/monster"]
    result = audit_inx_writer_corpus(s.client_root, prefixes=prefixes, sample_limit=a.sample_limit)
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "EMPTY"} else 3


def cmd_audit_smb_writer_corpus(a):
    s, reg, cert, resolver = make_context(a)
    prefixes = a.prefix or ["char/npc", "char/monster"]
    result = audit_smb_writer_corpus(s.project_root, s.client_root, prefixes=prefixes, sample_limit=a.sample_limit)
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "EMPTY"} else 3


def cmd_audit_inx_writer_edit_corpus(a):
    s, reg, cert, resolver = make_context(a)
    prefixes = a.prefix or ["char/npc", "char/monster"]
    result = audit_inx_writer_edit_corpus(s.client_root, prefixes=prefixes, sample_limit=a.sample_limit)
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "EMPTY"} else 3


def cmd_audit_smb_writer_edit_corpus(a):
    s, reg, cert, resolver = make_context(a)
    prefixes = a.prefix or ["char/npc", "char/monster"]
    result = audit_smb_writer_edit_corpus(s.project_root, s.client_root, prefixes=prefixes, sample_limit=a.sample_limit)
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "EMPTY"} else 3


def cmd_audit_motion_writer_semantic_edit_corpus(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_motion_writer_semantic_edit_corpus(
        s.project_root, reg, resolver,
        pair_limit=int(a.pair_limit or 0), sample_limit=int(a.sample_limit),
    )
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "EMPTY"} else 3


def cmd_audit_object_local_writer_corpus(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_object_local_writer_corpus(s.project_root, reg, resolver, sample_limit=int(a.sample_limit))
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "EMPTY"} else 3


def cmd_audit_rigid_model_info_contexts(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_rigid_model_info_contexts(reg, category=a.category, sample_limit=int(a.sample_limit))
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_audit_development_readiness(a):
    s, reg, cert, resolver = make_context(a)
    prefixes = a.prefix or ["char/npc", "char/monster"]
    result = audit_development_readiness(
        s.project_root, s.client_root, reg, resolver, _profile_registry(s),
        deep=bool(a.deep), prefixes=prefixes,
        animation_pair_limit=int(a.animation_pair_limit or 0),
        sample_limit=int(a.sample_limit),
    )
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_deploy_prepare(a):
    s, reg, cert, resolver = make_context(a)
    result = prepare_deployment_transaction(s.project_root, resolver, reg, a.target, a.artifact)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PREPARED", "PREPARED_BLOCKED"} else 3


def cmd_deploy_verify(a):
    result = verify_deployment_transaction(a.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_simulate(a):
    result = simulate_deployment_transaction(a.manifest, inject_failure=a.inject_failure)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_state(a):
    result = classify_client_transaction_state(a.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_restore_plan(a):
    result = plan_restore_transaction(a.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"RESTORE_CANDIDATE_BLOCKED", "BLOCKED"} else 3


def cmd_deploy_workspace_prepare(a):
    s, reg, cert, resolver = make_context(a)
    result = prepare_workspace_bundle(
        s, resolver, reg, a.target, include_model=not bool(a.textures_only),
        auto_rigid_weight_repair=not bool(getattr(a, "no_auto_rigid_weight_repair", False)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"READY", "NO_CHANGES"} else 3


def cmd_deploy_workspace_apply(a):
    result = apply_workspace_bundle_transaction(a.manifest, confirm=a.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_workspace_verify(a):
    result = verify_workspace_bundle_transaction(a.manifest, allow_managed=bool(a.allow_managed))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_workspace_state(a):
    result = workspace_bundle_status(a.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_workspace_restore(a):
    result = restore_workspace_bundle_transaction(a.manifest, confirm=a.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_workspace_history(a):
    s, reg, cert, resolver = make_context(a)
    # Resolve first so aliases/ids are normalized to the canonical primary path.
    asset = reg.resolve(a.target)
    result = bundle_history(s.project_root, asset.primary_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_deploy_workspace_publish(a):
    s, reg, cert, resolver = make_context(a)
    result = publish_workspace_bundle(
        s, resolver, reg, a.target, confirm=a.confirm, include_model=not bool(a.textures_only),
        allow_partial_lod=bool(getattr(a, "allow_partial_lod", False)),
        auto_rigid_weight_repair=not bool(getattr(a, "no_auto_rigid_weight_repair", False)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_workspace_check(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    result = check_latest_workspace_bundle(s.project_root, asset.primary_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_workspace_restore_latest(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    result = restore_latest_workspace_bundle(s.project_root, asset.primary_path, confirm=a.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_workspace_restore_model_latest(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    result = restore_latest_workspace_model(s.project_root, asset.primary_path, confirm=a.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3



def cmd_asset_authoring(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    source = None
    if asset.kind == "SMD_MODEL_062":
        source = resolver.resolve(asset.primary_path, required=True)
    result = authoring_plan(asset, source)
    workspace = blender_edit_root(s.project_root, "generic_import", asset.primary_path)
    manifest = workspace / "authoring_manifest.json"
    result["workspace"] = str(workspace)
    result["workspace_manifest"] = str(manifest) if manifest.is_file() else None
    result["workspace_verification"] = verify_workspace_manifest(manifest) if manifest.is_file() else {
        "status": "ABSENT", "errors": ["AUTHORING_WORKSPACE_NOT_IMPORTED_OR_LEGACY_UNVERIFIED"],
        "build_authorized": False, "client_write_authorized": False, "client_modified": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_audit_model062_authoring(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_model062_authoring(
        reg, resolver, category=a.category, physical_only=not bool(a.include_missing),
        sample_limit=int(a.sample_limit),
    )
    _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3

def cmd_families(a):
    s, reg, cert, resolver = make_context(a)
    table([(fam, n) for fam, n in reg.family_counts()], ["FAMILY", "ASSETS"])
    return 0


def cmd_asset_inspect(a):
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    resolver = ClientResolver(s.client_root)
    cert = CertificationRegistry(s.certifications_dir)
    reg = AssetRegistry(s.inventory, s.pairing, resolver=resolver)
    try:
        asset = reg.resolve(a.target)
    except KeyError:
        # Supporting files (INX/SMB/etc.) and client files absent from the
        # historical semantic inventory are still valid catalog entries.
        # Inspect them as files instead of incorrectly reporting "asset not found".
        rel = norm_path(a.target)
        record = reg.record_for_path(rel)
        try:
            physical = resolver.resolve(rel, required=True)
        except Exception as exc:
            raise KeyError(f"asset/file not found: {a.target}; physical={type(exc).__name__}: {exc}") from exc
        st = physical.stat()
        data = {
            "format": "PT_ASSET_FILE_INSPECT_V1",
            "registry_asset": False,
            "inventory_record_present": bool(record),
            "primary_path": rel,
            "basename": pathlib.PurePosixPath(rel).name,
            "extension": pathlib.PurePosixPath(rel).suffix.lower(),
            "size": int(st.st_size),
            "kind": (record or {}).get("kind") or "PHYSICAL_FILE",
            "family": (record or {}).get("compatibility_family") or "UNREGISTERED_FILE",
            "category": (record or {}).get("category_hint") or "UNKNOWN",
            "compatibility_tier": (record or {}).get("compatibility_tier") or "",
            "issues": list((record or {}).get("issues") or []),
            "certifications": [],
        }
        if a.physical:
            data["physical_path"] = str(physical)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    data = asset.to_dict()
    data["registry_asset"] = True
    data["inventory_record_present"] = True
    data["certifications"] = list(cert.latest(asset.asset_id).values())
    try:
        data["character_profiles"] = _profile_registry(s).match_asset(asset.primary_path)
    except Exception:
        data["character_profiles"] = []
    data["physical_dependency_status"] = reg.physical_dependency_status(asset)
    if a.physical:
        if not s.client_root.is_dir():
            data["physical_error"] = f"client root missing: {s.client_root}"
        else:
            try:
                data["physical_path"] = str(resolver.resolve(asset.primary_path))
                data["config_physical"] = [str(resolver.resolve(x["inx"])) for x in asset.configs]
                data["motion_physical"] = [str(resolver.resolve(x)) for x in asset.motions]
                data["binding_skeleton_physical"] = str(resolver.resolve(asset.binding_skeleton_smb)) if asset.binding_skeleton_smb else ""
                data["binding_root_model_physical"] = [str(resolver.resolve(x)) for x in asset.binding_root_models]
            except Exception as exc:
                data["physical_error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def choose_next(reg, cert, resolver, category=None):
    priority = {"MOB_MONSTER": 0, "NPC": 1, "CHARACTER": 2, "WEAPON_ITEM": 3, "EFFECT": 4, "MAP_STAGE": 5, "UNKNOWN": 9}
    candidates = reg.list_assets(category=category, visual_only=True)
    candidates.sort(key=lambda x: (priority.get(x.category, 8), x.family, x.primary_path.lower()))
    for asset in candidates:
        physical = resolver.resolve(asset.primary_path, required=False)
        current_sha = sha256_file(physical) if physical is not None else None
        if cert.latest_result(asset.asset_id, "VISUAL_ASSET", "HUMAN_VISUAL", source_sha256=current_sha) != "PASS":
            return asset
    raise RuntimeError("no pending visual-compatible assets match the selection")


def cmd_audit_texlink_semantics(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_multilayer_semantics_corpus(
        reg.records, resolver, bundle=a.bundle, per_profile=a.per_profile
    )
    if a.output:
        op = pathlib.Path(a.output).expanduser()
        if not op.is_absolute():
            op = s.project_root / op
        op = op.resolve(); op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(op)
    shown = dict(result)
    shown.pop("rows", None)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(
        "multilayer_texlink_semantics_audit=" + result["status"] +
        f" audited={result['physical_files_audited']}/{result['candidate_files_expected']}" +
        f" profiles={result['semantic_profile_file_counts']}" +
        f" htexture_fail={result['htexture_mapping_fail_files']}" +
        f" stage_index_fail={result['stage_index_fail_files']}" +
        f" semantic_fail={result['source_semantics_fail_files']}" +
        f" complete_candidate={str(result['two_stage_semantics_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_asset_texlink_semantics(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    if asset.kind != "SMD_MODEL_062":
        raise RuntimeError(f"TexLink semantics require SMD Model 0.62, got {asset.kind}")
    src = resolver.resolve(asset.primary_path)
    result = compact_semantics(parse_multilayer_semantics(src))
    result["asset_id"] = asset.asset_id
    result["asset"] = asset.primary_path
    result["category"] = asset.category
    result["mode"] = asset.physique_mode
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_validate_texlinks(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.multilayer_texlink(asset, lod=a.lod)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["visual_multilayer_asset"] != "FAIL" else 3


def cmd_validate_texlink_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.multilayer_texlink_roundtrip(asset, lod=a.lod, uv_delta=a.uv_delta)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["multilayer_texlink_roundtrip"] == "PASS" else 3


def cmd_validate_stage072_preview(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} KIND={asset.kind}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.stage072_preview(asset)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("stage072_blender_transport") == "PASS" else 3


def cmd_view_stage072(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} KIND={asset.kind}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.stage072_preview(asset)
    if result.get("stage072_blender_transport") != "PASS":
        return 3
    blend = pathlib.Path(result["preview_blend"]).resolve()
    helper = s.project_root / "pt_asset_tool/blender/open_stage072_preview.py"
    print(f"VIEW_STAGE072 blend={blend}")
    print("VIEW_POLICY=NORMALIZED_FLOATING_ORIGIN_PROXY source_coordinates_unchanged=true source_lights_preserved=true material_preview=true")
    proc = subprocess.run(s.blender_command() + [str(blend), "--python", str(helper)])
    return int(proc.returncode or 0)


def cmd_paint_stage072(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} KIND={asset.kind}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.stage072_preview(asset)
    if result.get("stage072_blender_transport") != "PASS":
        return 3
    blend = pathlib.Path(result["preview_blend"]).resolve()
    helper = s.project_root / "pt_asset_tool/blender/open_stage072_paint.py"
    paint_root = blender_edit_root(
        s.project_root, "stage072_texture_paint", asset.primary_path, f"stage_{int(a.stage)}"
    )
    if getattr(a, "reset", False) and paint_root.exists():
        shutil.rmtree(paint_root)
    workspace_info = write_workspace_info(
        paint_root, workflow="stage072_texture_paint", logical=asset.primary_path,
        extra={"stage": int(a.stage), "source_preview_blend": str(blend)},
    )
    print(f"PAINT_STAGE072 source_preview_blend={blend}")
    print(f"PAINT_ROOT={paint_root}")
    print(f"PAINT_WORKSPACE_INFO={workspace_info}")
    print(
        "PAINT_POLICY=NORMALIZED_FLOATING_ORIGIN_PRIVATE_TEXTURE_COPIES "
        f"stage={int(a.stage)} source_uv_unchanged=true client_modified=false"
    )
    proc = subprocess.run(
        s.blender_command() + [
            str(blend), "--python", str(helper), "--",
            "--paint-root", str(paint_root), "--stage", str(int(a.stage)),
        ]
    )
    return int(proc.returncode or 0)


def cmd_validate_stage072_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} KIND={asset.kind}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.stage072_uv_roundtrip(asset, uv_delta=a.uv_delta)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("stage072_uv_roundtrip") == "PASS" else 3


def cmd_validate_stage072_geometry_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} KIND={asset.kind}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.stage072_geometry_roundtrip(asset, delta_world=a.delta_world)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("stage072_geometry_roundtrip") == "PASS" else 3


def cmd_validate_structural(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.structural(asset)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_validate_visual(a):
    s, reg, cert, resolver = make_context(a)
    asset = choose_next(reg, cert, resolver, a.category) if a.target.lower() == "next" else reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.visual_geometry(asset, lod=a.lod)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["visual_asset"] != "FAIL" else 3


def cmd_validate_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.static_roundtrip(asset, witness_strength=a.witness_strength)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["static_roundtrip"] != "FAIL" else 3



def cmd_asset_object_local(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    if asset.family != "SMD_MODEL_062_STATIC":
        raise RuntimeError(
            f"object-local inspection applies to static Model0.62 objects; got {asset.family}. "
            "For rigid Physique models use `asset inspect`, `bindings`, `asset motions`, or animation tools instead."
        )
    src = resolver.resolve(asset.primary_path)
    result = compact_report(parse_object_local_smd(src, strict_v1=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_asset_texlinks(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    if asset.kind != "SMD_MODEL_062":
        raise RuntimeError(f"TexLink inspection requires SMD Model 0.62, got {asset.kind}")
    src = resolver.resolve(asset.primary_path)
    result = parse_texlink_file(src)
    result["asset_id"] = asset.asset_id
    result["asset"] = asset.primary_path
    result["category"] = asset.category
    result["mode"] = asset.physique_mode
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_validate_object_local(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE=STATIC_OBJECT_LOCAL")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.object_local_animation(asset, fps=a.fps)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["visual_object_local_asset"] != "FAIL" else 3

def _normalize_head_tier(value: str) -> tuple[str, int | None]:
    raw=(value or "auto").strip().lower().replace("_","-")
    aliases={
        "auto":("AUTO",None),
        "base":("PROMOTION_0",0), "0":("PROMOTION_0",0), "promotion-0":("PROMOTION_0",0), "promotion0":("PROMOTION_0",0),
        "a":("PROMOTION_1",1), "1":("PROMOTION_1",1), "promotion-1":("PROMOTION_1",1), "promotion1":("PROMOTION_1",1),
        "b":("PROMOTION_2",2), "2":("PROMOTION_2",2), "promotion-2":("PROMOTION_2",2), "promotion2":("PROMOTION_2",2),
        "c":("PROMOTION_3",3), "3":("PROMOTION_3",3), "promotion-3":("PROMOTION_3",3), "promotion3":("PROMOTION_3",3),
        "d":("PROMOTION_4",4), "4":("PROMOTION_4",4), "promotion-4":("PROMOTION_4",4), "promotion4":("PROMOTION_4",4),
        "t":("SPECIAL_T",None), "special-t":("SPECIAL_T",None), "specialt":("SPECIAL_T",None),
    }
    if raw not in aliases:
        raise RuntimeError("invalid --head-tier; use auto/base/0, a/1, b/2, c/3, d/4, or t")
    return aliases[raw]


def cmd_asset_heads(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    rows = reg.head_candidates(asset)
    table([(x["asset_id"], x["asset"], x.get("appearance_key") or "-", x.get("tier_name") or "-", x.get("inf") or x.get("descriptor_kind") or "-", ",".join(x["lods"]), x.get("object_count") or "") for x in rows[:a.limit]],
          ["ID","HEAD_ASSET","APPEARANCE","TIER","FACE_DESCRIPTOR","LODS","OBJECTS"])
    promo=sum(1 for x in rows if x.get("tier_kind")=="PROMOTION")
    special=sum(1 for x in rows if x.get("tier_kind")=="SPECIAL")
    print(f"\nhead_candidates={len(rows)} promotion_variants={promo} special_variants={special} body={asset.primary_path} root_smb={asset.binding_skeleton_smb}")
    return 0


def cmd_asset_head_tiers(a):
    s, reg, cert, resolver = make_context(a)
    body=reg.resolve(a.target)
    head=reg.resolve(a.head)
    rows=reg.head_tier_variants(body,head)
    table([(x["asset_id"],x["asset"],x.get("tier_name") or "-",x.get("tier_code") or "-",x.get("descriptor_kind") or "-",x.get("object_count") or "",x.get("total_vertices") or "") for x in rows],
          ["ID","HEAD_ASSET","TIER","CODE","DESCRIPTOR","OBJECTS","VERTICES"])
    info=reg._asset_head_variant_info(head) or {}
    print(f"\nappearance={info.get('appearance_key') or '-'} variants={len(rows)} root_smb={body.binding_skeleton_smb}")
    return 0


def _resolve_head_option(reg, asset, value: str, tier_value: str = "auto"):
    value=(value or "auto").strip()
    tier_name,tier_index=_normalize_head_tier(tier_value)
    # RC6.18: automatic head assembly is a playable-character feature.
    # Monsters/NPCs/effects are treated as monolithic unless the caller
    # explicitly supplies a verified head asset. This prevents Hopy-like
    # single-model assets from receiving irrelevant head/tier prompts.
    if value.lower() == "auto" and str(getattr(asset, "category", "")).upper() != "CHARACTER":
        return None, None
    if value.lower() in {"none","off","no"}:
        if tier_name != "AUTO":
            raise RuntimeError("--head-tier cannot be used with --head none")
        return None, None
    if reg.is_head_part(asset):
        if value.lower() == "auto" and tier_name == "AUTO":
            return None, None
        raise RuntimeError("target is already a head/face part; --head/--head-tier are only valid for a body/armor asset")
    candidates=reg.head_candidates(asset)
    if not candidates:
        return None, None

    if value.lower() == "auto":
        pool=candidates
        if tier_name == "AUTO":
            base=[x for x in pool if x.get("tier_index") == 0]
            pool=base or pool
        elif tier_name == "SPECIAL_T":
            pool=[x for x in pool if x.get("tier_name") == "SPECIAL_T"]
        else:
            pool=[x for x in pool if x.get("tier_index") == tier_index]
        if not pool:
            raise RuntimeError(f"no verified head candidate for requested tier={tier_name}")
        row=pool[0]
        return reg.resolve(row["asset"]), row

    requested=reg.resolve(value)
    valid={x["asset_id"]:x for x in candidates}
    if requested.asset_id not in valid:
        raise RuntimeError(f"requested head is not a verified face part for this root: {requested.primary_path}; candidates={len(candidates)}")
    row=valid[requested.asset_id]
    if tier_name == "AUTO":
        return requested,row

    variants=reg.head_tier_variants(asset,requested)
    if tier_name == "SPECIAL_T":
        matches=[x for x in variants if x.get("tier_name") == "SPECIAL_T"]
    else:
        matches=[x for x in variants if x.get("tier_index") == tier_index]
    if len(matches) != 1:
        raise RuntimeError(f"requested appearance has no unique {tier_name} variant: head={requested.primary_path} matches={len(matches)}")
    chosen=matches[0]
    return reg.resolve(chosen["asset"]),chosen


def _resolved_motion_context(asset, resolver):
    from .motion_core import resolve_asset_motion_context
    ctx = resolve_asset_motion_context(asset, resolver, require_physical=True)
    return ctx["config"], ctx["inx_path"], ctx["smb_path"]


def cmd_asset_motions(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    from .motion_core import load_motion_system, enrich_motions
    _cfg, inx, smb_path = _resolved_motion_context(asset, resolver)
    evaluator, inxcore = load_motion_system(s.project_root)
    smb = evaluator.parse_smb(smb_path); parsed = inxcore.parse_inx(inx); motions = enrich_motions(parsed, smb)
    rows=[]
    for m in motions:
        if not m.get("active_container"): continue
        rows.append((m["index"],m["state_name"],m["start"],m["end"],m["repeat"],m["motion_frame"]))
    table(rows,["INDEX","STATE","START","END","REPEAT","TMFRAME"])
    print(f"\nactive={len(rows)} motion_count={parsed['motion_count']}")
    return 0

def _resolve_inx_source(a, s, resolver):
    rel = norm_path(a.target)
    if pathlib.PurePosixPath(rel).suffix.lower() != ".inx":
        raise RuntimeError("INX motion writer/roundtrip currently requires an explicit .inx client-relative path")
    return rel, resolver.resolve(rel, required=True)


def _pt_build_output(s, raw, *, default_rel):
    build_root = (s.project_root / "pt_build").resolve()
    if raw:
        out = pathlib.Path(raw).expanduser()
        if not out.is_absolute():
            out = (s.project_root / out).resolve()
        else:
            out = out.resolve()
    else:
        out = (build_root / default_rel).resolve()
    if out != build_root and build_root not in out.parents:
        raise RuntimeError(f"output must stay under pt_build: {out}")
    return out


def _resolve_smb_source(a, s, resolver):
    rel = norm_path(a.target)
    if pathlib.PurePosixPath(rel).suffix.lower() != ".smb":
        raise RuntimeError("SMB writer/roundtrip currently requires an explicit .smb client-relative path")
    return rel, resolver.resolve(rel, required=True)


def cmd_validate_smb_track_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    rel, source = _resolve_smb_source(a, s, resolver)
    result = validate_track_roundtrip(s.project_root, source)
    result["logical_path"] = rel
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_write_smb_key(a):
    s, reg, cert, resolver = make_context(a)
    rel, source = _resolve_smb_source(a, s, resolver)
    default_rel = pathlib.Path("smb_key_edits") / asset_workspace_name(rel) / f"{pathlib.PurePosixPath(rel).stem}__{a.track}__{a.key_index}.smb"
    out = _pt_build_output(s, a.output, default_rel=default_rel)
    result = patch_key(
        s.project_root, source, out, bone=a.bone, track=a.track, key_index=a.key_index,
        x=a.x, y=a.y, z=a.z, w=a.w,
    )
    result["logical_path"] = rel
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_validate_inx_roundtrip(a):
    s, reg, cert, resolver = make_context(a)
    rel, source = _resolve_inx_source(a, s, resolver)
    result = validate_noop_roundtrip(source)
    result["logical_path"] = rel
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_write_inx_motion(a):
    s, reg, cert, resolver = make_context(a)
    rel, source = _resolve_inx_source(a, s, resolver)
    selector = str(a.motion)
    suffix = selector.strip().replace("/", "_").replace("\\", "_") or "motion"
    default_rel = pathlib.Path("inx_motion_edits") / asset_workspace_name(rel) / f"{pathlib.PurePosixPath(rel).stem}__{suffix}.inx"
    out = _pt_build_output(s, a.output, default_rel=default_rel)
    result = patch_motion(
        source, out, motion=selector, start=a.start, end=a.end, repeat=a.repeat,
        key_code=a.key_code, motion_frame=a.motion_frame,
    )
    result["logical_path"] = rel
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_write_object_local_key_candidate(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    if asset.family != "SMD_MODEL_062_STATIC":
        raise RuntimeError(f"object-local key candidate requires static Model0.62; got {asset.family}")
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True))
    default_rel = pathlib.Path("object_local_key_edits") / asset_workspace_name(asset.primary_path) / (
        f"{pathlib.PurePosixPath(asset.primary_path).stem}__obj{int(a.object_index)}__{a.channel}__{int(a.key_index)}.smd"
    )
    out = _pt_build_output(s, a.output, default_rel=default_rel)
    if str(a.channel).lower() == "rot" and a.w is None:
        raise ValueError("--w is required for --channel rot")
    values = [a.x, a.y, a.z] if str(a.channel).lower() != "rot" else [a.x, a.y, a.z, a.w]
    result = patch_existing_object_local_key(
        source, out, object_index=int(a.object_index), channel=a.channel, key_index=int(a.key_index),
        values=values,
    )
    prov = write_build_provenance(
        out, asset=asset, source=source, build_mode="CANDIDATE_OBJECT_LOCAL_EXISTING_KEY",
        adapter="pt_asset_tool.object_local_writer", build_status=result.get("status", "FAIL"),
        production_authorized=False, evidence={
            "writer_format": result.get("format"), "channel": result.get("channel"),
            "object_index": result.get("object_index"), "key_index": result.get("key_index"),
        },
    )
    result["build_provenance"] = str(prov)
    result["logical_path"] = asset.primary_path
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_validate_animation(a):
    s, reg, cert, resolver = make_context(a)
    asset = choose_next_animation(reg, cert, resolver, a.category) if a.target.lower() == "next" else reg.resolve(a.target)
    head, head_variant = _resolve_head_option(reg, asset, a.head, getattr(a, "head_tier", "auto"))
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    if head is not None:
        tier_label=(head_variant or {}).get("tier_name") or "UNCLASSIFIED"
        appearance=(head_variant or {}).get("appearance_key") or "-"
        print(f"ASSEMBLED_HEAD={head.asset_id} {head.primary_path} MODE=INDEPENDENT_RIG HEAD_TIER={tier_label} APPEARANCE={appearance}")
    elif str(a.head or "auto").lower() == "auto" and asset.category == "CHARACTER":
        try:
            candidate_count=len(reg.head_candidates(asset))
        except Exception:
            candidate_count=0
        print(f"ASSEMBLED_HEAD=NONE AUTO_HEAD_CANDIDATES={candidate_count}; use `python3 pt_asset.py asset heads {asset.primary_path}` to inspect verified candidates")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.visual_animation(asset, lod=a.lod, motion=a.motion, load_actions=a.load_actions, fps=a.fps, head_asset=head, head_variant=head_variant)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["visual_animation_asset"] != "FAIL" else 3

def choose_next_animation(reg, cert, resolver, category=None):
    candidates=[x for x in reg.list_assets(category=category, visual_only=True) if x.visual_mode=="RIGID" and x.animation_binding_ready]
    candidates.sort(key=lambda x:(x.category,x.primary_path.lower()))
    for asset in candidates:
        physical = resolver.resolve(asset.primary_path, required=False)
        current_sha = sha256_file(physical) if physical is not None else None
        if cert.latest_result(asset.asset_id,"VISUAL_ANIMATION_ASSET","HUMAN_VISUAL", source_sha256=current_sha) != "PASS":
            return asset
    raise RuntimeError("no pending animation-compatible assets match the selection")


def cmd_audit_animation_source(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    _cfg, inx, smb_path = _resolved_motion_context(asset, resolver)
    result = audit_animation_source_regression(s.project_root, inx, smb_path, mode=a.mode)
    result["asset_id"] = asset.asset_id
    result["asset"] = asset.primary_path
    result["binding_mode"] = asset.binding_mode
    result["binding_source"] = asset.binding_source
    if a.output:
        out = _pt_build_output(s, a.output, default_rel=pathlib.Path("animation_source") / f"{asset_workspace_name(asset.primary_path)}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_animation_corpus(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_animation_corpus(
        s.project_root, reg, resolver,
        category=a.category, mode=a.mode, pair_limit=a.pair_limit, sample_limit=a.sample_limit,
    )
    if a.output:
        out = _pt_build_output(s, a.output, default_rel=pathlib.Path("animation_source") / "corpus.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_diagnose_animation(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.animation_diagnostic(asset, lod=a.lod, motion=a.motion, load_actions=a.load_actions, fps=a.fps)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def cmd_diagnose_motion_source(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    from .motion_core import audit_motion_source
    _cfg, inx, smb_path = _resolved_motion_context(asset, resolver)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    result = audit_motion_source(s.project_root, inx, smb_path, selector=a.motion)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def cmd_diagnose_motion_segment(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    from .motion_core import audit_motion_segments
    _cfg, inx, smb_path = _resolved_motion_context(asset, resolver)
    print(f"ASSET={asset.asset_id} {asset.primary_path}")
    print(f"FAMILY={asset.family} CATEGORY={asset.category} MODE={asset.visual_mode}")
    result = audit_motion_segments(s.project_root, inx, smb_path, selector=a.motion)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _load_root_binding_cache(path: pathlib.Path) -> dict:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("format", "PT_ROOT_SKELETON_BINDINGS_V7")
                data.setdefault("entries", {})
                return data
        except Exception:
            pass
    return {"format": "PT_ROOT_SKELETON_BINDINGS_V7", "entries": {}}


def _atomic_json(path: pathlib.Path, data: dict):
    from .utils import atomic_write_json
    atomic_write_json(path, data)


def _signature_for_passing_smb(s, smb_path: pathlib.Path) -> dict:
    """Best-effort skeleton identity for an SMB that already passed the structural gate.

    The crucial ordering is gate-first: parser coverage over unrelated SMB dialects
    must never shrink the structural candidate universe. A PASS that cannot be
    signature-parsed is kept as unresolved evidence and forces fail-closed.
    """
    from .motion_core import load_smb_evaluator, smb_skeleton_signature
    evaluator = load_smb_evaluator(s.project_root)
    smb = evaluator.parse_smb(smb_path)
    return smb_skeleton_signature(smb)


def _error_bucket(exc: Exception) -> str:
    msg=f"{type(exc).__name__}: {exc}"
    low=msg.casefold()
    if 'eof' in low or 'unexpected end' in low or 'unpack' in low:
        return 'TRUNCATED_OR_LAYOUT'
    if 'magic' in low or 'header' in low or 'signature' in low:
        return 'HEADER_OR_DIALECT'
    if 'decode' in low or 'unicode' in low:
        return 'TEXT_DECODE'
    if 'assert' in low:
        return 'PARSER_ASSERTION'
    return type(exc).__name__



def _physique_subset_resolution(a, s, reg, resolver, asset, src, tested, work):
    """Resolve full-skeleton ambiguity by the mesh's actually weighted bone closure.

    The legacy Blender importer is used once to recover the rigid Physique bone
    indices as vertex-group names. Every structural PASS SMB is then compared
    only on those bones + their ancestors. This does not use directory/name
    similarity as binding evidence.
    """
    from .motion_core import load_smb_evaluator, smb_physique_closure_signature
    from .texture_overlay import prepare_texture_overlay
    from .utils import low_path, norm_path

    pass_rows=[r for r in tested.values() if isinstance(r,dict) and r.get('result')=='PASS' and r.get('signature_status')=='PASS' and r.get('path')]
    if not pass_rows:
        return {'status':'PHYSIQUE_PROBE_NO_PASSES','source':'PHYSIQUE_SUBSET'}

    asset_dir=str(pathlib.PurePosixPath(asset.primary_path).parent).casefold()
    pass_rows.sort(key=lambda r:(0 if str(pathlib.PurePosixPath(r['path']).parent).casefold()==asset_dir else 1, str(r['path']).casefold()))
    representative=pass_rows[0]['path']
    rep_smb_path=resolver.resolve(representative)

    cfg=asset.configs[0] if asset.configs else None
    if not cfg or not cfg.get('inx'):
        return {'status':'PHYSIQUE_PROBE_NO_INX','source':'PHYSIQUE_SUBSET'}
    inx=resolver.resolve(cfg['inx'])
    groups=cfg.get('lod_groups') or {}
    lod=next((x for x in ('default','high','low') if groups.get(x)), None)
    if not lod:
        return {'status':'PHYSIQUE_PROBE_NO_LOD','source':'PHYSIQUE_SUBSET'}

    probe=work/'physique_subset_v1'
    probe.mkdir(parents=True,exist_ok=True)
    overlay, texture_report=prepare_texture_overlay(asset=asset,resolver=resolver,root=s.project_root,work=probe)
    blend=probe/'physique_probe.blend'
    import_log=probe/'01_import.log'
    cmd=s.blender_command()+[
        '--background','--python-exit-code','1',
        '--python',str(s.project_root/'pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py'),'--',
        '--smd',str(src),'--skeleton',str(rep_smb_path),'--model-info',str(inx),
        '--lod',lod,'--client-root',str(overlay),'--out',str(blend),'--no-pack',
    ]
    proc=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    import_log.write_text(proc.stdout or '',encoding='utf-8')
    if proc.returncode or not blend.is_file():
        return {'status':'PHYSIQUE_PROBE_IMPORT_FAIL','source':'PHYSIQUE_SUBSET','representative_smb':representative,'log':str(import_log),'returncode':proc.returncode}

    usage_report=probe/'physique_usage.json'
    usage_log=probe/'02_usage.log'
    cmd=s.blender_command()+[
        '--background',str(blend),'--python-exit-code','1',
        '--python',str(s.project_root/'pt_asset_tool/blender/extract_physique_usage.py'),'--',
        '--report',str(usage_report),
    ]
    proc=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    usage_log.write_text(proc.stdout or '',encoding='utf-8')
    if proc.returncode or not usage_report.is_file():
        return {'status':'PHYSIQUE_USAGE_EXTRACT_FAIL','source':'PHYSIQUE_SUBSET','representative_smb':representative,'log':str(usage_log),'returncode':proc.returncode}

    usage=json.loads(usage_report.read_text(encoding='utf-8'))
    weighted=usage.get('weighted_groups') or []
    evaluator=load_smb_evaluator(s.project_root)
    rep_smb=evaluator.parse_smb(rep_smb_path)
    rep_names=[str(b.get('name') or '') for b in (rep_smb.get('bones') or [])]
    name_to_indices=collections.defaultdict(list)
    for i,n in enumerate(rep_names):
        if n: name_to_indices[n.casefold()].append(i)

    used_indices=[]; unmapped=[]; ambiguous_names=[]
    for row in weighted:
        name=str(row.get('name') or '')
        hits=name_to_indices.get(name.casefold(),[])
        if len(hits)==1:
            used_indices.append(hits[0])
        elif not hits:
            unmapped.append(name)
        else:
            ambiguous_names.append({'name':name,'indices':hits})
    used_indices=sorted(set(used_indices))
    if unmapped or ambiguous_names or not used_indices:
        return {'status':'PHYSIQUE_USAGE_UNMAPPED','source':'PHYSIQUE_SUBSET','representative_smb':representative,
                'weighted_groups':[r.get('name') for r in weighted],'used_bone_indices':used_indices,
                'unmapped_groups':unmapped,'ambiguous_group_names':ambiguous_names,'usage_report':str(usage_report)}

    subset_groups={}; topology_groups=collections.defaultdict(list); subset_failures=[]
    for row in pass_rows:
        rel=row['path']; physical=resolver.resolve(rel,required=False)
        if physical is None:
            subset_failures.append({'path':rel,'error':'MISSING'})
            continue
        try:
            smb=evaluator.parse_smb(physical)
            info=smb_physique_closure_signature(smb,used_indices)
            sig=info['physique_subset_signature']
            topo_sig=info['physique_topology_signature']
            topology_groups[topo_sig].append(rel)
            g=subset_groups.setdefault(sig,{'physique_subset_signature':sig,'physique_topology_signature':topo_sig,
                'used_bone_indices':info['used_bone_indices'],'used_bone_names':info['used_bone_names'],
                'closure_indices':info['closure_indices'],'closure_bone_names':info['closure_bone_names'],
                'closure_bone_count':info['closure_bone_count'],'smb_aliases':[]})
            g['smb_aliases'].append(rel)
        except Exception as exc:
            subset_failures.append({'path':rel,'error':f'{type(exc).__name__}: {exc}'})

    for g in subset_groups.values():
        g['smb_aliases']=sorted(set(g['smb_aliases']),key=str.lower)
    ordered=sorted(subset_groups.values(),key=lambda g:(-len(g['smb_aliases']),g['smb_aliases'][0].lower()))
    groups_report=probe/'physique_subset_groups.json'
    groups_report.write_text(json.dumps({'format':'PT_PHYSIQUE_SUBSET_GROUPS_V1','groups':ordered},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    base={'source':'PHYSIQUE_SUBSET','representative_probe_smb':representative,'lod':lod,
          'weighted_group_count':len(weighted),'weighted_groups':[r.get('name') for r in weighted],
          'used_bone_indices':used_indices,'physique_usage_report':str(usage_report),
          'physique_probe_blend':str(blend),'physique_subset_count':len(ordered),'physique_topology_subset_count':len(topology_groups),
          'subset_parse_failures':subset_failures,'physique_subset_groups_report':str(groups_report),
          'physique_subset_group_sample':ordered[:12]}
    if subset_failures:
        return {'status':'PHYSIQUE_SUBSET_INCOMPLETE',**base}
    if len(ordered)==1:
        winner=ordered[0]
        aliases=winner['smb_aliases']
        # Representative is deterministic, but animation remains contextual.
        preferred=sorted(aliases,key=lambda rel:(0 if str(pathlib.PurePosixPath(rel).parent).casefold()==asset_dir else 1,rel.casefold()))[0]
        return {'status':'PHYSIQUE_SUBSET_EQUIVALENT','representative_smb':preferred,
                'equivalent_smb_count':len(aliases),'equivalent_smb_alias_sample':aliases[:20],
                'physique_subset_signature':winner['physique_subset_signature'],
                'closure_bone_names':winner['closure_bone_names'],'closure_bone_count':winner['closure_bone_count'],**base}
    return {'status':'AMBIGUOUS_PHYSIQUE_SUBSET',**base}



def _extract_config_binary_refs(blob: bytes) -> dict:
    """Extract explicit asset references from opaque/fixed-field INX bytes.

    This is intentionally evidence-only: only literal .smb/.smd/.inx tokens that
    physically occur in the config are considered.  Both ASCII and UTF-16LE
    printable strings are inspected because Summit-era assets use both styles in
    adjacent tooling/data.
    """
    import re
    texts=[]
    seen=set()
    for m in re.finditer(rb'[\x20-\x7e]{4,}', blob):
        try: t=m.group(0).decode('ascii','strict').strip()
        except Exception: continue
        if t and t not in seen:
            seen.add(t); texts.append(t)
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){4,}', blob):
        try: t=m.group(0).decode('utf-16le','strict').strip()
        except Exception: continue
        if t and t not in seen:
            seen.add(t); texts.append(t)

    # First capture path-shaped refs, then bare basenames.  Keep original case;
    # resolver/canonical inventory will decide physical casing later.
    path_re=re.compile(r'(?i)([A-Za-z0-9_.() +@#\-]+(?:[\\/][A-Za-z0-9_.() +@#\-]+)+\.(?:smb|smd|inx))')
    base_re=re.compile(r'(?i)([A-Za-z0-9_.()@# +\-]+\.(?:smb|smd|inx))')
    tokens=[]; t_seen=set()
    for text in texts:
        hits=path_re.findall(text)
        if not hits:
            hits=base_re.findall(text)
        for raw in hits:
            tok=str(raw).strip(' \t\r\n\"\'').replace('\\','/')
            if not tok:
                continue
            k=tok.casefold()
            if k not in t_seen:
                t_seen.add(k); tokens.append(tok)
    return {'strings':texts,'tokens':tokens}


def _resolve_literal_config_ref(token: str, inx_rel: str, reg, resolver) -> dict:
    """Resolve one literal config token without fuzzy basename guessing.

    Accepted evidence paths are: exact canonical path, exact path relative to the
    INX directory, or a basename that is unique in the canonical inventory.  A
    basename collision is reported as ambiguous rather than guessed.
    """
    from .utils import low_path, norm_path
    tok=norm_path(token).strip()
    # If a saved absolute path leaked into the INX, keep only the client-relative
    # suffix when one of the known top-level asset folders is present.
    low=tok.casefold()
    for anchor in ('char/','effect/','image/','startimage/','field/','map/'):
        pos=low.find(anchor)
        if pos >= 0:
            tok=tok[pos:]; low=tok.casefold(); break
    candidates=[]
    def add(rel):
        rel=norm_path(rel)
        if rel and rel not in candidates:
            candidates.append(rel)
    add(tok)
    if '/' not in tok:
        add(str(pathlib.PurePosixPath(inx_rel).parent / tok))
    elif not low.startswith(('char/','effect/','image/','startimage/','field/','map/')):
        add(str(pathlib.PurePosixPath(inx_rel).parent / tok))

    exact=[]
    for rel in candidates:
        if resolver.resolve(rel, required=False) is not None:
            rec=reg.by_rel.get(low_path(rel))
            exact.append(norm_path(rec.get('relative_path')) if rec else rel)
    exact=sorted(set(exact), key=str.lower)
    if len(exact)==1:
        return {'token':token,'status':'RESOLVED','path':exact[0],'method':'EXACT_OR_INX_RELATIVE'}
    if len(exact)>1:
        return {'token':token,'status':'AMBIGUOUS','candidates':exact,'method':'EXACT_OR_INX_RELATIVE'}

    base=pathlib.PurePosixPath(tok).name.casefold()
    bybase=[]
    for rec in reg.records:
        if str(rec.get('basename') or pathlib.PurePosixPath(norm_path(rec.get('relative_path'))).name).casefold()==base:
            bybase.append(norm_path(rec.get('relative_path')))
    bybase=sorted(set(bybase), key=str.lower)
    if len(bybase)==1:
        return {'token':token,'status':'RESOLVED','path':bybase[0],'method':'UNIQUE_CANONICAL_BASENAME'}
    return {'token':token,'status':'AMBIGUOUS' if bybase else 'UNRESOLVED','candidates':bybase[:25],
            'candidate_count':len(bybase),'method':'CANONICAL_BASENAME'}


def _config_context_resolution(a, s, reg, resolver, asset, tested, work):
    """Use explicit config references to discriminate full-skeleton ambiguity.

    V0.3.5 proved that raw Physique indices cannot be compared positionally
    across unrelated SMBs.  This resolver therefore treats the SMD/INX assembly
    graph as the deciding evidence.  It never promotes filename similarity or a
    bone-index/name interpretation into a binding.
    """
    from .motion_core import load_smb_evaluator
    from .utils import low_path, norm_path

    audit_dir=work/'config_context_v1'; audit_dir.mkdir(parents=True,exist_ok=True)
    rows=[]; resolved_smb=set(); resolved_smd=set(); ambiguous=[]; unresolved=[]
    for cfg in asset.configs:
        inx_rel=norm_path(cfg.get('inx'))
        if not inx_rel:
            continue
        p=resolver.resolve(inx_rel, required=False)
        if p is None:
            rows.append({'inx':inx_rel,'status':'MISSING'})
            continue
        raw=_extract_config_binary_refs(p.read_bytes())
        rrefs=[]
        for token in raw['tokens']:
            rr=_resolve_literal_config_ref(token,inx_rel,reg,resolver); rrefs.append(rr)
            if rr.get('status')=='RESOLVED':
                rel=norm_path(rr.get('path')); ext=pathlib.PurePosixPath(rel).suffix.casefold()
                if ext=='.smb': resolved_smb.add(rel)
                elif ext=='.smd': resolved_smd.add(rel)
            elif rr.get('status')=='AMBIGUOUS': ambiguous.append(rr)
            else: unresolved.append(rr)
        rows.append({'inx':inx_rel,'status':'OK','literal_tokens':raw['tokens'],
                     'resolved_refs':rrefs,'printable_string_count':len(raw['strings']),
                     'printable_string_sample':raw['strings'][:40]})

    # A literal SMD root reference is strong evidence.  If that referenced asset
    # already has a proven skeleton binding, inherit only the skeleton SMB (not
    # its animation context).  Otherwise use only direct pairing rows for that
    # exact referenced model; no stem/directory inference is permitted.
    root_models=set(resolved_smd)
    derived_smb=set()
    for smd_rel in sorted(resolved_smd,key=str.lower):
        try:
            ra=reg.resolve(smd_rel)
        except Exception:
            ra=None
        if ra is not None and ra.rigid_binding_ready and ra.binding_skeleton_smb:
            derived_smb.add(norm_path(ra.binding_skeleton_smb))
            continue
        for prow in reg.pairing:
            if low_path(prow.get('model_smd')) != low_path(smd_rel):
                continue
            m=norm_path(prow.get('motion_smb'))
            if m:
                derived_smb.add(m)
    evidence_smb=sorted(resolved_smb | derived_smb,key=str.lower)

    signed=[]; rejected=[]
    for rel in evidence_smb:
        prow=tested.get(low_path(rel))
        if not isinstance(prow,dict) or prow.get('result')!='PASS':
            rejected.append({'path':rel,'reason':'NOT_A_STRUCTURAL_PASS'})
            continue
        if prow.get('signature_status')!='PASS' or not prow.get('skeleton_signature'):
            rejected.append({'path':rel,'reason':'PASS_WITHOUT_SKELETON_SIGNATURE'})
            continue
        signed.append({'path':rel,'skeleton_signature':prow['skeleton_signature'],
                       'topology_signature':prow.get('topology_signature'),
                       'bone_count':prow.get('bone_count')})

    groups=collections.defaultdict(list)
    for row in signed:
        groups[row['skeleton_signature']].append(row['path'])
    signed_groups=[{'skeleton_signature':sig,'smb_aliases':sorted(paths,key=str.lower)}
                   for sig,paths in sorted(groups.items(),key=lambda kv:kv[0])]

    # Keep the old Physique probe only as a diagnostic map.  It is explicitly
    # non-binding because numeric indices have candidate-local semantics.
    physique_diag={}
    usage_report=work/'physique_subset_v1'/'physique_usage.json'
    if usage_report.is_file():
        try:
            usage=json.loads(usage_report.read_text(encoding='utf-8'))
            weighted=usage.get('weighted_groups') or []
            probe_group_indices=sorted({int(i) for r in weighted for i in (r.get('group_indices') or [])})
            physique_diag={'probe_weighted_group_count':len(weighted),
                           'probe_weighted_group_names':[r.get('name') for r in weighted],
                           'probe_vertex_group_indices':probe_group_indices,
                           'index_semantics':'DIAGNOSTIC_ONLY_CANDIDATE_LOCAL'}
            # Candidate-local map is useful for reverse engineering, but never
            # participates in the automatic binding decision.
            same_dir=str(pathlib.PurePosixPath(asset.primary_path).parent).casefold()
            evaluator=load_smb_evaluator(s.project_root)
            cmap=[]
            for prow in sorted((r for r in tested.values() if isinstance(r,dict) and r.get('result')=='PASS' and r.get('path')),
                               key=lambda r:str(r.get('path')).casefold()):
                rel=norm_path(prow.get('path'))
                if str(pathlib.PurePosixPath(rel).parent).casefold()!=same_dir:
                    continue
                try:
                    smb=evaluator.parse_smb(resolver.resolve(rel))
                    bones=smb.get('bones') or []
                    names=[]; missing=[]
                    for i in probe_group_indices:
                        if 0 <= i < len(bones): names.append(str(bones[i].get('name') or ''))
                        else: missing.append(i)
                    cmap.append({'path':rel,'bone_count':len(bones),'names_at_probe_group_indices':names,
                                 'missing_probe_group_indices':missing})
                except Exception as exc:
                    cmap.append({'path':rel,'error':f'{type(exc).__name__}: {exc}'})
            map_path=audit_dir/'candidate_local_physique_index_map.json'
            map_path.write_text(json.dumps({'format':'PT_CANDIDATE_LOCAL_PHYSIQUE_INDEX_MAP_V1','rows':cmap},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            physique_diag['candidate_local_map_report']=str(map_path)
            physique_diag['candidate_local_map_sample']=cmap[:20]
        except Exception as exc:
            physique_diag={'physique_diagnostic_error':f'{type(exc).__name__}: {exc}'}

    report={'format':'PT_CONFIG_CONTEXT_AUDIT_V1','asset':asset.primary_path,'configs':rows,
            'explicit_smd_refs':sorted(resolved_smd,key=str.lower),
            'explicit_smb_refs':sorted(resolved_smb,key=str.lower),
            'derived_smb_refs_from_explicit_smd':sorted(derived_smb,key=str.lower),
            'evidence_smb_refs':evidence_smb,'ambiguous_literal_refs':ambiguous,
            'unresolved_literal_refs':unresolved,'signed_evidence_smbs':signed,
            'signed_evidence_skeleton_groups':signed_groups,'rejected_evidence_smbs':rejected,
            **physique_diag}
    rp=audit_dir/'config_context_audit.json'
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    base={'source':'CONFIG_CONTEXT','config_context_report':str(rp),
          'explicit_smd_refs':report['explicit_smd_refs'],'explicit_smb_refs':report['explicit_smb_refs'],
          'derived_smb_refs_from_explicit_smd':report['derived_smb_refs_from_explicit_smd'],
          'evidence_smb_refs':evidence_smb,'signed_evidence_skeleton_groups':signed_groups,
          'rejected_evidence_smbs':rejected,'ambiguous_literal_ref_count':len(ambiguous),
          'unresolved_literal_ref_count':len(unresolved),**physique_diag}

    if rejected:
        return {'status':'CONFIG_REFERENCE_EVIDENCE_INCOMPLETE',**base}
    if len(signed_groups)==1 and evidence_smb:
        winner=signed_groups[0]
        aliases=winner['smb_aliases']
        preferred=aliases[0]
        return {**base,'status':'CONFIG_EXPLICIT_SKELETON_UNIQUE','source':'CONFIG_EXPLICIT_REF_UNIQUE',
                'representative_smb':preferred,'motion_smb':preferred,
                'skeleton_signature':winner['skeleton_signature'],
                'equivalent_smb_count':len(aliases),'equivalent_smb_alias_sample':aliases[:20],
                'root_models':sorted(root_models,key=str.lower),
                'root_inxs':sorted({norm_path(c.get('inx')) for c in asset.configs if c.get('inx')},key=str.lower),
                'animation_context':'UNRESOLVED'}
    if len(signed_groups)>1:
        return {**base,'status':'AMBIGUOUS_CONFIG_EXPLICIT_SKELETON','source':'CONFIG_EXPLICIT_REF_AMBIGUOUS'}
    if evidence_smb:
        return {'status':'CONFIG_REFERENCE_NO_SIGNED_PASS','source':'CONFIG_CONTEXT',**base}
    return {'status':'CONFIG_CONTEXT_UNRESOLVED','source':'CONFIG_CONTEXT',**base}


def _assembly_graph_resolution(a, s, reg, resolver, asset, tested, work):
    """Resolve a config-only skeleton through explicit pairing graph connectivity.

    Binding edges are deliberately narrow:
      INX --(pairing row)--> resolved SMD
      SMD --(same exact canonical model path)--> every INX that references it

    Motion SMBs are evidence only when attached to a row inside the connected
    component and already proven by the structural scan/signature pass.  LOD
    object-name overlap is reported for reverse engineering but never used as a
    binding edge.
    """
    from .utils import low_path, norm_path, truth
    import re

    audit_dir=work/'assembly_graph_v1'; audit_dir.mkdir(parents=True,exist_ok=True)
    inx_rows=collections.defaultdict(list)
    model_inxs=collections.defaultdict(set)
    slot_inxs=collections.defaultdict(set)
    for row in reg.pairing:
        inx=norm_path(row.get('inx')) if row.get('inx') else ''
        model=norm_path(row.get('model_smd')) if row.get('model_smd') else ''
        if inx:
            inx_rows[low_path(inx)].append(row)
        if inx and model and truth(row.get('model_resolved')):
            model_inxs[low_path(model)].add(inx)
        if inx:
            for col in ('high','default','low'):
                for token in re.split(r'[,;|]', str(row.get(col) or '')):
                    token=token.strip()
                    if token:
                        slot_inxs[token.casefold()].add(inx)

    target_inxs=sorted({norm_path(c.get('inx')) for c in asset.configs if c.get('inx')},key=str.lower)
    q=collections.deque(target_inxs)
    seen_inxs={low_path(x) for x in target_inxs}
    seen_models=set()
    bridge_edges=[]
    component_rows=[]
    while q:
        inx=q.popleft(); rows=inx_rows.get(low_path(inx),[])
        component_rows.extend(rows)
        for row in rows:
            model=norm_path(row.get('model_smd')) if row.get('model_smd') else ''
            if not model or not truth(row.get('model_resolved')):
                continue
            mk=low_path(model)
            if mk not in seen_models:
                seen_models.add(mk)
            peers=sorted(model_inxs.get(mk) or [],key=str.lower)
            for peer in peers:
                pk=low_path(peer)
                bridge_edges.append({'model_smd':model,'from_inx':inx,'to_inx':peer})
                if pk not in seen_inxs:
                    seen_inxs.add(pk); q.append(peer)

    component_inxs=sorted({norm_path(r.get('inx')) for r in component_rows if r.get('inx')},key=str.lower)
    component_models=sorted({norm_path(r.get('model_smd')) for r in component_rows if r.get('model_smd') and truth(r.get('model_resolved'))},key=str.lower)
    component_motions=sorted({norm_path(r.get('motion_smb')) for r in component_rows if r.get('motion_smb')},key=str.lower)

    signed=[]; rejected=[]
    for rel in component_motions:
        prow=tested.get(low_path(rel))
        if not isinstance(prow,dict) or prow.get('result')!='PASS':
            rejected.append({'path':rel,'reason':'COMPONENT_MOTION_NOT_STRUCTURAL_PASS'})
            continue
        if prow.get('signature_status')!='PASS' or not prow.get('skeleton_signature'):
            rejected.append({'path':rel,'reason':'COMPONENT_MOTION_WITHOUT_SKELETON_SIGNATURE'})
            continue
        signed.append({'path':rel,'skeleton_signature':prow['skeleton_signature'],
                       'topology_signature':prow.get('topology_signature'),
                       'bone_count':prow.get('bone_count')})
    groups=collections.defaultdict(list)
    for row in signed:
        groups[row['skeleton_signature']].append(row['path'])
    signed_groups=[{'skeleton_signature':sig,'smb_aliases':sorted(paths,key=str.lower)}
                   for sig,paths in sorted(groups.items(),key=lambda kv:kv[0])]

    # Diagnostic-only LOD slot overlaps. Exact slot equality can be common across
    # unrelated art, so it must never create graph connectivity.
    target_slots=set()
    for inx in target_inxs:
        for row in inx_rows.get(low_path(inx),[]):
            for col in ('high','default','low'):
                for token in re.split(r'[,;|]', str(row.get(col) or '')):
                    token=token.strip()
                    if token: target_slots.add(token)
    slot_overlap=collections.defaultdict(set)
    for token in sorted(target_slots,key=str.lower):
        for inx in slot_inxs.get(token.casefold()) or []:
            if low_path(inx) not in {low_path(x) for x in target_inxs}:
                slot_overlap[inx].add(token)
    slot_sample=[{'inx':inx,'shared_slots':sorted(vals,key=str.lower)}
                 for inx,vals in sorted(slot_overlap.items(),key=lambda kv:kv[0].lower())[:50]]

    root_models=set(); root_inxs=set()
    winner_aliases=set(signed_groups[0]['smb_aliases']) if len(signed_groups)==1 else set()
    winner_keys={low_path(x) for x in winner_aliases}
    if winner_keys:
        for row in component_rows:
            motion=norm_path(row.get('motion_smb')) if row.get('motion_smb') else ''
            if low_path(motion) not in winner_keys:
                continue
            model=norm_path(row.get('model_smd')) if row.get('model_smd') else ''
            inx=norm_path(row.get('inx')) if row.get('inx') else ''
            if model and truth(row.get('model_resolved')): root_models.add(model)
            if inx: root_inxs.add(inx)

    report={'format':'PT_ASSEMBLY_GRAPH_AUDIT_V1','asset':asset.primary_path,
            'binding_edges':'PAIRING_EXACT_MODEL_ONLY','target_inxs':target_inxs,
            'component_inxs':component_inxs,'component_models':component_models,
            'component_motion_smbs':component_motions,'bridge_edges':bridge_edges,
            'signed_component_motions':signed,'signed_skeleton_groups':signed_groups,
            'rejected_component_motions':rejected,
            'lod_slot_overlap_semantics':'DIAGNOSTIC_ONLY_NOT_BINDING',
            'target_lod_slots':sorted(target_slots,key=str.lower),
            'lod_slot_overlap_sample':slot_sample}
    rp=audit_dir/'assembly_graph_audit.json'
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    base={'source':'ASSEMBLY_GRAPH','assembly_graph_report':str(rp),
          'assembly_binding_edges':'PAIRING_EXACT_MODEL_ONLY',
          'assembly_target_inxs':target_inxs,
          'assembly_component_inx_count':len(component_inxs),
          'assembly_component_model_count':len(component_models),
          'assembly_component_motion_count':len(component_motions),
          'assembly_component_inx_sample':component_inxs[:30],
          'assembly_component_model_sample':component_models[:30],
          'assembly_component_motion_smbs':component_motions,
          'assembly_signed_skeleton_groups':signed_groups,
          'assembly_rejected_component_motions':rejected,
          'lod_slot_overlap_semantics':'DIAGNOSTIC_ONLY_NOT_BINDING',
          'lod_slot_overlap_peer_count':len(slot_overlap),
          'lod_slot_overlap_sample':slot_sample[:20]}
    if rejected:
        return {'status':'ASSEMBLY_COMPONENT_EVIDENCE_INCOMPLETE',**base}
    if len(signed_groups)==1 and component_motions:
        winner=signed_groups[0]; aliases=winner['smb_aliases']; preferred=aliases[0]
        return {**base,'status':'ASSEMBLY_COMPONENT_SKELETON_UNIQUE','source':'ASSEMBLY_GRAPH_UNIQUE',
                'representative_smb':preferred,'motion_smb':preferred,
                'skeleton_signature':winner['skeleton_signature'],
                'equivalent_smb_count':len(aliases),'equivalent_smb_alias_sample':aliases[:20],
                'root_models':sorted(root_models,key=str.lower),'root_inxs':sorted(root_inxs,key=str.lower),
                'animation_context':'UNRESOLVED'}
    if len(signed_groups)>1:
        return {**base,'status':'AMBIGUOUS_ASSEMBLY_COMPONENT_SKELETON','source':'ASSEMBLY_GRAPH_AMBIGUOUS'}
    return {**base,'status':'ASSEMBLY_COMPONENT_UNRESOLVED','source':'ASSEMBLY_GRAPH'}

def cmd_binding_discover(a, s, reg, resolver):
    from .utils import low_path, norm_path, sha256_file, stable_id, utc_now
    asset = reg.resolve(a.discover)
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"binding discovery requires rigid Physique SMD; got {asset.family}")
    if asset.binding_mode == "SELF_CONTAINED":
        raise RuntimeError("asset is already SELF_CONTAINED; discovery is only for config-only/root-bound assets")
    if asset.binding_mode == "ROOT_SKELETON_BOUND" and asset.binding_source == "INX_LINK_FILE":
        linked_configs=[{
            "source_inx":c.get("inx") or "",
            "target_inx":c.get("motion_inx") or "",
            "motion_smb":c.get("motion_smb") or "",
            "root_model_smd":c.get("root_model_smd") or "",
        } for c in asset.configs if c.get("motion_binding_origin") == "INX_LINK_FILE"]
        out={
            "asset_id":asset.asset_id,
            "asset":asset.primary_path,
            "status":"INX_LINK_FILE_BOUND",
            "source":"INX_LINK_FILE",
            "binding_skeleton_smb":asset.binding_skeleton_smb,
            "binding_root_models":asset.binding_root_models,
            "linked_configs":linked_configs,
            "rigid_binding_ready":asset.rigid_binding_ready,
            "animation_binding_ready":asset.animation_binding_ready,
            "binding_notes":asset.binding_notes,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("binding_discovery=INX_LINK_FILE_BOUND (runtime LinkFile/link_code/file_code verified)")
        return 0

    gate = s.project_root / "pt_character_structural_gate_v2.py"
    if not gate.is_file():
        raise FileNotFoundError(gate)
    src = resolver.resolve(asset.primary_path)
    source_sha = sha256_file(src)
    work = s.work_dir / asset.asset_id / "root_skeleton_discovery"
    reports = work / "reports_v7"
    reports.mkdir(parents=True, exist_ok=True)
    state_path = work / "probe_state_v7.json"
    state = {"format":"PT_ROOT_SKELETON_PROBE_STATE_V7", "asset":asset.primary_path,
             "source_sha256":source_sha, "tested":{}, "passes":[]}
    if not a.no_resume and state_path.is_file():
        try:
            old=json.loads(state_path.read_text(encoding="utf-8"))
            if old.get("source_sha256") == source_sha and old.get("format") == "PT_ROOT_SKELETON_PROBE_STATE_V7":
                state=old
        except Exception:
            pass

    # V0.3.7 migration: reuse V0.3.6 complete structural/signature state.
    migrated_from_v6 = False
    if not state.get("tested") and not a.no_resume:
        v6_path = work / "probe_state_v6.json"
        if v6_path.is_file():
            try:
                v6=json.loads(v6_path.read_text(encoding="utf-8"))
                if v6.get("source_sha256") == source_sha and v6.get("format") == "PT_ROOT_SKELETON_PROBE_STATE_V6":
                    state["tested"]=v6.get("tested") or {}
                    migrated_from_v6=True
                    print(f"reused_v6_scan={len(state['tested'])}; assembly_graph_will_be_audited")
            except Exception as exc:
                print(f"v6_state_reuse=SKIP ({type(exc).__name__})")

    # V0.3.6 migration: reuse the complete V0.3.5 gate/signature scan.
    # No 958-SMB rescan is needed; only config/assembly evidence is new.
    migrated_from_v5 = False
    if not state.get("tested") and not a.no_resume:
        v5_path = work / "probe_state_v5.json"
        if v5_path.is_file():
            try:
                v5=json.loads(v5_path.read_text(encoding="utf-8"))
                if v5.get("source_sha256") == source_sha and v5.get("format") == "PT_ROOT_SKELETON_PROBE_STATE_V5":
                    state["tested"]=v5.get("tested") or {}
                    migrated_from_v5=True
                    print(f"reused_v5_scan={len(state['tested'])}; config_context_will_be_audited")
            except Exception as exc:
                print(f"v5_state_reuse=SKIP ({type(exc).__name__})")
    # Older V4 can still be recovered if V5 was never produced.
    migrated_from_v4 = False
    if not state.get("tested") and not a.no_resume:
        v4_path = work / "probe_state_v4.json"
        if v4_path.is_file():
            try:
                v4=json.loads(v4_path.read_text(encoding="utf-8"))
                if v4.get("source_sha256") == source_sha and v4.get("format") == "PT_ROOT_SKELETON_PROBE_STATE_V4":
                    state["tested"]=v4.get("tested") or {}
                    migrated_from_v4=True
                    print(f"reused_v4_scan={len(state['tested'])}; config_context_will_be_audited")
            except Exception as exc:
                print(f"v4_state_reuse=SKIP ({type(exc).__name__})")
    # Older V3 can still be recovered if V4/V5 were never produced. Its broken
    # signatures are stripped and recomputed below.
    migrated_from_v3 = False
    if not state.get("tested") and not a.no_resume:
        v3_path = work / "probe_state_v3.json"
        if v3_path.is_file():
            try:
                v3=json.loads(v3_path.read_text(encoding="utf-8"))
                if v3.get("source_sha256") == source_sha and v3.get("format") == "PT_ROOT_SKELETON_PROBE_STATE_V3":
                    imported={}
                    for k,row in (v3.get("tested") or {}).items():
                        if not isinstance(row,dict):
                            continue
                        keep={x:row.get(x) for x in ("path","result","sha256","report") if row.get(x) is not None}
                        imported[k]=keep
                    state["tested"]=imported
                    migrated_from_v3=True
                    print(f"reused_v3_structural_results={len(imported)}; signatures_will_be_recomputed")
            except Exception as exc:
                print(f"v3_state_reuse=SKIP ({type(exc).__name__})")

    # IMPORTANT: this is the complete physical SMB universe. We intentionally
    # do NOT pre-parse it with the animation evaluator. Structural gate decides
    # relevance first; skeleton signature is only requested for actual PASSes.
    candidates=[]; seen=set()
    for r in reg.records:
        if str(r.get("extension") or "").lower() != ".smb":
            continue
        rel=norm_path(r.get("relative_path")); k=low_path(rel)
        if rel and k not in seen:
            seen.add(k); candidates.append(rel)
    candidates.sort(key=str.lower)
    if a.candidate_limit and a.candidate_limit > 0:
        candidates=candidates[:a.candidate_limit]

    tested=state.setdefault("tested", {})
    total=len(candidates); fresh=0

    # Repair/re-sign already-proven structural PASSes. This is deliberately
    # independent from the gate loop: a parser/signature bug must never force
    # 958 expensive structural gates to run again.
    resign_total=sum(1 for row in tested.values() if isinstance(row,dict) and row.get("result")=="PASS" and not row.get("skeleton_signature"))
    resign_done=0; resign_fail=0
    if resign_total:
        print(f"resign_structural_passes={resign_total}")
    for k,row in tested.items():
        if not isinstance(row,dict) or row.get("result") != "PASS" or row.get("skeleton_signature"):
            continue
        rel=row.get("path")
        smb=resolver.resolve(rel, required=False) if rel else None
        if smb is None:
            row.update({"signature_status":"FAIL","signature_error_bucket":"MISSING","signature_error":"SMB missing during re-sign"})
            resign_fail += 1
            continue
        try:
            info=_signature_for_passing_smb(s, smb)
            row.update({"signature_status":"PASS", **info})
            for dead in ("signature_error_bucket","signature_error"):
                row.pop(dead,None)
            resign_done += 1
        except Exception as exc:
            bucket=_error_bucket(exc); msg=f"{type(exc).__name__}: {exc}"
            row.update({"signature_status":"FAIL","signature_error_bucket":bucket,"signature_error":msg})
            resign_fail += 1
        if (resign_done + resign_fail) % 50 == 0:
            _atomic_json(state_path,state)
            print(f"resign_progress={resign_done + resign_fail}/{resign_total} ok={resign_done} fail={resign_fail}")
    if resign_total:
        _atomic_json(state_path,state)
        print(f"resign_complete={resign_done + resign_fail}/{resign_total} ok={resign_done} fail={resign_fail}")

    # Reconstruct pass groups from the per-candidate resumable state. This is
    # stronger than relying on the periodic summary: an interruption after a
    # PASS cannot silently lose its skeleton identity.
    pass_groups={}
    unsigned_passes=[]
    parse_error_counts=collections.Counter()
    parse_error_samples={}
    structural_pass_count=0
    for row in tested.values():
        if not isinstance(row, dict) or row.get("result") != "PASS":
            continue
        structural_pass_count += 1
        sig=row.get("skeleton_signature")
        if row.get("signature_status") == "PASS" and sig:
            g=pass_groups.setdefault(sig,{"skeleton_signature":sig,
                "topology_signature":row.get("topology_signature"),
                "bone_count":row.get("bone_count"),"root_bones":row.get("root_bones") or [],
                "smb_aliases":[],"reports":[]})
            if row.get("path"): g["smb_aliases"].append(row["path"])
            if row.get("report"): g["reports"].append(row["report"])
        else:
            unsigned={k:row.get(k) for k in ("path","sha256","report","signature_error_bucket","signature_error")}
            unsigned_passes.append(unsigned)
            bucket=row.get("signature_error_bucket") or "UNKNOWN"
            parse_error_counts[bucket]+=1
            if row.get("path"):
                parse_error_samples.setdefault(bucket,{"path":row.get("path"),"error":row.get("signature_error") or ""})

    for pos, rel in enumerate(candidates, 1):
        k=low_path(rel)
        if k in tested:
            continue
        smb=resolver.resolve(rel, required=False)
        if smb is None:
            tested[k]={"path":rel,"result":"MISSING"}
            continue
        rid=stable_id("smb-gate-first", rel).replace("AST-", "")
        rp=reports / f"{rid}.json"; lp=reports / f"{rid}.log"
        proc=subprocess.run(["python3", str(gate), "--smd", str(src), "--smb", str(smb), "--report", str(rp)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        lp.write_text(proc.stdout or "", encoding="utf-8")
        fresh += 1
        if proc.returncode == 0:
            structural_pass_count += 1
            file_sha=sha256_file(smb)
            base={"path":rel,"result":"PASS","sha256":file_sha,"report":str(rp)}
            try:
                info=_signature_for_passing_smb(s, smb)
                sig=info["skeleton_signature"]
                base.update({"signature_status":"PASS", **info})
                g=pass_groups.setdefault(sig,{"skeleton_signature":sig,
                    "topology_signature":info.get("topology_signature"),
                    "bone_count":info.get("bone_count"),"root_bones":info.get("root_bones") or [],
                    "smb_aliases":[],"reports":[]})
                g["smb_aliases"].append(rel); g["reports"].append(str(rp))
                print(f"PASS {rel} skeleton={sig[:12]} bones={info.get('bone_count')}")
            except Exception as exc:
                bucket=_error_bucket(exc); msg=f"{type(exc).__name__}: {exc}"
                base.update({"signature_status":"FAIL","signature_error_bucket":bucket,"signature_error":msg})
                unsigned={"path":rel,"sha256":file_sha,"report":str(rp),
                          "signature_error_bucket":bucket,"signature_error":msg}
                unsigned_passes.append(unsigned)
                parse_error_counts[bucket]+=1
                parse_error_samples.setdefault(bucket,{"path":rel,"error":msg})
                print(f"PASS-UNSIGNED {rel} parser={bucket}")
            tested[k]=base
        else:
            tested[k]={"path":rel,"result":"FAIL"}

        if fresh % 25 == 0:
            state["passes"]=[]
            for g in pass_groups.values():
                row=dict(g); row["smb_aliases"]=sorted(set(row["smb_aliases"]),key=str.lower); row["reports"]=sorted(set(row["reports"]))
                state["passes"].append(row)
            state["passes"].extend(unsigned_passes)
            _atomic_json(state_path,state)
            print(f"progress={pos}/{total} structural_passes={structural_pass_count} "
                  f"signed_skeletons={len(pass_groups)} unsigned_passes={len(unsigned_passes)}")

        # V0.3.5 needs the complete structural PASS universe before a Physique
        # subset equivalence claim can be made, so discovery no longer early-
        # stops at two full-skeleton identities.

    # Canonicalize state.
    state["passes"]=[]
    for g in sorted(pass_groups.values(), key=lambda x:(x.get("smb_aliases") or [""])[0].lower()):
        row=dict(g); row["smb_aliases"]=sorted(set(row["smb_aliases"]),key=str.lower); row["reports"]=sorted(set(row["reports"]))
        state["passes"].append(row)
    state["passes"].extend(sorted(unsigned_passes,key=lambda x:x.get("path","").lower()))
    _atomic_json(state_path,state)

    tested_count=len(tested)
    scan_complete=(tested_count >= total)
    cache_path = reg.binding_cache_path
    cache = _load_root_binding_cache(cache_path)
    entry={"asset":asset.primary_path,"source_sha256":source_sha,"updated_at":utc_now(),
           "candidate_universe":total,"tested_candidates":tested_count,"scan_complete":scan_complete,
           "structural_passes":structural_pass_count,"distinct_signed_skeletons":len(pass_groups),
           "unsigned_structural_passes":len(unsigned_passes),"probe_state":str(state_path),
           "reused_v6_scan":bool(migrated_from_v6),
           "reused_v5_scan":bool(migrated_from_v5),
           "reused_v4_scan":bool(migrated_from_v4),
           "reused_v3_structural_results":bool(migrated_from_v3),
           "resigned_structural_passes":resign_total,"resign_ok":resign_done,"resign_fail":resign_fail,
           "pass_signature_error_counts":dict(sorted(parse_error_counts.items())),
           "pass_signature_error_samples":parse_error_samples}

    if unsigned_passes:
        entry.update({"status":"PASS_SIGNATURE_INCOMPLETE",
                      "source":"GATE_FIRST_SIGNATURE_INCOMPLETE",
                      "full_skeleton_group_sample":state["passes"][:10]})
    elif len(pass_groups) >= 2 and scan_complete:
        # V0.3.5 proved that raw Physique indices are candidate-local and cannot
        # identify a root across unrelated skeletons. Use literal assembly/config
        # references as the deciding evidence instead; Physique maps are diagnostic only.
        context=_config_context_resolution(a,s,reg,resolver,asset,tested,work)
        entry.update(context)
        if context.get("status") == "CONFIG_CONTEXT_UNRESOLVED":
            assembly=_assembly_graph_resolution(a,s,reg,resolver,asset,tested,work)
            # Preserve the literal-config audit path as prior evidence while the
            # assembly graph becomes the deciding stage.
            assembly.setdefault("config_context_report", context.get("config_context_report"))
            assembly["prior_config_context_status"] = context.get("status")
            entry.update(assembly)
        entry["full_skeleton_group_sample"]=state["passes"][:10]
        entry["full_skeleton_groups"]=len(pass_groups)
    elif len(pass_groups) >= 2:
        entry.update({"status":"AMBIGUOUS_SKELETON_MATCH","source":"GATE_FIRST_SKELETON_SIGNATURE",
                      "full_skeleton_group_sample":state["passes"][:10]})
    elif len(pass_groups) == 1 and scan_complete:
        sig,winner=next(iter(pass_groups.items()))
        aliases=sorted(set(winner["smb_aliases"]), key=str.lower)
        alias_keys={low_path(x) for x in aliases}
        root_models=set(); root_inxs=set(); referenced_aliases=[]
        for row in reg.pairing:
            motion=norm_path(row.get("motion_smb"))
            if low_path(motion) not in alias_keys:
                continue
            if motion: referenced_aliases.append(motion)
            model=norm_path(row.get("model_smd")); inx=norm_path(row.get("inx"))
            if model and str(row.get("model_resolved") or "").lower() in {"1","true","yes","y"}:
                root_models.add(model)
            if inx: root_inxs.add(inx)
        canonical_motion=sorted(set(referenced_aliases),key=str.lower)[0] if referenced_aliases else aliases[0]
        entry.update({"status":"UNIQUE_SKELETON","motion_smb":canonical_motion,
                      "motion_aliases":aliases,"skeleton_signature":sig,
                      "topology_signature":winner.get("topology_signature"),"bone_count":winner.get("bone_count"),
                      "root_bones":winner.get("root_bones") or [],
                      "root_models":sorted(root_models,key=str.lower),"root_inxs":sorted(root_inxs,key=str.lower),
                      "source":"GATE_FIRST_SKELETON_UNIQUE"})
    elif scan_complete:
        entry.update({"status":"NO_MATCH","source":"GATE_FIRST_STRUCTURAL"})
    else:
        entry.update({"status":"INCOMPLETE_SCAN","source":"GATE_FIRST_STRUCTURAL",
                      "full_skeleton_group_sample":state["passes"][:10]})

    cache.setdefault("entries", {})[low_path(asset.primary_path)] = entry
    _atomic_json(cache_path, cache)
    print(json.dumps({"asset_id":asset.asset_id,"asset":asset.primary_path,**entry}, ensure_ascii=False, indent=2))
    if entry["status"] in {"UNIQUE_SKELETON","CONFIG_EXPLICIT_SKELETON_UNIQUE","ASSEMBLY_COMPONENT_SKELETON_UNIQUE"}:
        print(f"binding_discovery={entry['status']}; rerun `python3 pt_asset.py asset inspect <asset> --physical`")
        return 0
    if entry["status"] in {"AMBIGUOUS_SKELETON_MATCH","AMBIGUOUS_CONFIG_EXPLICIT_SKELETON","AMBIGUOUS_ASSEMBLY_COMPONENT_SKELETON"}:
        print(f"binding_discovery={entry['status']} (fail-closed)")
        return 4
    if entry["status"] in {"PASS_SIGNATURE_INCOMPLETE","CONFIG_REFERENCE_EVIDENCE_INCOMPLETE","ASSEMBLY_COMPONENT_EVIDENCE_INCOMPLETE"}:
        print(f"binding_discovery={entry['status']} (diagnostic evidence incomplete; fail-closed)")
        return 5
    print(f"binding_discovery={entry['status']} (fail-closed)")
    return 3

def cmd_bindings(a):
    s, reg, cert, resolver = make_context(a)
    if getattr(a, "discover", None):
        return cmd_binding_discover(a, s, reg, resolver)
    assets = [x for x in reg.assets if x.extension == ".smd" and x.family == "SMD_MODEL_062_RIGID_PHYSIQUE"]
    if a.category:
        assets = [x for x in assets if x.category.lower() == a.category.lower()]
    if a.mode:
        assets = [x for x in assets if x.binding_mode.lower() == a.mode.lower()]
    interesting = [x for x in assets if x.binding_mode in {"ROOT_SKELETON_BOUND", "CONFIG_ONLY", "AMBIGUOUS_MULTIPLE_MOTIONS"}]
    rows=[]
    for asset in interesting[:a.limit]:
        roots = ",".join(asset.binding_root_models[:3])
        if len(asset.binding_root_models) > 3:
            roots += f" (+{len(asset.binding_root_models)-3})"
        motion = asset.motions[0] if len(asset.motions) == 1 else (f"{len(asset.motions)} motions" if asset.motions else "-")
        rows.append((asset.asset_id, asset.category, asset.binding_mode, motion, roots or "-", asset.primary_path))
    table(rows, ["ID","CATEGORY","BINDING","MOTION","ROOT MODEL(S)","PATH"])
    counts = collections.Counter(x.binding_mode for x in assets)
    print("\n" + " ".join(f"{k}={v}" for k,v in sorted(counts.items())))
    print(f"shown={len(rows)} interesting={len(interesting)} rigid_assets={len(assets)}")
    print("\nBinding meaning:")
    print("  SELF_CONTAINED: the model directly names the INX/SMB context it animates with.")
    print("  ROOT_SKELETON_BOUND: the model is a component that reuses a verified root skeleton/motion context.")
    print("  CONFIG_ONLY: configuration exists but a unique root/motion relation is not proven enough for animation.")
    print("  NONE: no binding is known/required; common for non-rigid assets and support files.")
    print("Bindings describe model -> config -> skeleton/motion relationships; they are not simply attachments, although the same evidence can prove compatible modular parts such as body/head.")
    print("Use `bindings --discover ASSET` only to investigate a rigid CONFIG_ONLY asset; it writes diagnostic evidence under pt_build, never the client.")
    return 0

def cmd_view_rigid_candidate(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"rigid candidate review requires SMD_MODEL_062_RIGID_PHYSIQUE, got {asset.family}")
    result = prepare_rigid_candidate_review_workspace(s, resolver, asset, a.artifact)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if bool(getattr(a, "no_open", False)):
        return 0
    proc = subprocess.run(s.blender_command() + [str(pathlib.Path(result["review_blend"]).resolve())])
    return int(proc.returncode or 0)


def cmd_audit_rigid_authoring_certification_plan(a):
    s, reg, cert, resolver = make_context(a)
    result = build_rigid_authoring_certification_plan(
        _profile_registry(s), reg, resolver, cert, profile_id=getattr(a, "profile", None)
    )
    if getattr(a, "output", None):
        _write_read_only_audit_result(s, result, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "WARN"} else 3


def cmd_cert_rigid_candidate_review(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"rigid candidate review requires SMD_MODEL_062_RIGID_PHYSIQUE, got {asset.family}")
    review_verify = verify_rigid_candidate_review_workspace(s, resolver, asset, a.artifact)
    if review_verify.get("status") != "PASS":
        raise RuntimeError(f"rigid candidate review workspace failed: {review_verify.get('errors')}")
    verified = dict(review_verify.get("artifact_verification") or {})
    evidence = dict(verified.get("evidence") or {})
    selected_context = dict(verified.get("selected_context") or {})
    basis = dict(selected_context.get("selection_basis") or {})
    source_path = resolver.resolve(asset.primary_path, required=True)
    artifact_sha = verified.get("artifact_sha256")

    def record_pair(object_name, lod, context_key, *, edit_observed, unknown_bones):
        meta = {
            "rigid_candidate_context_key": context_key,
            "stress_profile_review": bool(verified.get("stress_profile")),
            "stress_review_context_key": verified.get("context_key") if verified.get("stress_profile") else None,
            "asset": asset.primary_path,
            "artifact": verified.get("artifact"),
            "artifact_sha256": artifact_sha,
            "provenance": verified.get("provenance"),
            "object": object_name,
            "lod": lod,
            "profile_id": basis.get("profile_id"),
            "profile_version": basis.get("profile_version"),
            "model_info_inx": ((selected_context.get("model_info_inx") or {}).get("logical")),
            "skeleton_smb": ((selected_context.get("skeleton_smb") or {}).get("logical")),
            "lod_groups_signature": selected_context.get("lod_groups_signature"),
            "edit_observed": bool(edit_observed),
            "non_target_changed": list(evidence.get("non_target_changed") or []),
            "unknown_physique_bones": list(unknown_bones or []),
            "verification_errors": list(evidence.get("verification_errors") or []),
            "review_manifest": review_verify.get("review_manifest"),
            "review_blend": ((review_verify.get("review") or {}).get("review_blend")),
            "review_blend_sha256": ((review_verify.get("review") or {}).get("review_blend_sha256")),
            "automatic_evidence_verified": True,
            "production_authorized": False,
            "client_write_authorized": False,
        }
        auto = cert.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test=AUTOMATIC_TEST, layer=AUTOMATIC_LAYER, result="PASS",
            source_sha256=sha256_file(source_path), artifact_sha256=artifact_sha,
            notes="Verified controlled rigid saved-Blender candidate edit; still candidate-only.", metadata=meta,
        )
        human_meta = dict(meta); human_meta["manual_review"] = True
        human = cert.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test=AUTOMATIC_TEST, layer=HUMAN_LAYER, result=a.result,
            source_sha256=sha256_file(source_path), artifact_sha256=artifact_sha,
            notes=a.notes or "", metadata=human_meta,
        )
        return auto, human

    if bool(verified.get("stress_profile")):
        objects = list(verified.get("candidate_objects") or [])
        lods = dict(verified.get("stress_object_lods") or {})
        edit_map = dict(evidence.get("edit_observed_by_object") or {})
        unknown_map = dict(evidence.get("unknown_physique_bones_by_object") or {})
        rows = []
        for object_name in objects:
            lod = str(lods.get(object_name) or "")
            if lod not in {"high", "default", "low"}:
                raise RuntimeError(f"stress candidate missing LOD identity for object {object_name}")
            context_for_key = dict(selected_context)
            context_for_key["lod"] = lod
            context_for_key["selected_lod_nodes"] = list((selected_context.get("lod_groups") or {}).get(lod) or [])
            context_key = rigid_candidate_context_key(asset.primary_path, context_for_key, object_name)
            auto, human = record_pair(
                object_name, lod, context_key,
                edit_observed=bool(edit_map.get(object_name)),
                unknown_bones=list(unknown_map.get(object_name) or []),
            )
            rows.append({"object": object_name, "lod": lod, "context_key": context_key, "automatic": auto, "human": human})
        shown = {
            "format": "PT_RIGID_PROFILE_STRESS_CANDIDATE_REVIEW_V1",
            "status": "PASS",
            "artifact_verification": verified,
            "review_workspace_verification": review_verify,
            "reviewed_context_count": len(rows),
            "reviewed_contexts": rows,
            "context_pass": a.result == "PASS" and len(rows) == len(objects),
            "runtime_authorized": False, "production_authorized": False,
            "client_write_authorized": False, "client_modified": False,
        }
    else:
        context_key = str(verified.get("context_key") or rigid_candidate_context_key(asset.primary_path, selected_context, verified.get("candidate_object") or ""))
        auto, human = record_pair(
            verified.get("candidate_object"), selected_context.get("lod"), context_key,
            edit_observed=bool(evidence.get("edit_observed")),
            unknown_bones=list(evidence.get("unknown_physique_bones") or []),
        )
        shown = {
            "format": "PT_RIGID_SAVED_BLENDER_CANDIDATE_REVIEW_V1",
            "status": "PASS", "artifact_verification": verified,
            "review_workspace_verification": review_verify,
            "automatic_certification": auto, "human_certification": human,
            "context_pass": a.result == "PASS",
            "runtime_authorized": False, "production_authorized": False,
            "client_write_authorized": False, "client_modified": False,
        }
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0

def cmd_cert_list(a):
    s, reg, cert, resolver = make_context(a)
    rows = cert.records()
    if a.asset:
        asset = reg.resolve(a.asset)
        rows = [x for x in rows if x.get("asset_id") == asset.asset_id]
    if a.latest:
        latest = {}
        for r in rows:
            latest[(r.get("asset_id"), r.get("test"), r.get("layer"))] = r
        rows = list(latest.values())
    rows = rows[-a.limit:]
    table([(r.get("timestamp",""), r.get("asset_id",""), r.get("test",""), r.get("layer",""), r.get("result",""), r.get("asset_path","")) for r in rows], ["TIME", "ID", "TEST", "LAYER", "RESULT", "PATH"])
    return 0


def cmd_cert_record(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    src = resolver.resolve(asset.primary_path, required=False) if s.client_root.is_dir() else None
    source_sha = None
    if src and src.is_file():
        from .utils import sha256_file
        source_sha = sha256_file(src)
    row = cert.add(
        asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
        test=a.test, layer=a.layer, result=a.result, source_sha256=source_sha, notes=a.notes or "",
        metadata={"manual_record": True},
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0



def cmd_audit_release_1_coverage(a):
    # Registry-only audit: Release 1 coverage is derived from the frozen
    # inventory/pairing and must remain usable even when the physical client is
    # not mounted on the machine running this diagnostic.
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    reg = AssetRegistry(s.inventory, s.pairing)
    result = build_release_1_coverage(reg)
    if getattr(a, "output", None):
        out = pathlib.Path(a.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0




def cmd_validate_environment_auto(a):
    s, reg, cert, resolver = make_context(a)
    result = run_environment_validation(
        s, reg, resolver,
        blender_timeout_seconds=float(getattr(a, "blender_timeout", 60.0)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3

def cmd_validate_server_environment_auto(a):
    s, reg, cert, resolver = make_context(a)
    result = run_server_environment_validation(s, server_root=getattr(a, "server_root", None))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_server_inventory(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise RuntimeError("server root is not configured; use --server-root or PT_SERVER_ROOT")
    def progress(msg):
        print(f"[server-inventory] {msg}", flush=True)
    result = audit_server_inventory(
        s.project_root, s.server_root,
        progress_every=int(getattr(a, "progress_every", 10000)),
        sample_limit=int(getattr(a, "sample_limit", 12)),
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_server_bundles(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise RuntimeError("server root is not configured; use --server-root or PT_SERVER_ROOT")
    def progress(msg):
        print(f"[server-bundles] {msg}", flush=True)
    result = audit_server_entity_bundles(
        s.project_root, s.server_root, s.client_root,
        sample_limit=int(getattr(a, "sample_limit", 40)),
        progress_every=int(getattr(a, "progress_every", 250)),
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_server_fields(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise RuntimeError("server root is not configured; use --server-root or PT_SERVER_ROOT")
    def progress(msg):
        print(f"[server-fields] {msg}", flush=True)
    result = audit_server_field_bundles(
        s.project_root, s.server_root,
        sample_limit=int(getattr(a, "sample_limit", 50)),
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_server_items(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise RuntimeError("server root is not configured; use --server-root or PT_SERVER_ROOT")
    def progress(msg):
        print(f"[server-items] {msg}", flush=True)
    result = audit_server_item_bundles(
        s.project_root, s.server_root,
        sample_limit=int(getattr(a, "sample_limit", 50)),
        progress_every=int(getattr(a, "progress_every", 250)),
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3





def cmd_legacy_management_summary(a):
    print(json.dumps(legacy_management_summary(), ensure_ascii=False, indent=2))
    return 0


def cmd_legacy_management_verify(a):
    result = verify_management_root(pathlib.Path(a.management_root))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("mismatch_count", 0) == 0 else 3


def cmd_legacy_management_item_code(a):
    classification = classify_item_code(str(a.code))
    runtime = lookup_item_runtime(str(a.code))
    result = {"format": "PT_LEGACY_MANAGEMENT_ITEM_CODE_V2", **classification, "runtime_item_contract": runtime}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if classification.get("status") != "UNCLASSIFIED" or runtime.get("status") == "SOURCE_VERIFIED" else 3


def cmd_audit_legacy_management(a):
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    def progress(msg):
        print(f"[legacy-management] {msg}", flush=True)
    result = audit_legacy_management(
        s.project_root,
        server_root=s.server_root,
        client_root=s.client_root,
        management_root=pathlib.Path(a.management_root).expanduser() if getattr(a, "management_root", None) else None,
        tutorial_root=pathlib.Path(a.tutorial_root).expanduser() if getattr(a, "tutorial_root", None) else None,
        sample_limit=int(getattr(a, "sample_limit", 80)),
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_legacy_authoring_capabilities(a):
    print(json.dumps(authoring_capabilities(), ensure_ascii=False, indent=2))
    return 0


def _legacy_authoring_context(a):
    s = Settings.discover(getattr(a, "root", None), getattr(a, "client_root", None), getattr(a, "server_root", None))
    if s.server_root is None or not pathlib.Path(s.server_root).is_dir():
        raise ValueError("SERVER_ROOT_REQUIRED")
    return s


def cmd_legacy_authoring_inspect(a):
    s = _legacy_authoring_context(a)
    result = inspect_authoring(s.project_root, s.server_root, s.client_root, str(a.kind), str(a.path))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_legacy_authoring_stage(a):
    s = _legacy_authoring_context(a)
    spec = json.loads(pathlib.Path(a.spec).expanduser().read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("LEGACY_AUTHORING_SPEC_MUST_BE_OBJECT")
    result = stage_authoring(s.project_root, s.server_root, s.client_root, spec)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_legacy_authoring_publish(a):
    s = _legacy_authoring_context(a)
    manifest = pathlib.Path(a.manifest).expanduser().resolve() if a.manifest else latest_bundle_manifest(s.project_root)
    if manifest is None:
        raise FileNotFoundError("ASSET_BUNDLE_MANIFEST_NOT_FOUND")
    result = publish_authoring(s.project_root, s.client_root, s.server_root, manifest, confirm=str(a.confirm))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_legacy_authoring_restore(a):
    s = _legacy_authoring_context(a)
    manifest = pathlib.Path(a.manifest).expanduser().resolve() if a.manifest else latest_bundle_manifest(s.project_root)
    if manifest is None:
        raise FileNotFoundError("ASSET_BUNDLE_MANIFEST_NOT_FOUND")
    result = restore_authoring(s.project_root, s.client_root, s.server_root, manifest, confirm=str(a.confirm))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def cmd_contracts_registry_list(a):
    result = registry_summary(
        query=str(getattr(a, "query", "") or ""),
        capability=str(getattr(a, "capability", "") or ""),
        implementation=str(getattr(a, "implementation", "") or ""),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_contracts_registry_show(a):
    contract = get_contract(str(a.contract_id)).public()
    result = {
        "format": "PT_ASSET_CONTRACT_DETAIL_V1",
        "status": "PASS",
        "contract": contract,
        "schema": schema_for_contract(str(a.contract_id)),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_asset_compiler_capabilities(a):
    print(json.dumps(compiler_capabilities(), ensure_ascii=False, indent=2))
    return 0


def cmd_asset_compiler_plan(a):
    s, reg, cert, resolver = make_context(a)
    result = plan_compiler_input(pathlib.Path(a.recipe), client_root=s.client_root, server_root=s.server_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "READY" else 3


def cmd_asset_compiler_build(a):
    s, reg, cert, resolver = make_context(a)
    result = compile_compiler_input(
        s.project_root, pathlib.Path(a.recipe), client_root=s.client_root, server_root=s.server_root
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _asset_bundle_manifest_arg(s, value):
    if value:
        return pathlib.Path(value).expanduser().resolve()
    manifest = latest_bundle_manifest(s.project_root)
    if manifest is None:
        raise FileNotFoundError("ASSET_BUNDLE_MANIFEST_NOT_FOUND")
    return manifest


def cmd_asset_compiler_status(a):
    s, reg, cert, resolver = make_context(a)
    result = asset_bundle_deploy_status(s.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_asset_compiler_publish(a):
    s, reg, cert, resolver = make_context(a)
    manifest = _asset_bundle_manifest_arg(s, getattr(a, "manifest", None))
    result = publish_asset_bundle(
        s.project_root, s.client_root, s.server_root, manifest, confirm=str(a.confirm)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_asset_compiler_restore(a):
    s, reg, cert, resolver = make_context(a)
    manifest = _asset_bundle_manifest_arg(s, getattr(a, "manifest", None))
    result = restore_asset_bundle(
        s.project_root, s.client_root, s.server_root, manifest, confirm=str(a.confirm)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_audit_client_enrichment(a):
    s, reg, cert, resolver = make_context(a)
    catalog, seed = _entity_catalog_context(s, reg)
    result = audit_client_enrichment(
        s.project_root,
        s.client_root,
        catalog,
        seed,
        registry=reg,
        settings=s,
        progress=lambda msg: print(f"[client-enrichment] {msg}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3

def cmd_audit_source_contracts(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_source_contracts(
        s.project_root,
        source_root=getattr(a, "source_root", None),
        reference_source_root=getattr(a, "reference_source_root", None),
        progress=lambda msg: print(f"[source-contracts] {msg}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3

def cmd_audit_class_ui_aliases(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_class_ui_aliases(s.project_root, s.client_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_recover_class_ui_alias_only(a):
    s, reg, cert, resolver = make_context(a)
    result = canonicalize_class_ui_alias_only(
        s.project_root,
        s.client_root,
        expected_group=getattr(a, "expected_group", ""),
        expected_paths=getattr(a, "expected_path", None) or [],
        apply=bool(getattr(a, "apply", False)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_general_asset_census(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise FileNotFoundError("SERVER_ROOT_NOT_FOUND; configure --server-root or PT_SERVER_ROOT")
    donor_clients = getattr(a, "donor_client", None) or configured_contract_donor_clients(s.project_root)
    donor_servers = getattr(a, "donor_server", None) or configured_contract_donor_servers(s.project_root)
    result = audit_general_asset_census(
        s.project_root, s.client_root, s.server_root,
        source_root=getattr(a, "source_root", None),
        reference_source_root=getattr(a, "reference_source_root", None),
        donor_clients=donor_clients,
        donor_servers=donor_servers,
        progress=lambda msg: print(f"[general-asset-census] {msg}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_t5_effects(a):
    """Run a fresh General Census and print the Tier-5 effect+audio asset slice.

    This remains plan-only. Tier-5 gameplay functionality is not re-inferred;
    only current asset calls are attributed. Donor/reference presence alone is
    never import authority, and scoped import roots require CLOSED same-lineage
    physical bundles for the complete proven asset set of a skill.
    """
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise FileNotFoundError("SERVER_ROOT_NOT_FOUND; configure --server-root or PT_SERVER_ROOT")
    donor_clients = getattr(a, "donor_client", None) or configured_contract_donor_clients(s.project_root)
    donor_servers = getattr(a, "donor_server", None) or configured_contract_donor_servers(s.project_root)
    census = audit_general_asset_census(
        s.project_root, s.client_root, s.server_root,
        source_root=getattr(a, "source_root", None),
        reference_source_root=getattr(a, "reference_source_root", None),
        donor_clients=donor_clients,
        donor_servers=donor_servers,
        progress=lambda msg: print(f"[t5-assets] {msg}", flush=True),
    )
    report_path = pathlib.Path(str(census.get("t5_asset_report") or census.get("t5_effect_report") or ""))
    if not report_path.is_file():
        raise FileNotFoundError(f"T5_ASSET_REPORT_NOT_FOUND:{report_path}")
    result = json.loads(report_path.read_text(encoding="utf-8"))
    result["general_census_state"] = census.get("census_state")
    result["general_recoverable_reachable_candidate_count"] = census.get("recoverable_reachable_candidate_count", 0)
    result["general_recovery_bundle_root_count"] = census.get("recovery_bundle_root_count", 0)
    result["general_missing_reachable_no_donor_count"] = census.get("missing_reachable_no_donor_count", 0)
    result["general_census_report"] = census.get("report")
    result["reports_bundle"] = census.get("reports_bundle")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "t5_asset_readiness=" + str(result.get("status") or "UNKNOWN")
        + f" asset_call_skills={result.get('current_runtime_asset_skill_count', 0)}/{result.get('skill_count', 0)}"
        + f" effect_skills={result.get('current_runtime_effect_skill_count', 0)}"
        + f" audio_skills={result.get('current_runtime_audio_skill_count', 0)}"
        + f" client_asset_call_probes={result.get('current_client_asset_call_probe_count', 0)}"
        + f" client_audio_call_probes={result.get('current_client_audio_call_probe_count', 0)}"
        + f" unresolved_audio_call_probes={result.get('current_client_unresolved_audio_call_probe_count', 0)}"
        + f" client_effect_call_probes={result.get('current_client_effect_call_probe_count', 0)}"
        + f" t5_bridge_cases={result.get('current_t5_asset_bridge_case_count', 0)}"
        + f" closed_effect_roots={result.get('recoverable_closed_effect_root_count', 0)}"
        + f" closed_audio_roots={result.get('recoverable_closed_audio_root_count', 0)}"
        + f" scoped_import_roots={result.get('scoped_import_root_count', 0)}"
        + f" blocked_skills={result.get('current_asset_blocked_skill_count', 0)}"
        + f" scoped_import_ready={str(bool(result.get('scoped_import_ready'))).lower()}"
        + " client_modified=false server_modified=false"
    )
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_t5_assets(a):
    return cmd_audit_t5_effects(a)


def cmd_recover_general_closed_bundles(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise FileNotFoundError("SERVER_ROOT_NOT_FOUND; configure --server-root or PT_SERVER_ROOT")
    donor_clients = getattr(a, "donor_client", None) or configured_contract_donor_clients(s.project_root)
    donor_servers = getattr(a, "donor_server", None) or configured_contract_donor_servers(s.project_root)
    result = recover_closed_general_asset_bundles(
        s.project_root, s.client_root, s.server_root,
        source_root=getattr(a, "source_root", None),
        reference_source_root=getattr(a, "reference_source_root", None),
        donor_clients=donor_clients,
        donor_servers=donor_servers,
        expected_roots=getattr(a, "expected_root", None) or [],
        apply=bool(getattr(a, "apply", False)),
        progress=lambda msg: print(f"[general-asset-recovery] {msg}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_player_class_contracts(a):
    s, reg, cert, resolver = make_context(a)
    classes = tuple(getattr(a, "class_name", None) or TARGET_CLASSES)
    def progress(msg):
        print(f"[player-class-contracts] {msg}", flush=True)
    result = audit_player_class_contracts(
        s.project_root,
        s.client_root,
        source_root=getattr(a, "source_root", None),
        reference_source_root=getattr(a, "reference_source_root", None),
        donor_clients=(getattr(a, "donor_client", None) or configured_contract_donor_clients(s.project_root)),
        classes=classes,
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3

def cmd_aggregate_player_classes(a):
    s, reg, cert, resolver = make_context(a)
    classes = tuple(getattr(a, "class_name", None) or TARGET_CLASSES)
    def progress(msg):
        print(f"[aggregate-player-classes] {msg}", flush=True)
    result = build_player_class_aggregation(
        s.project_root,
        s.client_root,
        source_root=getattr(a, "source_root", None),
        reference_source_root=getattr(a, "reference_source_root", None),
        donor_clients=(getattr(a, "donor_client", None) or configured_contract_donor_clients(s.project_root)),
        classes=classes,
        materialize=not bool(getattr(a, "plan_only", False)),
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_aggregate_client_superset(a):
    s, reg, cert, resolver = make_context(a)
    donors = getattr(a, "donor_client", None) or configured_contract_donor_clients(s.project_root)
    result = build_client_superset(
        s.project_root, s.client_root, donors,
        materialize=not bool(getattr(a, "plan_only", False)),
        progress=lambda msg: print(f"[aggregate-client-superset] {msg}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_aggregate_server_superset(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise FileNotFoundError("SERVER_ROOT_NOT_FOUND; configure --server-root or PT_SERVER_ROOT")
    donors = getattr(a, "donor_server", None) or configured_contract_donor_servers(s.project_root)
    result = build_server_superset(
        s.project_root, s.server_root, donors,
        materialize=not bool(getattr(a, "plan_only", False)),
        progress=lambda msg: print(f"[aggregate-server-superset] {msg}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_aggregate_summit_superset(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise FileNotFoundError("SERVER_ROOT_NOT_FOUND; configure --server-root or PT_SERVER_ROOT")
    donor_clients = getattr(a, "donor_client", None) or configured_contract_donor_clients(s.project_root)
    donor_servers = getattr(a, "donor_server", None) or configured_contract_donor_servers(s.project_root)
    result = build_summit_superset(
        s.project_root, s.client_root, s.server_root,
        source_root=getattr(a, "source_root", None),
        reference_source_root=getattr(a, "reference_source_root", None),
        donor_clients=donor_clients, donor_servers=donor_servers,
        materialize=not bool(getattr(a, "plan_only", False)),
        progress=lambda msg: print(f"[aggregate-summit] {msg}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_enrichment_plan(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise RuntimeError("server root is not configured; use --server-root or PT_SERVER_ROOT")
    result = generate_migration_plan(
        s.project_root, s.client_root, s.server_root,
        timeout_seconds=float(getattr(a, "timeout", 180.0)),
        progress=lambda m: print(m, flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_audit_enrichment_graph(a):
    s, reg, cert, resolver = make_context(a)
    if s.server_root is None:
        raise RuntimeError("server root is not configured; use --server-root or PT_SERVER_ROOT")
    result = build_dependency_graph(
        s.project_root, s.client_root, s.server_root,
        skip_client_scan=bool(getattr(a, "skip_client_scan", False)),
        timeout_seconds=float(getattr(a, "timeout", 240.0)),
        progress=lambda m: print(m, flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_validate_server_design_auto(a):
    s, reg, cert, resolver = make_context(a)
    result = run_server_design_auto(
        s, server_root=getattr(a, "server_root", None),
        progress=lambda m: print(f"[server-design-auto] {m}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_validate_physical_regression_auto(a):
    s, reg, cert, resolver = make_context(a)
    result = run_physical_regression_auto(
        s, reg, resolver, cert,
        fps=int(getattr(a, "fps", 30)),
        blender_timeout_seconds=float(getattr(a, "environment_blender_timeout", 60.0)),
        smb_sample_limit=int(getattr(a, "smb_sample_limit", 25)),
        rigid_operation_timeout_seconds=float(getattr(a, "rigid_operation_timeout", 180.0)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_validate_integration_regression_auto(a):
    s, reg, cert, resolver = make_context(a)
    result = run_integration_regression_auto(
        s, reg, resolver, cert,
        fps=int(getattr(a, "fps", 30)),
        environment_blender_timeout_seconds=float(getattr(a, "environment_blender_timeout", 60.0)),
        affine_blender_timeout_seconds=float(getattr(a, "affine_blender_timeout", 90.0)),
        progress=lambda m: print(f"[integration-regression-auto] {m}", flush=True),
    )
    # Keep the terminal useful.  Full per-file server censuses stay in the
    # referenced result.json files; stdout ends with a compact actionable
    # summary so failures are not pushed out of terminal scrollback.
    gates = result.get("gates") or {}
    shown = {
        "format": result.get("format"),
        "status": result.get("status"),
        "integration_regression_ready": result.get("integration_regression_ready"),
        "required_failures": result.get("required_failures") or [],
        "failure_summary": result.get("failure_summary") or {},
        "gate_statuses": {
            name: (row or {}).get("status") if isinstance(row, dict) else "UNKNOWN"
            for name, row in gates.items()
        },
        "selection": result.get("selection") or {},
        "next_gate": result.get("next_gate"),
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
        "client_modified": bool(result.get("client_modified")),
        "server_modified": bool(result.get("server_modified")),
        "report": result.get("report"),
        "failure_summary_report": result.get("failure_summary_report"),
    }
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_validate_release_1_auto(a):
    s, reg, cert, resolver = make_context(a)
    environment = run_environment_validation(
        s, reg, resolver,
        blender_timeout_seconds=float(getattr(a, "environment_blender_timeout", 60.0)),
    )
    release_1_auto_may_run = bool((environment.get("policy") or {}).get("release_1_auto_may_run"))
    if environment.get("status") != "PASS" or not release_1_auto_may_run:
        shown = {
            "format": "PT_ASSET_RELEASE_1_ENVIRONMENT_BLOCK_V1",
            "status": "FAIL",
            "automatic_gate_status": (
                "NOT_RUN_ENVIRONMENT_FAIL"
                if environment.get("status") != "PASS"
                else "NOT_RUN_BLENDER_UNAVAILABLE"
            ),
            "environment": environment,
            "production_authorized": False,
            "client_write_authorized": False,
            "client_modified": bool(environment.get("client_modified")),
        }
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        return 3
    server_design = None
    if s.server_root is not None:
        print(f"[release-1-auto] START server_design_auto root={s.server_root}", flush=True)
        server_design = run_server_design_auto(
            s, server_root=s.server_root,
            progress=lambda m: print(f"[release-1-auto] SERVER {m}", flush=True),
        )
        print(f"[release-1-auto] DONE  server_design_auto status={server_design.get('status')}", flush=True)
        if server_design.get("status") != "PASS":
            shown = {
                "format": "PT_ASSET_RELEASE_1_SERVER_ENVIRONMENT_BLOCK_V1",
                "status": "FAIL",
                "automatic_gate_status": "NOT_RUN_SERVER_DESIGN_FAIL",
                "environment": environment,
                "server_design": server_design,
                "production_authorized": False,
                "client_write_authorized": False,
                "server_write_authorized": False,
                "client_modified": bool(environment.get("client_modified")),
                "server_modified": bool(server_design.get("server_modified")),
            }
            print(json.dumps(shown, ensure_ascii=False, indent=2))
            return 3
    result = run_release_1_automated_gate(
        s, reg, resolver, cert,
        rigid_per_domain=int(a.rigid_per_domain), static_per_domain=int(a.static_per_domain),
        object_local_limit=int(a.object_local_limit), texlink_limit=int(a.texlink_limit),
        animation_fps=int(a.fps), motion_pair_limit=int(a.motion_pair_limit), resume=bool(a.resume),
        motion_semantic_timeout_seconds=float(a.motion_semantic_timeout),
    )
    environment_summary = {
        "status": environment.get("status"),
        "environment_ready": environment.get("environment_ready"),
        "required_failure_count": environment.get("required_failure_count"),
        "report": environment.get("report"),
        "blender_version": ((environment.get("blender") or {}).get("payload") or {}).get("blender_version"),
        "client_modified": environment.get("client_modified"),
    }
    result["environment"] = environment_summary
    server_design_summary = None
    if isinstance(server_design, dict):
        server_design_summary = {
            "status": server_design.get("status"),
            "server_design_catalog_ready": server_design.get("server_design_catalog_ready"),
            "bundle_closure_complete": server_design.get("bundle_closure_complete"),
            "unresolved_or_review_count": server_design.get("unresolved_or_review_count"),
            "report": server_design.get("report"),
            "server_write_authorized": False,
        }
        result["server_design"] = server_design_summary
    try:
        result_report = pathlib.Path(str(result.get("report") or "")).expanduser().resolve()
        if result_report.is_file():
            persisted = json.loads(result_report.read_text(encoding="utf-8"))
            if isinstance(persisted, dict):
                persisted["environment"] = environment_summary
                if server_design_summary is not None:
                    persisted["server_design"] = server_design_summary
                result_report.write_text(json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        result["environment_report_attach_error"] = f"{type(exc).__name__}:{exc}"
    shown = {
        "format": result.get("format"), "status": result.get("status"),
        "automatic_gate_status": result.get("automatic_gate_status"),
        "environment": environment_summary,
        "server_design": server_design_summary,
        "release_target": result.get("release_target"), "summary": result.get("summary"),
        "blockers": result.get("blockers"), "manual_review_required_now": result.get("manual_review_required_now"),
        "external_input_required": result.get("external_input_required"),
        "external_input_request": result.get("external_input_request"),
        "external_gates_pending": result.get("external_gates_pending"),
        "runtime_game_acceptance_pending": result.get("runtime_game_acceptance_pending"),
        "production_authorized": False, "client_write_authorized": False, "server_write_authorized": False, "client_modified": False,
        "report": result.get("report"),
    }
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"PASS", "BLOCKED_EXTERNAL"} else 3


def cmd_validate_rigid_profile_auto(a):
    s, reg, cert, resolver = make_context(a)
    profiles = _profile_registry(s)
    if bool(getattr(a, "all", False)):
        profile_ids = [p.profile_id for p in profiles.list()]
    else:
        profile_ids = [str(a.profile)]
    result = run_rigid_profile_automated_devtest_batch(
        s, reg, resolver, cert, profiles, profile_ids, amplitude=float(a.amplitude)
    )
    # Keep the terminal payload compact; detailed per-object/writer reports are
    # persisted under pt_build and referenced by path in each result.
    shown = {
        "format": result.get("format"),
        "status": result.get("status"),
        "profile_count": result.get("profile_count"),
        "passed_profiles": result.get("passed_profiles"),
        "failed_profiles": result.get("failed_profiles"),
        "profiles": [
            {
                "profile_id": row.get("profile_id"),
                "status": row.get("status"),
                "asset": row.get("asset"),
                "automatic_edit": row.get("automatic_edit"),
                "candidate": row.get("candidate"),
                "reimport": row.get("reimport"),
                "report": row.get("report"),
            }
            for row in (result.get("results") or [])
        ],
        "automatic_only": True,
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
        "report": result.get("report"),
    }
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3

def cmd_audit_stage072_normals(a):
    s, reg, cert, resolver = make_context(a)
    result = audit_stage072_normals(reg.records, resolver, bundle=a.bundle)
    rows = result.pop("rows", [])
    if a.output:
        out = pathlib.Path(a.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        full = dict(result); full["rows"] = rows; full["report"] = str(out)
        out.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "stage072_vectnormal_audit=" + result["status"] +
        f" audited={result['physical_files_audited']}/{result['candidate_files_expected']}" +
        f" current_exact={result['current_exact_files']}" +
        f" legacy_exact={result['legacy_reciprocal_exact_files']}" +
        f" legacy_unresolved={result['legacy_float_variant_unresolved_files']}" +
        f" max_legacy_delta={result['max_legacy_component_delta']}" +
        f" geometry_complete={str(result['stage072_geometry_write_complete_candidate']).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3



def cmd_audit_rare_rigid_edit_workflow(a):
    s, reg, cert, resolver = make_context(a)
    work = s.project_root / "pt_build" / "rare_rigid_edit_workflow_v089"
    result = audit_rare_rigid_edit_workflow(
        reg, resolver, cert, s, project_root=s.project_root, work=work
    )
    if a.output:
        out = pathlib.Path(a.output).expanduser()
        if not out.is_absolute():
            out = s.project_root / out
        out = out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        full = dict(result); full["report"] = str(out)
        out.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_edit_workflow=" + result["status"] +
        f" transactions={result.get('transaction_roundtrip_pass',0)}/{result.get('transaction_representatives_expected',0)}" +
        f" vertex_counts={','.join(str(x) for x in result.get('transaction_vertex_counts',[]))}" +
        f" shared_face_reps={result.get('shared_face_transaction_representatives',0)}" +
        f" max_bones={result.get('max_affected_bone_count',0)}" +
        f" normal_reimport_error_fixed={result.get('max_target_reimport_normal_error_fixed',0)}" +
        f" multivertex_write={str(result.get('multi_vertex_transaction_write_authorized',False)).lower()}" +
        f" atomic={str(result.get('atomic_output_replace',False)).lower()}"
    )
    return 0 if result["status"] == "PASS" else 3


def cmd_edit_rare_model(a):
    s, reg, cert, resolver = make_context(a)
    target = norm_path(a.target)
    if target.lower() not in {"char/tmabcd/at_dragon.smd", "at_dragon.smd"}:
        raise SystemExit("V0.8.9 guarded edit workspace currently accepts only char/tmABCD/at_dragon.smd")
    logical = "char/tmABCD/at_dragon.smd"
    workspace = blender_edit_root(s.project_root, "rare_model", logical)
    write_workspace_info(workspace, workflow="rare_model", logical=logical, extra={"guarded_writer": True})
    result = prepare_at_dragon_edit_workspace(
        reg, resolver, cert, s, project_root=s.project_root, open_gui=True, reset=bool(a.reset),
        workspace_root=workspace
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_edit=READY" +
        f" blend={result['edit_blend']}" +
        " scope=ONE_TO_FOUR_VERTEX_SINGLE_OBJECT_MULTIBONE_INTERIOR_TRANSACTION client_modified=false"
    )
    return 0



def _enforce_candidate_edit_requirement(kind, verification, require_edit):
    """Fail closed when a candidate workflow explicitly requires an observed edit.

    This is deliberately a small policy helper: it does not infer whether an edit
    occurred; it only enforces the verifier's ``edit_observed`` evidence when the
    caller requested ``--require-edit``.  Candidate output remains pt_build-only.
    """
    result = dict(verification or {})
    result["edit_required"] = bool(require_edit)
    if not require_edit:
        return result
    if bool(result.get("edit_observed")):
        return result
    result["status"] = "FAIL"
    errors = list(result.get("errors") or [])
    if "TARGET_EDIT_NOT_OBSERVED" not in errors:
        errors.append("TARGET_EDIT_NOT_OBSERVED")
    result["errors"] = errors
    return result


def _parse_material_edits(specs):
    edits = {}
    float_fields = {"transparency", "self_illum"}
    int_fields = {"texture_type", "blend_type", "shade", "two_side"}
    for raw in specs or []:
        text = str(raw)
        if "=" not in text:
            raise RuntimeError(f"invalid material edit {text!r}; expected FIELD=VALUE")
        field, value = text.split("=", 1)
        field = field.strip()
        value = value.strip()
        if field in float_fields:
            edits[field] = float(value)
        elif field in int_fields:
            edits[field] = int(value, 0)
        else:
            raise RuntimeError(f"unsupported material field: {field}")
    if not edits:
        raise RuntimeError("at least one --set FIELD=VALUE is required")
    return edits


def cmd_asset_material_candidate(a):
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    edits = _parse_material_edits(a.set_values)
    output = _pt_build_output(
        s, a.output,
        default_rel=pathlib.Path("material_candidate") / asset_workspace_name(asset.primary_path) / pathlib.PurePosixPath(asset.primary_path).name,
    )

    if asset.kind == "SMD_MODEL_062":
        rebuilt, writer = rebuild_material_fields(source, material_index=int(a.material_index), edits=edits)
        verify_fn = verify_material_candidate
        report_format = "PT_ASSET_MODEL062_MATERIAL_CANDIDATE_V1"
        build_mode = "CANDIDATE_MODEL062_MATERIAL"
        adapter = "pt_asset_tool.model062_material_writer"
    elif asset.kind == "SMD_STAGE_072" or asset.family == "STAGE_072_MAP_SEPARATE":
        rebuilt, writer = rebuild_stage_material_fields(source, material_index=int(a.material_index), edits=edits)
        verify_fn = verify_stage_material_candidate
        report_format = "PT_ASSET_STAGE072_MATERIAL_CANDIDATE_V1"
        build_mode = "CANDIDATE_STAGE072_MATERIAL"
        adapter = "pt_asset_tool.stage072_material_writer"
    else:
        raise RuntimeError(f"material candidate supports Model0.62 and Stage0.72 only; got kind={asset.kind} family={asset.family}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rebuilt)
    verification = verify_fn(source, output, material_index=int(a.material_index), edits=edits)
    shown = {
        "format": report_format,
        "status": "PASS" if writer.get("status") == "PASS" and verification.get("status") == "PASS" else "FAIL",
        "asset": asset.primary_path, "family": asset.family, "kind": asset.kind,
        "source": str(source), "output": str(output),
        "material_index": int(a.material_index), "edits": edits, "writer": writer, "verification": verification,
        "authorization": "CANDIDATE_PT_BUILD_ONLY", "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }
    if shown["status"] == "PASS":
        prov = write_build_provenance(
            output, asset=asset, source=source, build_mode=build_mode,
            adapter=adapter, build_status="PASS", production_authorized=False,
            evidence={"material_index": int(a.material_index), "edits": edits, "verification": verification},
        )
        shown["build_provenance"] = str(prov)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if shown["status"] == "PASS" else 3

def cmd_import_asset(a):
    """Prepare/open a reusable Blender workspace for a supported asset.

    This command deliberately separates import from build.  Successful import
    means the asset can be represented in Blender through a proven adapter; it
    does *not* imply that a generic writer exists for the family.
    """
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    profile_plan = None
    model_info = getattr(a, "model_info", None)
    skeleton = getattr(a, "skeleton", None)
    selection_basis = None
    profile_id = getattr(a, "profile", None)
    if profile_id:
        if model_info or skeleton:
            raise RuntimeError("--profile is mutually exclusive with --model-info/--skeleton")
        profile_plan = plan_profile_authoring_context(
            _profile_registry(s), profile_id, resolver, reg, lod=a.lod
        )
        if profile_plan.get("status") != "READY":
            raise RuntimeError(f"profile authoring context is blocked: {profile_plan.get('errors')}")
        if str(profile_plan.get("asset") or "").replace("\\", "/").casefold() != asset.primary_path.replace("\\", "/").casefold():
            raise RuntimeError("profile roundtrip target does not match requested import asset")
        model_info = profile_plan["model_info_inx"]
        selection_basis = profile_plan["selection_basis"]
    runner = ValidationRunner(ValidationContext(s, resolver, cert))
    result = runner.blender_import_workspace(
        asset, lod=a.lod, reset=bool(a.reset), model_info=model_info,
        selection_basis=selection_basis, skeleton=skeleton,
        motion=getattr(a, "motion", "STAND"),
        load_actions=getattr(a, "load_actions", "all"),
    )
    if profile_plan is not None:
        result["profile_authoring_plan"] = profile_plan
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "asset_import=READY"
        f" family={asset.family} kind={asset.kind}"
        f" blend={result['blend']}"
        f" reused={str(bool(result.get('reused_existing'))).lower()}"
        " build_supported=false client_modified=false"
    )
    if a.no_open:
        return 0

    open_mode = str(getattr(a, "open_mode", "paint") or "paint").strip().lower()
    animation_meta = dict(result.get("animation_authoring") or {})
    if open_mode == "animation":
        preview = animation_meta.get("preview_blend")
        if not preview:
            raise RuntimeError(
                "animation preview is unavailable; use --load-actions all|selected or open --open-mode paint"
            )
        open_blend = pathlib.Path(preview).resolve()
        gui_cmd = s.blender_command() + [str(open_blend)]
        paint_supported = False
    else:
        open_blend = pathlib.Path(result["blend"]).resolve()
        gui_cmd = s.blender_command() + [
            str(open_blend),
            "--python", str(s.project_root / "pt_asset_tool/blender/authoring_session_save.py"),
            "--", "--workspace", str(pathlib.Path(result["workspace"]).resolve()),
        ]
        paint_supported = True

    try:
        proc = subprocess.Popen(
            gui_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
        )
    except Exception as exc:
        raise RuntimeError(f"failed to launch Blender GUI: {type(exc).__name__}:{exc}") from exc
    print(
        f"blender_launch=DETACHED pid={proc.pid} mode={open_mode} blend={open_blend} "
        f"texture_paint_supported={str(paint_supported).lower()}"
    )
    if open_mode == "animation":
        print(
            "animation_preview_note=Texture Paint is intentionally disabled for this workflow; "
            "paint in --open-mode paint and reopen animation preview to see the shared overlay."
        )
    print("ui_job_release=IMMEDIATE client_modified=false")
    return 0


def cmd_build_asset(a):
    if bool(getattr(a, "require_edit", False)) and not bool(getattr(a, "candidate", False)):
        raise RuntimeError("--require-edit requires --candidate")
    if bool(getattr(a, "stress_profile", False)) and not bool(getattr(a, "candidate", False)):
        raise RuntimeError("--stress-profile requires --candidate")
    if bool(getattr(a, "stress_profile", False)) and getattr(a, "object", None):
        raise RuntimeError("--stress-profile selects the full canonical profile scope; do not combine it with --object")
    s, reg, cert, resolver = make_context(a)
    asset = reg.resolve(a.target)
    plan = build_plan(asset)
    source_for_authoring = None
    if asset.kind == "SMD_MODEL_062":
        try:
            source_for_authoring = resolver.resolve(asset.primary_path, required=True)
        except Exception:
            source_for_authoring = None
    authoring = authoring_plan(asset, source_for_authoring)
    if a.plan:
        shown = {"build_plan": plan, "authoring_plan": authoring}
        if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            workspace = blender_edit_root(s.project_root, "generic_import", asset.primary_path)
            manifest = workspace / "authoring_manifest.json"
            if manifest.is_file():
                manifest_verify = verify_workspace_manifest(manifest)
                selected_context = manifest_verify.get("selected_context")
                candidate_scope = inspect_rigid_candidate_scope(authoring, selected_context)
                candidate_scope["workspace"] = str(workspace)
                candidate_scope["manifest_verification_status"] = manifest_verify.get("status")
                candidate_scope["status"] = (
                    "READY" if manifest_verify.get("status") == "PASS"
                    and candidate_scope.get("eligible_objects")
                    else "BLOCKED"
                )
                shown["candidate_scope"] = candidate_scope
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        return 0

    if bool(getattr(a, "candidate", False)):
        if asset.family == "SMD_MODEL_062_STATIC":
            candidate = plan_static_saved_blender_candidate(
                s.project_root, resolver, asset, object_name=getattr(a, "object", None), output=a.output
            )
            kind = "STATIC"
        elif asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE" and bool(getattr(a, "stress_profile", False)):
            candidate = plan_rigid_profile_stress_candidate(
                s.project_root, resolver, asset, output=a.output
            )
            kind = "RIGID_STRESS"
        elif asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            candidate = plan_rigid_saved_blender_candidate(
                s.project_root, resolver, asset, object_name=getattr(a, "object", None), output=a.output
            )
            kind = "RIGID"
        elif asset.family == "SMD_MODEL_062_MIXED_PHYSIQUE":
            if getattr(a, "object", None):
                raise RuntimeError("mixed-Physique candidate rewrites the verified eligible mixed target set; do not combine with --object")
            candidate = plan_mixed_saved_blender_candidate(
                s.project_root, resolver, asset, output=a.output
            )
            kind = "MIXED"
        elif asset.kind == "SMD_STAGE_072":
            candidate = plan_stage072_saved_blender_candidate(
                s.project_root, resolver, asset, output=a.output
            )
            kind = "STAGE072"
        else:
            raise RuntimeError(f"candidate build is not wired for family={asset.family}")
        if candidate.get("status") != "READY":
            raise RuntimeError(f"{kind.lower()} candidate build is blocked: {candidate.get('blockers')}")
        output = pathlib.Path(candidate["output"]).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        report = output.with_suffix(output.suffix + ".writer.json")
        log = output.with_suffix(output.suffix + ".build.log")
        if kind == "STATIC":
            cmd = build_static_candidate_blender_command(s, candidate, report=report)
            run_logged(cmd, log)
            writer_report = json.loads(report.read_text(encoding="utf-8"))
            verification = validate_static_candidate_output(
                pathlib.Path(candidate["source"]), output, candidate["object"]
            )
        elif kind == "RIGID":
            cmd = build_rigid_candidate_blender_command(s, candidate, report=report)
            run_logged(cmd, log)
            writer_report = json.loads(report.read_text(encoding="utf-8"))
            verification = validate_rigid_candidate_output(
                s.project_root, pathlib.Path(candidate["source"]), output, pathlib.Path(candidate["skeleton"]), candidate["object"]
            )
        elif kind == "RIGID_STRESS":
            steps_dir = output.parent / "stress_steps"
            steps_dir.mkdir(parents=True, exist_ok=True)
            current_source = pathlib.Path(candidate["source"]).resolve()
            step_reports = []
            objects = list(candidate.get("objects") or [])
            for idx, object_name in enumerate(objects, start=1):
                is_last = idx == len(objects)
                step_output = output if is_last else (steps_dir / f"{idx:02d}_{object_name}.smd")
                step_report = steps_dir / f"{idx:02d}_{object_name}.writer.json"
                step_log = steps_dir / f"{idx:02d}_{object_name}.build.log"
                step_candidate = dict(candidate)
                step_candidate["source"] = str(current_source)
                step_candidate["source_sha256"] = sha256_file(current_source)
                step_candidate["object"] = object_name
                step_candidate["output"] = str(step_output)
                cmd = build_rigid_candidate_blender_command(s, step_candidate, report=step_report)
                run_logged(cmd, step_log)
                step_data = json.loads(step_report.read_text(encoding="utf-8"))
                step_reports.append({
                    "index": idx, "object": object_name, "lod": (candidate.get("object_lods") or {}).get(object_name),
                    "input": str(current_source), "input_sha256": sha256_file(current_source),
                    "output": str(step_output), "output_sha256": sha256_file(step_output),
                    "writer_report": str(step_report), "log": str(step_log),
                    "source_counts": step_data.get("source_counts"),
                    "output_counts": step_data.get("output_counts"),
                    "topology_changed": (step_data.get("source_counts") or {}) != (step_data.get("output_counts") or {}),
                    "unrelated_object_blocks_byte_identical": step_data.get("unrelated_object_blocks_byte_identical"),
                    "max_vertex_fit_error": step_data.get("max_vertex_fit_error"),
                })
                current_source = step_output.resolve()
            writer_report = {
                "tool": "PT_RIGID_PROFILE_STRESS_WRITER_V1",
                "objects": objects,
                "object_lods": dict(candidate.get("object_lods") or {}),
                "step_count": len(step_reports),
                "steps": step_reports,
                "output_sha256": sha256_file(output),
            }
            report.write_text(json.dumps(writer_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            log.write_text("RIGID_PROFILE_STRESS steps=" + str(len(step_reports)) + "\n", encoding="utf-8")
            verification = validate_rigid_profile_stress_output(
                s.project_root, pathlib.Path(candidate["source"]), output, pathlib.Path(candidate["skeleton"]), objects
            )
        elif kind == "MIXED":
            steps_dir = output.parent / "mixed_steps"
            steps_dir.mkdir(parents=True, exist_ok=True)
            current_source = pathlib.Path(candidate["source"]).resolve()
            step_reports = []
            objects = list(candidate.get("objects") or [])
            for idx, object_name in enumerate(objects, start=1):
                is_last = idx == len(objects)
                step_output = output if is_last else (steps_dir / f"{idx:02d}_{object_name}.smd")
                step_report = steps_dir / f"{idx:02d}_{object_name}.writer.json"
                step_log = steps_dir / f"{idx:02d}_{object_name}.build.log"
                cmd = build_mixed_candidate_step_command(
                    s, candidate, object_name=object_name, source=current_source, output=step_output, report=step_report
                )
                run_logged(cmd, step_log)
                step_data = json.loads(step_report.read_text(encoding="utf-8"))
                step_reports.append({
                    "index": idx, "object": object_name, "adapter": (candidate.get("object_adapters") or {}).get(object_name),
                    "input": str(current_source), "input_sha256": sha256_file(current_source),
                    "output": str(step_output), "output_sha256": sha256_file(step_output),
                    "writer_report": str(step_report), "log": str(step_log),
                    "source_counts": step_data.get("source_counts"), "output_counts": step_data.get("output_counts"),
                    "unrelated_object_blocks_byte_identical": step_data.get("unrelated_object_blocks_byte_identical"),
                    "max_vertex_fit_error": step_data.get("max_vertex_fit_error"),
                })
                current_source = step_output.resolve()
            writer_report = {
                "tool": "PT_MIXED_PHYSIQUE_COMBINED_WRITER_V1", "objects": objects,
                "object_adapters": dict(candidate.get("object_adapters") or {}),
                "step_count": len(step_reports), "steps": step_reports, "output_sha256": sha256_file(output),
            }
            report.write_text(json.dumps(writer_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            log.write_text("MIXED_PHYSIQUE_COMBINED steps=" + str(len(step_reports)) + "\n", encoding="utf-8")
            verification = validate_mixed_candidate_output(
                pathlib.Path(candidate["source"]), output, target_objects=objects,
                project_root=s.project_root, skeleton=pathlib.Path(candidate["skeleton"]),
            )
            if bool(getattr(a, "require_edit", False)) and not bool(verification.get("all_target_edits_observed")):
                verification = dict(verification)
                verification["status"] = "FAIL"
                errors = list(verification.get("errors") or [])
                if "TARGET_EDIT_NOT_OBSERVED" not in errors:
                    errors.append("TARGET_EDIT_NOT_OBSERVED")
                verification["errors"] = errors
                verification["edit_required"] = True
        else:
            witness = output.with_suffix(output.suffix + ".saved_edit_witness.json")
            extract_report = output.with_suffix(output.suffix + ".saved_edit_extract.json")
            cmd = build_stage072_edit_extract_command(s, candidate, witness=witness, report=extract_report)
            run_logged(cmd, log)
            writer_report = json.loads(extract_report.read_text(encoding="utf-8"))
            verification = apply_stage072_candidate_witness(candidate, witness)
        require_edit = bool(getattr(a, "require_edit", False))
        verification = _enforce_candidate_edit_requirement(kind, verification, require_edit) if kind not in {"RIGID_STRESS", "MIXED"} else verification
        shown = {
            "format": "PT_ASSET_CANDIDATE_BUILD_V1",
            "status": "PASS" if verification.get("status") == "PASS" else "FAIL",
            "candidate_kind": kind,
            "authorization": "CANDIDATE_PT_BUILD_ONLY",
            "candidate_plan": candidate,
            "writer_report": writer_report,
            "verification": verification,
            "log": str(log),
            "production_authorized": False,
            "client_write_authorized": False,
            "client_modified": False,
        }
        if shown["status"] == "PASS" and output.is_file():
            adapter = {
                "STATIC": "pt_blender_to_smd_static_v1.py",
                "RIGID": "pt_blender_to_smd_free_mesh_v3.py",
                "RIGID_STRESS": "pt_blender_to_smd_free_mesh_v3.py",
                "MIXED": "pt_asset_tool.mixed_authoring_candidate",
                "STAGE072": "pt_asset_tool.stage072_authoring_candidate",
            }[kind]
            prov = write_build_provenance(
                output, asset=asset, source=pathlib.Path(candidate["source"]),
                build_mode=f"CANDIDATE_{kind}", adapter=adapter,
                build_status="PASS", production_authorized=False,
                evidence=(
                    {
                        "verification_format": verification.get("format"), "verification_status": verification.get("status"),
                        "authorization": "CANDIDATE_PT_BUILD_ONLY", "mixed_physique": True,
                        "candidate_objects": list(candidate.get("objects") or []),
                        "object_adapters": dict(candidate.get("object_adapters") or {}),
                        "all_target_edits_observed": bool(verification.get("all_target_edits_observed")),
                        "targets_without_observed_edit": list(verification.get("targets_without_observed_edit") or []),
                        "verification_errors": list(verification.get("errors") or []),
                        "non_target_changed": list(verification.get("non_target_changed") or []),
                        "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}),
                        "target_results": list(verification.get("target_results") or []),
                        "writer_tool": writer_report.get("tool"), "writer_output_sha256": writer_report.get("output_sha256"),
                        "writer_step_count": writer_report.get("step_count"),
                    } if kind == "MIXED" else ({
                        "verification_format": verification.get("format"),
                        "verification_status": verification.get("status"),
                        "authorization": "CANDIDATE_PT_BUILD_ONLY",
                        "stress_profile": True,
                        "candidate_objects": list(candidate.get("objects") or []),
                        "stress_object_lods": dict(candidate.get("object_lods") or {}),
                        "profile_id": ((candidate.get("selected_context") or {}).get("selection_basis") or {}).get("profile_id"),
                        "edit_observed_by_object": dict(verification.get("edit_observed_by_object") or {}),
                        "all_target_edits_observed": bool(verification.get("all_target_edits_observed")),
                        "targets_without_observed_edit": list(verification.get("targets_without_observed_edit") or []),
                        "verification_errors": list(verification.get("errors") or []),
                        "non_target_changed": list(verification.get("non_target_changed") or []),
                        "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}),
                        "targets": dict(verification.get("targets") or {}),
                        "writer_tool": writer_report.get("tool"),
                        "writer_output_sha256": writer_report.get("output_sha256"),
                        "writer_step_count": writer_report.get("step_count"),
                    } if kind == "RIGID_STRESS" else build_candidate_provenance_evidence(
                        kind, candidate, writer_report, verification, require_edit=require_edit
                    ))
                ),
                selected_context=candidate.get("selected_context") if kind in {"RIGID", "RIGID_STRESS", "MIXED"} else None,
            )
            shown["build_provenance"] = str(prov)
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        return 0 if shown["status"] == "PASS" else 3

    if not plan.get("authorized"):
        raise RuntimeError(f"generic build is fail-closed for {asset.primary_path}: {plan.get('reason')}")
    if plan.get("adapter") != "RARE_RIGID_AT_DRAGON_CERTIFIED":
        raise RuntimeError(f"build adapter not wired: {plan.get('adapter')}")
    output = _pt_build_output(
        s, a.output,
        default_rel=pathlib.Path("generic_build") / asset_workspace_name(asset.primary_path) / pathlib.PurePosixPath(asset.primary_path).name,
    )
    workspace = blender_edit_root(s.project_root, "rare_model", asset.primary_path)
    result = write_at_dragon_edit_workspace(
        reg, resolver, cert, s, project_root=s.project_root, output=output, workspace_root=workspace
    )
    shown = {
        "format": "PT_ASSET_GENERIC_BUILD_V1",
        "status": result.get("status"),
        "plan": plan,
        "result": result,
        "client_modified": False,
    }
    if result.get("status") == "PASS" and pathlib.Path(output).is_file():
        prov = write_build_provenance(
            pathlib.Path(output), asset=asset, source=resolver.resolve(asset.primary_path),
            build_mode="PRODUCTION_CERTIFIED", adapter=str(plan.get("adapter") or ""),
            build_status="PASS", production_authorized=True,
            evidence={"writer_result_format": result.get("format"), "build_plan": plan},
        )
        shown["build_provenance"] = str(prov)
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 3


def cmd_deploy_plan(a):
    s, reg, cert, resolver = make_context(a)
    result = plan_deployment(s.project_root, resolver, reg, a.target, a.artifact)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_write_rare_model(a):
    s, reg, cert, resolver = make_context(a)
    target = norm_path(a.target)
    if target.lower() not in {"char/tmabcd/at_dragon.smd", "at_dragon.smd"}:
        raise SystemExit("V0.8.9 guarded writer currently accepts only char/tmABCD/at_dragon.smd")
    output = pathlib.Path(a.output).expanduser() if a.output else None
    logical = "char/tmABCD/at_dragon.smd"
    workspace = blender_edit_root(s.project_root, "rare_model", logical)
    result = write_at_dragon_edit_workspace(
        reg, resolver, cert, s, project_root=s.project_root, output=output, workspace_root=workspace
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "rare_rigid_write=" + result["status"] +
        f" changed_vertices={result['artist_changed_vertices']}" +
        f" affected_bones={result['affected_bone_count']}" +
        f" normal_reimport_error_fixed={result['max_target_reimport_normal_error_fixed']}" +
        f" output={result['output_smd']}" +
        " client_modified=false"
    )
    return 0 if result["status"] == "PASS" else 3


def build_parser():
    p = argparse.ArgumentParser(prog="pt_asset", description="Summit Tale asset registry and validation backend")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--root", help="design_work root (default: package parent or PT_PROJECT_ROOT)")
    p.add_argument("--client-root", help="client root (default: PT_CLIENT_ROOT or standard Summit path)")
    p.add_argument("--server-root", help="server root (default: PT_SERVER_ROOT; server integration is read-only until separately certified)")
    sp = p.add_subparsers(dest="command", required=True)

    x = sp.add_parser("doctor"); x.set_defaults(func=cmd_doctor)
    x = sp.add_parser("families"); x.set_defaults(func=cmd_families)
    entities = sp.add_parser("entities", help="inspect live Monster/NPC physical entities with registry evidence"); enp = entities.add_subparsers(dest="entities_cmd", required=True)
    x = enp.add_parser("list"); x.add_argument("--group", choices=("MONSTER","NPC")); x.add_argument("--q", default=""); x.add_argument("--limit", type=int, default=200); x.add_argument("--json", action="store_true"); x.set_defaults(func=cmd_entities_list)
    x = enp.add_parser("inspect"); x.add_argument("group", choices=("MONSTER","NPC")); x.add_argument("entity", help="entity display name, folder path or entity key"); x.set_defaults(func=cmd_entities_inspect)
    profiles = sp.add_parser("profiles", help="inspect canonical character/LOD profiles"); prp = profiles.add_subparsers(dest="profiles_cmd", required=True)
    x = prp.add_parser("list"); x.set_defaults(func=cmd_profiles_list)
    x = prp.add_parser("inspect"); x.add_argument("profile_id"); x.set_defaults(func=cmd_profiles_inspect)
    x = prp.add_parser("lod"); x.add_argument("profile_id"); x.add_argument("--lod", required=True, choices=("high","default","low","all")); x.set_defaults(func=cmd_profiles_lod)
    x = prp.add_parser("discover", help="discover rigid Model0.62 profile/LOD candidates from registry-proven INX data without creating/authorizing profiles"); x.add_argument("--category"); x.add_argument("--limit", type=int, default=50, help="rows printed in JSON; zero means all"); x.add_argument("--output", help="optional full/limited JSON report under pt_build"); x.set_defaults(func=cmd_profiles_discover)
    x = prp.add_parser("authoring-plan", help="resolve one canonical profile to an exact registry-proven rigid import context; read-only and not writer authorization"); x.add_argument("profile_id"); x.add_argument("--lod", choices=("auto","high","default","low"), default="auto"); x.set_defaults(func=cmd_profiles_authoring_plan)
    x = prp.add_parser("verify", help="verify profile components against the configured client without authorizing writes"); g=x.add_mutually_exclusive_group(required=True); g.add_argument("profile_id", nargs="?"); g.add_argument("--all", action="store_true"); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_profiles_verify)
    contracts = sp.add_parser("contracts", help="source-derived asset contract registry and schemas")
    ctp = contracts.add_subparsers(dest="contracts_cmd", required=True)
    x = ctp.add_parser("list", help="list source-derived game asset contracts and current tool implementation state")
    x.add_argument("--query", default=""); x.add_argument("--capability", default=""); x.add_argument("--implementation", default="")
    x.set_defaults(func=cmd_contracts_registry_list)
    x = ctp.add_parser("show", help="show one contract and its exact source-derived schema when available")
    x.add_argument("contract_id"); x.set_defaults(func=cmd_contracts_registry_show)

    compiler = sp.add_parser("asset-compiler", help="compile typed asset recipes or multi-asset bundles into pt_build overlays; never writes live client/server")
    acp = compiler.add_subparsers(dest="asset_compiler_cmd", required=True)
    x = acp.add_parser("capabilities", help="show contracts with direct recipe compilers")
    x.set_defaults(func=cmd_asset_compiler_capabilities)
    x = acp.add_parser("plan", help="validate and compile a recipe in memory without writing output")
    x.add_argument("recipe"); x.set_defaults(func=cmd_asset_compiler_plan)
    x = acp.add_parser("build", help="compile a validated recipe into pt_build/asset_compiler only")
    x.add_argument("recipe"); x.set_defaults(func=cmd_asset_compiler_build)
    x = acp.add_parser("status", help="show latest compiled bundle and deploy/rollback state")
    x.set_defaults(func=cmd_asset_compiler_status)
    x = acp.add_parser("publish", help=f"publish a compiled bundle transactionally; requires --confirm '{ASSET_BUNDLE_APPLY_CONFIRM}'")
    x.add_argument("--manifest", help="bundle manifest; defaults to latest compiled bundle")
    x.add_argument("--confirm", required=True); x.set_defaults(func=cmd_asset_compiler_publish)
    x = acp.add_parser("restore", help=f"restore latest transaction for a compiled bundle; requires --confirm '{ASSET_BUNDLE_RESTORE_CONFIRM}'")
    x.add_argument("--manifest", help="bundle manifest; defaults to latest compiled bundle")
    x.add_argument("--confirm", required=True); x.set_defaults(func=cmd_asset_compiler_restore)

    lm = sp.add_parser("legacy-management", help="static integration of historical Management tooling evidence; never executes legacy EXEs")
    lmp = lm.add_subparsers(dest="legacy_management_cmd", required=True)
    x = lmp.add_parser("summary", help="show versioned PriTaTor/NPCManager/ItemDistributor contracts and item taxonomy"); x.set_defaults(func=cmd_legacy_management_summary)
    x = lmp.add_parser("verify", help="verify an extracted Management directory against known original hashes without executing binaries"); x.add_argument("--management-root", required=True); x.set_defaults(func=cmd_legacy_management_verify)
    x = lmp.add_parser("item-code", help="classify an item code using the historical PriTaTor selector taxonomy"); x.add_argument("code"); x.set_defaults(func=cmd_legacy_management_item_code)

    la = sp.add_parser("legacy-authoring", help="Python-native replacement pipeline for legacy Item/Monster/NPC/Field tooling; no legacy EXE execution")
    lap = la.add_subparsers(dest="legacy_authoring_cmd", required=True)
    x = lap.add_parser("capabilities", help="show create/edit/publish capabilities and remaining code boundaries"); x.set_defaults(func=cmd_legacy_authoring_capabilities)
    x = lap.add_parser("inspect", help="inspect an Item/Monster/NPC/SPM/SPP/SPC source as an editable Python authoring document"); x.add_argument("--kind", required=True, choices=["ITEM","MONSTER","NPC","SPM","SPP","SPC"]); x.add_argument("--path", required=True); x.set_defaults(func=cmd_legacy_authoring_inspect)
    x = lap.add_parser("stage", help="stage a JSON authoring spec under pt_build without writing client/server"); x.add_argument("--spec", required=True); x.set_defaults(func=cmd_legacy_authoring_stage)
    x = lap.add_parser("publish", help=f"publish latest/specified staged authoring bundle; requires --confirm '{ASSET_BUNDLE_APPLY_CONFIRM}'"); x.add_argument("--manifest"); x.add_argument("--confirm", required=True); x.set_defaults(func=cmd_legacy_authoring_publish)
    x = lap.add_parser("restore", help=f"restore latest/specified authoring bundle; requires --confirm '{ASSET_BUNDLE_RESTORE_CONFIRM}'"); x.add_argument("--manifest"); x.add_argument("--confirm", required=True); x.set_defaults(func=cmd_legacy_authoring_restore)

    audit = sp.add_parser("audit"); audp = audit.add_subparsers(dest="audit_cmd", required=True)
    x = audp.add_parser("physique", help="audit canonical Model0.62 files for mixed Physique/static object modes"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_physique)
    x = audp.add_parser("client-enrichment", help="read-only client enrichment: entity closure, registry relations, validation coverage and actionable gaps; writes only pt_build/client_enrichment")
    x.set_defaults(func=cmd_audit_client_enrichment)
    x = audp.add_parser("server-inventory", help="read-only full server tree census classified by path/lifecycle; persistence, logs and security state are excluded from assets"); x.add_argument("--progress-every", type=int, default=10000); x.add_argument("--sample-limit", type=int, default=12); x.set_defaults(func=cmd_audit_server_inventory)
    x = audp.add_parser("server-bundles", help="read-only Monster/NPC bundle census: literal model/name refs, logical INI->INX resolution across server/client; no authoring certification"); x.add_argument("--progress-every", type=int, default=250); x.add_argument("--sample-limit", type=int, default=40); x.set_defaults(func=cmd_audit_server_bundles)
    x = audp.add_parser("server-fields", help="read-only field bundle census: SPM/SPP/SPC companions, canonical Summit sizes and basename stage candidates; ambiguous/mismatched layouts stay REVIEW"); x.add_argument("--sample-limit", type=int, default=50); x.set_defaults(func=cmd_audit_server_fields)
    x = audp.add_parser("server-items", help="read-only OpenItem census: CODE identity, ZHOON presence and duplicate-code conflicts; client catalog/DorpItem closure remains explicitly out of scope"); x.add_argument("--progress-every", type=int, default=250); x.add_argument("--sample-limit", type=int, default=50); x.set_defaults(func=cmd_audit_server_items)
    x = audp.add_parser("legacy-management", help="cross-check historical PriTaTor/NPCManager workflows against current server OpenItem/Monster/NPC/SPM evidence; read-only")
    x.add_argument("--management-root", help="optional extracted original Management directory for SHA-256 verification")
    x.add_argument("--tutorial-root", help="optional extracted @Tutoriais directory for item-code evidence")
    x.add_argument("--sample-limit", type=int, default=80)
    x.set_defaults(func=cmd_audit_legacy_management)
    x = audp.add_parser("source-contracts", help="read-only C/C++ source evidence census: sound maps, player-class job gates and source-proven item/field format relations; no hashes/copies")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback PT_SOURCE_ROOT or project config")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback PT_REFERENCE_SOURCE_ROOT or project config")
    x.set_defaults(func=cmd_audit_source_contracts)
    x = audp.add_parser("player-class-contracts", help="source-backed 10-class contract coverage graph: UI assets, class audio family, handler sound/particle/animation evidence, runtime migration and transitive .part dependencies; read-only, no hashes/copies")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback PT_SOURCE_ROOT or project config")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback PT_REFERENCE_SOURCE_ROOT or project config")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="optional read-only donor client root; repeatable (e.g. OFFICIAL=/path/to/donor/client)")
    x.add_argument("--class", dest="class_name", action="append", choices=TARGET_CLASSES, help="audit one class; repeatable; default all 10")
    x.set_defaults(func=cmd_audit_player_class_contracts)
    x = audp.add_parser("enrichment-plan", help="run Summit Asset Enrichment v9 PLAN mode using current client/server roots and only donor roots that exist; writes manifest only under pt_build"); x.add_argument("--timeout", type=float, default=180.0); x.set_defaults(func=cmd_audit_enrichment_plan)
    x = audp.add_parser("enrichment-graph", help="build the Asset Enrichment v9 client/server dependency graph under pt_build; source roots remain read-only"); x.add_argument("--skip-client-scan", action="store_true"); x.add_argument("--timeout", type=float, default=240.0); x.set_defaults(func=cmd_audit_enrichment_graph)
    x = audp.add_parser("class-ui-aliases", help="read-only class skill-UI alias audit; detects split roots such as Mecha/Mechanician and never moves/deletes client files")
    x.set_defaults(func=cmd_audit_class_ui_aliases)
    x = audp.add_parser("general-asset-census", help="plan-only general client/server reachability census; separates donor gaps from runtime-reachable dependencies and never writes target roots")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback config/discovery")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback config/discovery")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="read-only donor client root; repeatable; persisted donors used when omitted")
    x.add_argument("--donor-server", action="append", default=[], metavar="LABEL=PATH", help="read-only donor server root; repeatable; persisted donors used when omitted")
    x.set_defaults(func=cmd_audit_general_asset_census)
    x = audp.add_parser("t5-assets", help="fresh plan-only Tier-5 effect+audio asset readiness; gameplay functionality is assumed externally, while current asset calls must resolve to target or CLOSED same-lineage bundles")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback config/discovery")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback config/discovery")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="read-only donor client root; repeatable; persisted donors used when omitted")
    x.add_argument("--donor-server", action="append", default=[], metavar="LABEL=PATH", help="read-only donor server root; repeatable; persisted donors used when omitted")
    x.set_defaults(func=cmd_audit_t5_assets)
    x = audp.add_parser("t5-effects", help="compatibility alias for the Tier-5 effect+audio asset readiness audit")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback config/discovery")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback config/discovery")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="read-only donor client root; repeatable; persisted donors used when omitted")
    x.add_argument("--donor-server", action="append", default=[], metavar="LABEL=PATH", help="read-only donor server root; repeatable; persisted donors used when omitted")
    x.set_defaults(func=cmd_audit_t5_effects)
    x = audp.add_parser("binding-coverage", help="summarize rigid binding readiness and unresolved config-only reasons without promoting guesses"); x.add_argument("--category"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_binding_coverage)
    x = audp.add_parser("inx-writer-corpus", help="read-only byte-preservation audit for candidate INX MotionInfo writer"); x.add_argument("--prefix", action="append", help="client-relative subtree to scan; repeatable (default char/npc + char/monster)"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_inx_writer_corpus)
    x = audp.add_parser("smb-writer-corpus", help="read-only byte-preservation audit for candidate SMB existing-key writer"); x.add_argument("--prefix", action="append", help="client-relative subtree to scan; repeatable (default char/npc + char/monster)"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_smb_writer_corpus)
    x = audp.add_parser("inx-writer-edit-corpus", help="temp-output corpus probe: perform one allowlisted existing MotionInfo edit per INX without modifying the client"); x.add_argument("--prefix", action="append"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_inx_writer_edit_corpus)
    x = audp.add_parser("smb-writer-edit-corpus", help="temp-output corpus probe: perform one existing-key edit per editable SMB without modifying the client"); x.add_argument("--prefix", action="append"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_smb_writer_edit_corpus)
    x = audp.add_parser("motion-writer-semantic-edit-corpus", help="temp-edit registry-proven INX/SMB contexts and require source-side animation evaluation to remain valid; not Blender/runtime certification"); x.add_argument("--pair-limit", type=int, default=0); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_motion_writer_semantic_edit_corpus)
    x = audp.add_parser("object-local-writer-corpus", help="temp-edit existing static Model0.62 object-local ROT/POS/SCALE keys and require byte-preserving reparse; ROT rebuilds cumulative TmPrevRot"); x.add_argument("--sample-limit", type=int, default=25); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_object_local_writer_corpus)
    x = audp.add_parser("rigid-model-info-contexts", help="classify rigid assets with multiple INX model-info configs as semantically equivalent or fail-closed ambiguous using full LOD groups + skeleton"); x.add_argument("--category"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_rigid_model_info_contexts)
    x = audp.add_parser("rigid-authoring-certification-plan", help="show canonical profile/LOD/object coverage for verified controlled rigid candidate edits plus human visual reviews; never promotes production"); x.add_argument("--profile"); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_rigid_authoring_certification_plan)
    x = audp.add_parser("development-readiness", help="summarize current implementation maturity, evidence and remaining blockers; --deep reruns read-only INX/SMB/animation corpus gates"); x.add_argument("--deep", action="store_true"); x.add_argument("--prefix", action="append", help="deep writer corpus subtree; repeatable (default char/npc + char/monster)"); x.add_argument("--animation-pair-limit", type=int, default=0, help="deep-mode debug cap; zero audits all unique animation contexts"); x.add_argument("--sample-limit", type=int, default=25); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_development_readiness)
    x = audp.add_parser("release-1-coverage", help="cross product of Release 1.0 content domains and required technical capabilities; read-only planning matrix"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_release_1_coverage)
    x = audp.add_parser("model062-authoring", help="classify physical Model0.62 assets by current saved-Blender authoring maturity without writing the client"); x.add_argument("--category"); x.add_argument("--include-missing", action="store_true", help="include registry assets whose physical source is absent from the configured client"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_model062_authoring)
    x = audp.add_parser("animation-source", help="source-side INX/SMB motion regression; diagnostic, not visual certification"); x.add_argument("target", help="rigid asset id/path with resolved animation binding"); x.add_argument("--mode", choices=("core","all"), default="core"); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_animation_source)
    x = audp.add_parser("animation-corpus", help="deduplicated source-side regression of registry-proven INX/SMB motion contexts"); x.add_argument("--category"); x.add_argument("--mode", choices=("core","all"), default="core"); x.add_argument("--pair-limit", type=int, default=0, help="debug/quick-run cap; zero audits every unique physical context"); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_animation_corpus)
    x = audp.add_parser("animation-certification-plan", help="build a deterministic human Blender review queue across proven INX/SMB contexts; does not open Blender or certify automatically"); x.add_argument("--category"); x.add_argument("--context-limit", type=int, default=0); x.add_argument("--motions-per-context", type=int, default=3); x.add_argument("--sample-limit", type=int, default=50); x.add_argument("--output", help="optional JSON report under pt_build"); x.set_defaults(func=cmd_audit_animation_certification_plan)
    x = audp.add_parser("object-local", help="discover static Model0.62 files with serialized object-local transform arrays"); x.add_argument("--limit", type=int, default=50); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_object_local)
    x = audp.add_parser("object-local-corpus", help="physically audit all object-local candidates for hierarchy/segmented subtypes"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing only rare subtype representatives"); x.add_argument("--per-subtype", type=int, default=3); x.set_defaults(func=cmd_audit_object_local_corpus)
    x = audp.add_parser("texlink-corpus", help="physically audit Model0.62 multilayer TexLink chains and collect representative SMD/textures"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing representative SMDs plus referenced textures"); x.add_argument("--per-profile", type=int, default=2); x.set_defaults(func=cmd_audit_texlink_corpus)
    x = audp.add_parser("texlink-semantics", help="audit exact hTexture->smTexture stage mapping and material stage/form profiles"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing representatives for every semantic profile"); x.add_argument("--per-profile", type=int, default=2); x.set_defaults(func=cmd_audit_texlink_semantics)
    x = audp.add_parser("stage072-corpus", help="physically audit all SMD Stage data Ver 0.72 files from the canonical inventory"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing structural/capability representatives"); x.add_argument("--per-profile", type=int, default=2); x.set_defaults(func=cmd_audit_stage072_corpus)
    x = audp.add_parser("stage072-stagearea", help="prove StageArea/StageMapRect reconstruction from physical Stage0.72 geometry"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing StageArea boundary representatives"); x.set_defaults(func=cmd_audit_stage072_stagearea)
    x = audp.add_parser("stage072-normals", help="audit physical Stage0.72 VectNormal generation families before geometry writing"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing all legacy-normal files plus current controls"); x.set_defaults(func=cmd_audit_stage072_normals)
    x = audp.add_parser("stage072-textures", help="audit physical presence of textures referenced by face-used Stage0.72 materials"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing SMDs with missing client texture references plus manifest"); x.set_defaults(func=cmd_audit_stage072_textures)
    x = audp.add_parser("rare-outliers", help="prove the physical families of the 18 canonical reverse-engineering outliers and classify remaining TGA exceptions"); x.add_argument("--output", help="optional full JSON report path"); x.add_argument("--bundle", help="optional ZIP containing all 18 outliers plus anomalous TGA files and diagnostic manifest"); x.set_defaults(func=cmd_audit_rare_outliers)
    x = audp.add_parser("rare-support", help="prepare and verify the 16 physically-proven usable rare outliers without modifying client files"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_support)
    x = audp.add_parser("rare-rigid-context", help="classify Physique/binding context for the six rare Model0.62 files before Blender preview integration"); x.add_argument("--output", help="optional JSON report path"); x.add_argument("--bundle", help="optional ZIP with rare SMDs, exact INX/INF context and standard peer controls"); x.set_defaults(func=cmd_audit_rare_rigid_context)
    x = audp.add_parser("rare-rigid-binding", help="resolve the six rare rigid Model0.62 files through verified serialized INX LinkFile targets"); x.add_argument("--output", help="optional JSON report path"); x.add_argument("--bundle", help="optional ZIP with source INX, verified target INX, motion SMB and physical root-model evidence"); x.set_defaults(func=cmd_audit_rare_rigid_binding)
    x = audp.add_parser("rare-rigid-preview", help="automatically import/check all six proven rare rigid Model0.62 files in their verified Blender binding context"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_preview)
    x = audp.add_parser("rare-rigid-geometry", help="audit fixed-point Physique inverse loss and single-bone/mixed-bone geometry write preconditions for the six rare rigid files"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_geometry)
    x = audp.add_parser("rare-rigid-geometry-roundtrip", help="certify the first interior single-bone Model0.62 position writer with locked historical normal vector and byte-exact untouched data"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_roundtrip)
    x = audp.add_parser("rare-rigid-normal-roundtrip", help="certify affected-vertex normal updates through a historical-residual plus current SourceCode SetGNormals delta bridge"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_normal_roundtrip)
    x = audp.add_parser("rare-rigid-extent-roundtrip", help="certify monotonic outward Model0.62 single-bone bound expansion while preserving historical normal provenance and all non-authorized bytes"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_extent_roundtrip)
    x = audp.add_parser("rare-rigid-multibone", help="audit at_dragon mixed-bone changed-normal provenance using each affected vertex's own Physique bone transform; no writes"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_multibone)
    x = audp.add_parser("rare-rigid-multibone-roundtrip", help="certify the per-edit guarded at_dragon multibone position/normal writer on 2-, 3- and 4-bone representatives; interior only"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_multibone_roundtrip)
    x = audp.add_parser("rare-rigid-edit-workflow", help="certify atomic 2/3/4-vertex saved-Blender transactions with joint final-geometry normal guards"); x.add_argument("--output", help="optional JSON report path"); x.set_defaults(func=cmd_audit_rare_rigid_edit_workflow)
    x = sp.add_parser("bindings"); x.add_argument("--category"); x.add_argument("--mode"); x.add_argument("--limit", type=int, default=100); x.add_argument("--discover", metavar="ASSET", help="resolve config-only binding; verified INX LinkFile is authoritative before legacy discovery fallbacks"); x.add_argument("--candidate-limit", type=int, default=0, help="debug only: cap skeleton-signature groups; zero means all"); x.add_argument("--full-scan", action="store_true", help="continue even after two distinct skeleton signatures pass"); x.add_argument("--no-resume", action="store_true", help="ignore previous per-candidate probe state"); x.set_defaults(func=cmd_bindings)

    aggregate = sp.add_parser("aggregate", help="build fail-closed staging overlays from source-backed asset contracts; never writes target client/server")
    agp = aggregate.add_subparsers(dest="aggregate_cmd", required=True)
    x = agp.add_parser("player-classes", help="aggregate contract-reachable assets for one or all player classes into pt_build staging overlay")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback config/discovery")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback config/discovery")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="read-only donor client root; repeatable; persisted donors used when omitted")
    x.add_argument("--class", dest="class_name", action="append", choices=TARGET_CLASSES, help="aggregate one class; repeatable; default all 10")
    x.add_argument("--plan-only", action="store_true", help="create manifest/review queues without copying recoverable files into the staging overlay")
    x.set_defaults(func=cmd_aggregate_player_classes)

    x = agp.add_parser("client-superset", help="stage every target-missing deployable asset/data file from donor clients; preserve variants/reference-only files")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="read-only donor client root; repeatable; persisted/autodiscovered donors used when omitted")
    x.add_argument("--plan-only", action="store_true", help="build reports without copying files into staging")
    x.set_defaults(func=cmd_aggregate_client_superset)

    x = agp.add_parser("server-superset", help="stage target-missing server data from donor servers; excludes runtime/log state and binaries")
    x.add_argument("--donor-server", action="append", default=[], metavar="LABEL=PATH", help="read-only donor server root; repeatable; persisted/autodiscovered donors used when omitted")
    x.add_argument("--plan-only", action="store_true", help="build reports without copying files into staging")
    x.set_defaults(func=cmd_aggregate_server_superset)

    x = agp.add_parser("summit-superset", help="combined 10-class contract + client superset + server superset staging run; emits one small reports_bundle.zip")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback config/discovery")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback config/discovery")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="read-only donor client root; repeatable")
    x.add_argument("--donor-server", action="append", default=[], metavar="LABEL=PATH", help="read-only donor server root; repeatable")
    x.add_argument("--plan-only", action="store_true", help="build all reports without copying files into staging")
    x.set_defaults(func=cmd_aggregate_summit_superset)

    recover = sp.add_parser("recover", help="scope-locked recovery of fresh CLOSED reachability bundles; broad deployment remains disabled")
    rcp = recover.add_subparsers(dest="recover_cmd", required=True)
    x = rcp.add_parser("general-closed-bundles", help="rerun the general census, require the exact expected CLOSED roots, stage verified donor members and optionally create missing target files")
    x.add_argument("--source-root", required=False, help="current Summit C/C++ source root; fallback config/discovery")
    x.add_argument("--reference-source-root", required=False, help="EU reference C/C++ source root; fallback config/discovery")
    x.add_argument("--donor-client", action="append", default=[], metavar="LABEL=PATH", help="read-only donor client root; repeatable; persisted donors used when omitted")
    x.add_argument("--donor-server", action="append", default=[], metavar="LABEL=PATH", help="read-only donor server root; repeatable; persisted donors used when omitted")
    x.add_argument("--expected-root", action="append", default=[], metavar="SIDE:PATH", help="exact authorized recovery root; repeatable; --apply refuses to run without this scope lock")
    x.add_argument("--apply", action="store_true", help="create only the missing files in client/server roots after fresh scope/closure checks; never overwrites existing files")
    x.set_defaults(func=cmd_recover_general_closed_bundles)

    x = rcp.add_parser("class-ui-alias-only", help="scope-locked create-only canonicalization of fresh ALIAS_ONLY class skill-UI files; never deletes alias files or touches conflicts")
    x.add_argument("--expected-group", required=True, help="exact class UI alias group ID, e.g. MECHANICIAN_SKILL_UI")
    x.add_argument("--expected-path", action="append", default=[], metavar="CLIENT_LOGICAL_PATH", help="exact fresh ALIAS_ONLY canonical destination; repeatable; --apply requires exact scope equality")
    x.add_argument("--apply", action="store_true", help="create only the missing canonical files after staging/hash verification; never overwrites or deletes")
    x.set_defaults(func=cmd_recover_class_ui_alias_only)

    assets = sp.add_parser("assets"); asp = assets.add_subparsers(dest="assets_cmd", required=True)
    x = asp.add_parser("list"); x.add_argument("--category"); x.add_argument("--family"); x.add_argument("--ext"); x.add_argument("--visual-only", action="store_true"); x.add_argument("--gates", action="store_true", help="show structural/visual/animation certification columns"); x.add_argument("--limit", type=int, default=50); x.set_defaults(func=cmd_assets_list)

    asset = sp.add_parser("asset"); ap = asset.add_subparsers(dest="asset_cmd", required=True)
    x = ap.add_parser("inspect"); x.add_argument("target"); x.add_argument("--physical", action="store_true"); x.set_defaults(func=cmd_asset_inspect)
    x = ap.add_parser("authoring", help="show per-channel authoring maturity, blockers and generic-import workspace provenance"); x.add_argument("target"); x.set_defaults(func=cmd_asset_authoring)
    x = ap.add_parser("motions"); x.add_argument("target"); x.set_defaults(func=cmd_asset_motions)
    x = ap.add_parser("heads"); x.add_argument("target"); x.add_argument("--limit", type=int, default=50); x.set_defaults(func=cmd_asset_heads)
    x = ap.add_parser("head-tiers"); x.add_argument("target", help="body/armor asset"); x.add_argument("--head", required=True, help="one head asset from the desired appearance family"); x.set_defaults(func=cmd_asset_head_tiers)
    x = ap.add_parser("object-local"); x.add_argument("target", help="static Model0.62 asset"); x.set_defaults(func=cmd_asset_object_local)
    x = ap.add_parser("texlinks"); x.add_argument("target", help="Model0.62 asset with possible chained TexLinks"); x.set_defaults(func=cmd_asset_texlinks)
    x = ap.add_parser("texlink-semantics"); x.add_argument("target", help="Model0.62 asset with chained TexLinks"); x.set_defaults(func=cmd_asset_texlink_semantics)
    x = ap.add_parser("material-candidate", help="candidate-only fixed-size Model0.62/Stage0.72 material field edit; output remains under pt_build")
    x.add_argument("target", help="Model0.62 or Stage0.72 asset id/path")
    x.add_argument("--material-index", type=int, default=0)
    x.add_argument("--set", dest="set_values", action="append", required=True, metavar="FIELD=VALUE", help="repeatable allowlisted field edit: texture_type, blend_type, shade, two_side, transparency, self_illum")
    x.add_argument("--output", help="optional output path; must remain under pt_build")
    x.set_defaults(func=cmd_asset_material_candidate)

    x = sp.add_parser("import", help="prepare a reusable Blender workspace through a proven family adapter; never writes the client")
    x.add_argument("target", help="supported asset id/path")
    x.add_argument("--lod", choices=("auto","high","default","low"), default="auto", help="rigid Model0.62 LOD selection")
    x.add_argument("--model-info", help="exact associated INX path when a rigid asset has multiple non-equivalent model-info configurations")
    x.add_argument("--skeleton", help="explicit SMB logical client path for rigid Physique assets without a usable model-info skeleton context; structural gate must PASS and context is persisted fail-closed")
    x.add_argument("--profile", help="canonical character profile id; resolves to an exact INX+skeleton+LOD context and is mutually exclusive with --model-info/--skeleton")
    x.add_argument("--motion", default="STAND", help="initial rigid Action state/index; case-insensitive (default STAND)")
    x.add_argument("--load-actions", choices=("all","selected","none"), default="all", help="rigid animation preview Actions: all (default), selected only, or none")
    x.add_argument("--open-mode", choices=("paint","animation"), default="paint", help="open stable paint/edit workspace (default) or separate animation preview")
    x.add_argument("--reset", action="store_true", help="discard the existing import workspace before rebuilding")
    x.add_argument("--no-open", action="store_true", help="prepare the Blender workspace without opening Blender interactively")
    x.set_defaults(func=cmd_import_asset)

    x = sp.add_parser("build", help="generic fail-closed build dispatcher; production routes only to certified writers; --candidate enables explicit pt_build-only static/rigid/mixed/Stage0.72 research writers")
    x.add_argument("target", help="asset id/path")
    x.add_argument("--plan", action="store_true", help="show production adapter plus per-channel authoring decision without building")
    x.add_argument("--candidate", action="store_true", help="run the explicit static/rigid/mixed/Stage0.72 saved-Blender candidate writer; output remains pt_build-only and never authorizes publish")
    x.add_argument("--stress-profile", action="store_true", help="rigid canonical-profile stress build: rewrite every HIGH/DEFAULT/LOW profile mesh from one saved Blender session, require every target to be genuinely edited, and review one combined candidate")
    x.add_argument("--object", help="target object for --candidate when more than one static/rigid object is eligible; Mixed rewrites its verified eligible set")
    x.add_argument("--require-edit", action="store_true", help="for static/rigid --candidate, fail unless the target object block differs from the source; useful for controlled manual Blender certification tests")
    x.add_argument("--output", help="optional output path; must remain under pt_build")
    x.set_defaults(func=cmd_build_asset)

    deploy = sp.add_parser("deploy", help="read-only deployment planning; no app-level client write is enabled")
    dpp = deploy.add_subparsers(dest="deploy_cmd", required=True)
    x = dpp.add_parser("plan", help="plan provenance/drift/backup/rollback requirements for a pt_build artifact; never writes the client")
    x.add_argument("target", help="asset id/path")
    x.add_argument("--artifact", help="candidate artifact under pt_build; omission shows the missing-artifact blocker")
    x.set_defaults(func=cmd_deploy_plan)
    x = dpp.add_parser("prepare", help="prepare a verified pt_build transaction snapshot/backup/staged artifact; still never writes the client")
    x.add_argument("target", help="asset id/path")
    x.add_argument("--artifact", required=True, help="artifact under pt_build")
    x.set_defaults(func=cmd_deploy_prepare)
    x = dpp.add_parser("verify", help="re-verify a prepared transaction and detect client/backup/staged-artifact drift; read-only")
    x.add_argument("manifest", help="pt_build deployment transaction.json")
    x.set_defaults(func=cmd_deploy_verify)
    x = dpp.add_parser("simulate", help="prove atomic replace/postwrite/rollback entirely inside the prepared pt_build transaction; never writes the client")
    x.add_argument("manifest", help="pt_build deployment transaction.json")
    x.add_argument("--inject-failure", choices=("postwrite",), help="inject a controlled failure after simulated replace and require rollback")
    x.set_defaults(func=cmd_deploy_simulate)
    x = dpp.add_parser("state", help="classify current client bytes as original source, known managed artifact, or unknown drift; read-only")
    x.add_argument("manifest", help="pt_build deployment transaction.json")
    x.set_defaults(func=cmd_deploy_state)
    x = dpp.add_parser("restore-plan", help="plan fail-closed restoration from verified backup; apply remains disabled")
    x.add_argument("manifest", help="pt_build deployment transaction.json")
    x.set_defaults(func=cmd_deploy_restore_plan)

    x = dpp.add_parser("workspace-prepare", help="build a complete model/texture/context deployment bundle from a verified generic Blender workspace; client remains unchanged")
    x.add_argument("target", help="imported Model0.62 asset id/path")
    x.add_argument("--textures-only", action="store_true", help="skip model candidate build and prepare only changed workspace textures/context")
    x.add_argument("--no-auto-rigid-weight-repair", action="store_true", help="strict mode: refuse rigid vertices that do not have exactly one bone group at weight 1.0 instead of automatically selecting one bone and serializing it at 1.0")
    x.set_defaults(func=cmd_deploy_workspace_prepare)
    x = dpp.add_parser("workspace-publish", help="prepare and atomically publish a verified workspace bundle with backup and automatic rollback")
    x.add_argument("target", help="imported Model0.62 asset id/path")
    x.add_argument("--textures-only", action="store_true", help="publish only changed workspace textures; model remains preserve-only")
    x.add_argument("--allow-partial-lod", action="store_true", help="explicitly allow publish when one or more runtime LODs cannot be safely serialized; uncovered LODs remain unchanged")
    x.add_argument("--no-auto-rigid-weight-repair", action="store_true", help="strict mode: refuse rigid vertices that do not have exactly one bone group at weight 1.0 instead of automatically selecting one bone and serializing it at 1.0")
    x.add_argument("--confirm", required=True, help=f"exact safety phrase: {WORKSPACE_BUNDLE_APPLY_CONFIRMATION}")
    x.set_defaults(func=cmd_deploy_workspace_publish)
    x = dpp.add_parser("workspace-check", help="re-check only the latest deployed bundle for one asset; no corpus-wide physical regression")
    x.add_argument("target", help="deployed Model0.62 asset id/path")
    x.set_defaults(func=cmd_deploy_workspace_check)
    x = dpp.add_parser("workspace-apply", help="apply a prepared workspace bundle transaction to the configured client")
    x.add_argument("manifest", help="pt_build workspace bundle transaction.json")
    x.add_argument("--confirm", required=True, help=f"exact safety phrase: {WORKSPACE_BUNDLE_APPLY_CONFIRMATION}")
    x.set_defaults(func=cmd_deploy_workspace_apply)
    x = dpp.add_parser("workspace-verify", help="verify bundle backups, staged artifacts and client drift")
    x.add_argument("manifest", help="pt_build workspace bundle transaction.json")
    x.add_argument("--allow-managed", action="store_true", help="accept already deployed managed artifact identities")
    x.set_defaults(func=cmd_deploy_workspace_verify)
    x = dpp.add_parser("workspace-state", help="classify tracked files as ORIGINAL, DEPLOYED or DRIFT")
    x.add_argument("manifest", help="pt_build workspace bundle transaction.json")
    x.set_defaults(func=cmd_deploy_workspace_state)
    x = dpp.add_parser("workspace-restore", help="restore an APPLIED_VERIFIED workspace bundle from its verified backup")
    x.add_argument("manifest", help="pt_build workspace bundle transaction.json")
    x.add_argument("--confirm", required=True, help=f"exact safety phrase: {WORKSPACE_BUNDLE_RESTORE_CONFIRMATION}")
    x.set_defaults(func=cmd_deploy_workspace_restore)
    x = dpp.add_parser("workspace-history", help="list retained workspace deployment transactions for an asset")
    x.add_argument("target", help="asset id/path")
    x.set_defaults(func=cmd_deploy_workspace_history)
    x = dpp.add_parser("workspace-restore-latest", help="restore all still-deployed files from the newest active verified bundle for an asset")
    x.add_argument("target", help="asset id/path")
    x.add_argument("--confirm", required=True, help=f"exact safety phrase: {WORKSPACE_BUNDLE_RESTORE_CONFIRMATION}")
    x.set_defaults(func=cmd_deploy_workspace_restore_latest)
    x = dpp.add_parser("workspace-restore-model-latest", help="manually remove only the deployed model from the newest active verified bundle; deployed textures remain untouched")
    x.add_argument("target", help="asset id/path")
    x.add_argument("--confirm", required=True, help=f"exact safety phrase: {WORKSPACE_BUNDLE_RESTORE_CONFIRMATION}")
    x.set_defaults(func=cmd_deploy_workspace_restore_model_latest)

    view = sp.add_parser("view", help="open certified asset previews with viewer-specific navigation helpers")
    vwp = view.add_subparsers(dest="view_cmd", required=True)
    x = vwp.add_parser("stage072", help="generate/verify a Stage0.72 preview and open a disposable floating-origin Blender view")
    x.add_argument("target", help="SMD Stage data Ver 0.72 asset id/path")
    x.set_defaults(func=cmd_view_stage072)
    x = vwp.add_parser("rare-model", help="open one of the six proven rare rigid Model0.62 pieces on its physically verified root/skeleton context")
    x.add_argument("target", help="rare SMD path or unique filename (ar0nass/Cartola*/at_dragon)")
    x.set_defaults(func=cmd_view_rare_model)
    x = vwp.add_parser("rigid-candidate", help="reimport a verified R12 rigid candidate artifact into a separate Blender review workspace; never writes the client")
    x.add_argument("target", help="rigid source asset id/path")
    x.add_argument("--artifact", required=True, help="R12 candidate SMD under pt_build with sibling .build.json")
    x.add_argument("--no-open", action="store_true", help="prepare/verify the candidate reimport review workspace without opening Blender")
    x.set_defaults(func=cmd_view_rigid_candidate)

    edit = sp.add_parser("edit", help="open guarded geometry edit workspaces without touching client assets")
    ewp = edit.add_subparsers(dest="edit_cmd", required=True)
    x = ewp.add_parser("rare-model", help="open at_dragon in the V0.8.9 guarded 1..4-vertex single-object multibone transaction workspace")
    x.add_argument("target", help="char/tmABCD/at_dragon.smd")
    x.add_argument("--reset", action="store_true", help="rebuild the persistent edit workspace from the physical source")
    x.set_defaults(func=cmd_edit_rare_model)

    write = sp.add_parser("write", help="write guarded edits to pt_build outputs; never modifies the client source")
    wwp = write.add_subparsers(dest="write_cmd", required=True)
    x = wwp.add_parser("rare-model", help="write 1..4 saved at_dragon vertex edits atomically only if the joint final-geometry guard passes")
    x.add_argument("target", help="char/tmABCD/at_dragon.smd")
    x.add_argument("--output", help="optional output SMD path; edit workspace stays under pt_build/blender_edits/rare_model")
    x.set_defaults(func=cmd_write_rare_model)
    x = wwp.add_parser("inx-motion", help="candidate MotionInfo writer to a new INX under pt_build; never modifies the client")
    x.add_argument("target", help="client-relative .inx path")
    x.add_argument("--motion", required=True, help="motion state name (STAND/WALK/...) or motion index")
    x.add_argument("--start", type=int, help="new logical start frame")
    x.add_argument("--end", type=int, help="new logical end frame")
    x.add_argument("--repeat", type=int, help="new repeat DWORD")
    x.add_argument("--key-code", type=int, help="new key-code byte (0..255)")
    x.add_argument("--motion-frame", type=int, help="new signed motion-frame/container slot")
    x.add_argument("--output", help="optional project-relative output path; must remain under pt_build")
    x.set_defaults(func=cmd_write_inx_motion)
    x = wwp.add_parser("smb-key", help="candidate existing-key SMB track writer to pt_build; no key insertion/deletion")
    x.add_argument("target", help="client-relative .smb path")
    x.add_argument("--bone", required=True, help="exact skeleton bone name")
    x.add_argument("--track", required=True, choices=("pos","rot","scale"))
    x.add_argument("--key-index", required=True, type=int)
    x.add_argument("--x", type=float); x.add_argument("--y", type=float); x.add_argument("--z", type=float); x.add_argument("--w", type=float)
    x.add_argument("--output", help="optional project-relative output path; must remain under pt_build")
    x.set_defaults(func=cmd_write_smb_key)
    x = wwp.add_parser("object-local-key-candidate", help="candidate static Model0.62 existing ROT/POS/SCALE key writer; rotation rebuilds cumulative TmPrevRot; pt_build only, no key insert/delete")
    x.add_argument("target", help="static Model0.62 asset id/path")
    x.add_argument("--object-index", required=True, type=int)
    x.add_argument("--channel", required=True, choices=("rot","pos","scale"))
    x.add_argument("--key-index", required=True, type=int)
    x.add_argument("--x", required=True, type=float); x.add_argument("--y", required=True, type=float); x.add_argument("--z", required=True, type=float); x.add_argument("--w", type=float, help="required only for --channel rot")
    x.add_argument("--output", help="optional project-relative output path; must remain under pt_build")
    x.set_defaults(func=cmd_write_object_local_key_candidate)

    paint = sp.add_parser("paint", help="open safe editable texture-paint workspaces without touching client textures")
    pwp = paint.add_subparsers(dest="paint_cmd", required=True)
    x = pwp.add_parser("stage072", help="open Stage0.72 in normalized floating-origin Texture Paint with private texture copies")
    x.add_argument("target", help="SMD Stage data Ver 0.72 asset id/path")
    x.add_argument("--stage", type=int, default=0, choices=range(0, 8), help="TexLink stage to paint (default 0)")
    x.add_argument("--reset", action="store_true", help="discard the existing private paint workspace before opening")
    x.set_defaults(func=cmd_paint_stage072)

    val = sp.add_parser("validate"); vp = val.add_subparsers(dest="val_cmd", required=True)
    x = vp.add_parser("structural"); x.add_argument("target"); x.set_defaults(func=cmd_validate_structural)
    x = vp.add_parser("inx-roundtrip", help="byte-exact no-op MotionInfo re-encode proof for MODERN_172/LEGACY_120 INX")
    x.add_argument("target", help="client-relative .inx path")
    x.set_defaults(func=cmd_validate_inx_roundtrip)
    x = vp.add_parser("smb-track-roundtrip", help="byte-exact no-op rewrite proof for existing SMB rot/pos/scale/PrevRot records")
    x.add_argument("target", help="client-relative .smb path")
    x.set_defaults(func=cmd_validate_smb_track_roundtrip)
    x = vp.add_parser("stage072-preview", help="automatic Stage0.72 Blender geometry/UV/color/light transport gate"); x.add_argument("target", help="SMD Stage data Ver 0.72 asset id/path"); x.set_defaults(func=cmd_validate_stage072_preview)
    x = vp.add_parser("stage072-roundtrip", help="strict Stage0.72 UV writer/roundtrip; preserves geometry, StageArea, materials, lights and opaque suffix byte-identically"); x.add_argument("target", help="SMD Stage data Ver 0.72 asset id/path"); x.add_argument("--uv-delta", type=float, default=0.03125); x.set_defaults(func=cmd_validate_stage072_roundtrip)
    x = vp.add_parser("stage072-geometry-roundtrip", help="strict Stage0.72 geometry witness with normal provenance bridge; rebuilds changed-face VectNormal, StageArea and StageMapRect"); x.add_argument("target", help="SMD Stage0.72 asset id/path"); x.add_argument("--delta-world", type=float, default=64.0, help="intentional X witness move in world units (default 64; must map to 1/256 grid)"); x.set_defaults(func=cmd_validate_stage072_geometry_roundtrip)
    x = vp.add_parser("visual"); x.add_argument("target", help="asset id/path, or 'next'"); x.add_argument("--category"); x.add_argument("--lod", choices=("auto","high","default","low"), default="auto"); x.set_defaults(func=cmd_validate_visual)
    x = vp.add_parser("roundtrip"); x.add_argument("target", help="static Model0.62 asset id/path"); x.add_argument("--witness-strength", type=float, default=0.08, help="intentional radial vertex edit as bbox fraction (default 0.08)"); x.set_defaults(func=cmd_validate_roundtrip)
    x = vp.add_parser("object-local"); x.add_argument("target", help="static Model0.62 asset with object-local transform keys"); x.add_argument("--fps", type=int, default=30); x.set_defaults(func=cmd_validate_object_local)
    x = vp.add_parser("texlinks"); x.add_argument("target", help="Model0.62 asset with two-stage TexLink chains"); x.add_argument("--lod", choices=("auto","high","default","low"), default="auto"); x.set_defaults(func=cmd_validate_texlinks)
    x = vp.add_parser("texlink-roundtrip", help="automatic strict NextTex/hTexture + per-layer UV roundtrip witness"); x.add_argument("target", help="Model0.62 asset with two-stage TexLink chains"); x.add_argument("--lod", choices=("auto","high","default","low"), default="auto"); x.add_argument("--uv-delta", type=float, default=0.03125, help="intentional stage-1 U witness delta (default 0.03125)"); x.set_defaults(func=cmd_validate_texlink_roundtrip)
    x = vp.add_parser("animation"); x.add_argument("target", help="asset id/path, or 'next'"); x.add_argument("--category"); x.add_argument("--lod", choices=("auto","high","default","low"), default="auto"); x.add_argument("--motion", default="auto", help="auto, state name (case-insensitive: STAND/stand/Stand), or motion index"); x.add_argument("--load-actions", choices=("selected","core","all"), default="all", help="all (default, persistent workspace with every active Action), selected (only requested motion), or core (legacy subset)"); x.add_argument("--fps", type=int, default=30); x.add_argument("--head", default="auto", help="auto assembles verified heads only for CHARACTER assets; non-character assets default to monolithic/no head; use none or an exact verified head path/id to override"); x.add_argument("--head-tier", default="auto", help="auto/base/0, a/1, b/2, c/3, d/4, or t; suffix only selects art after root compatibility is verified"); x.set_defaults(func=cmd_validate_animation)
    x = vp.add_parser("rigid-profile-auto", help="fully automated Blender/dev writer stress for canonical rigid profiles: deterministic edits across HIGH/DEFAULT/LOW, combined candidate build, and headless reimport checks; pt_build only")
    g = x.add_mutually_exclusive_group(required=True); g.add_argument("--profile"); g.add_argument("--all", action="store_true")
    x.add_argument("--amplitude", type=float, default=0.12, help="deterministic mesh deformation amplitude in Blender units (default 0.12)")
    x.set_defaults(func=cmd_validate_rigid_profile_auto)
    x = vp.add_parser("environment-auto", help="fast automatic environment preflight: client/inventory consistency, pt_build isolation and certified hashes; Blender bridge is reported as an optional capability; never writes client")
    x.add_argument("--blender-timeout", type=float, default=60.0, help="headless Blender environment probe timeout in seconds (default 60)")
    x.set_defaults(func=cmd_validate_environment_auto)
    x = vp.add_parser("server-environment-auto", help="fast read-only server-root preflight: lifecycle separation, static/shared-3D samples, client/server shared-path evidence, and no server writes")
    x.set_defaults(func=cmd_validate_server_environment_auto)
    x = vp.add_parser("server-design-auto", help="read-only server design catalog gate: environment + Monster/NPC + field + OpenItem bundle censuses; no server/client writes")
    x.set_defaults(func=cmd_validate_server_design_auto)
    x = vp.add_parser("physical-regression-auto", help="focused physical regression gate for fixes discovered by the first complete client run; runs exact historical witnesses plus current per-domain representatives; never writes client")
    x.add_argument("--fps", type=int, default=30)
    x.add_argument("--environment-blender-timeout", type=float, default=60.0, help="environment preflight Blender bridge timeout in seconds")
    x.add_argument("--rigid-operation-timeout", type=float, default=180.0, help="per Blender/writer operation timeout inside rigid_regressions; timed-out assets fail closed and the batch continues")
    x.add_argument("--smb-sample-limit", type=int, default=25, help="per-domain SMB writer regression sample size for MONSTER/EFFECT (default 25)")
    x.set_defaults(func=cmd_validate_physical_regression_auto)
    x = vp.add_parser("integration-regression-auto", help="focused client+server regression gate for affine animation, exact SMB/TGA outliers and Asset Enrichment bundle parsers; skips already-green material/rigid/static breadth")
    x.add_argument("--fps", type=int, default=30)
    x.add_argument("--environment-blender-timeout", type=float, default=60.0, help="client environment Blender bridge timeout in seconds")
    x.add_argument("--affine-blender-timeout", type=float, default=90.0, help="per-operation Blender timeout for the synthetic affine save/reopen self-test")
    x.set_defaults(func=cmd_validate_integration_regression_auto)
    x = vp.add_parser("release-1-auto", help="single automatic Release 1.0 development gate across real content-domain representatives; Blender/headless + writer/corpus/codec checks, never writes client")
    x.add_argument("--rigid-per-domain", type=int, default=3)
    x.add_argument("--static-per-domain", type=int, default=3)
    x.add_argument("--object-local-limit", type=int, default=4)
    x.add_argument("--texlink-limit", type=int, default=4)
    x.add_argument(
        "--motion-pair-limit", type=int, default=0,
        help="limit motion semantic edit contexts (0 = full corpus; Release 1.0 PASS requires the full corpus)",
    )
    x.add_argument("--fps", type=int, default=30)
    x.add_argument("--environment-blender-timeout", type=float, default=60.0, help="preflight Blender bridge timeout in seconds before the Release 1.0 gate starts")
    x.add_argument(
        "--motion-semantic-timeout", type=float, default=120.0,
        help="per-writer watchdog in seconds for each INX/SMB semantic context (default 120; timeout fails that context and continues)",
    )
    x.add_argument(
        "--resume", action="store_true",
        help="reuse exact PASS Blender batches plus SHA-validated completed motion-semantic checkpoints in this app/pt_build; physical corpus audits are rerun",
    )
    x.set_defaults(func=cmd_validate_release_1_auto)

    diag = sp.add_parser("diagnose"); dp = diag.add_subparsers(dest="diag_cmd", required=True)
    x = dp.add_parser("animation"); x.add_argument("target", help="asset id/path"); x.add_argument("--lod", choices=("auto","high","default","low"), default="auto"); x.add_argument("--motion", default="ATTACK", help="state name or motion index"); x.add_argument("--load-actions", choices=("selected","core","all"), default="selected"); x.add_argument("--fps", type=int, default=30); x.set_defaults(func=cmd_diagnose_animation)
    x = dp.add_parser("motion-source"); x.add_argument("target", help="asset id/path"); x.add_argument("--motion", default="STAND", help="state name or motion index"); x.set_defaults(func=cmd_diagnose_motion_source)
    x = dp.add_parser("motion-segment"); x.add_argument("target", help="asset id/path"); x.add_argument("--motion", default="STAND", help="state name or motion index"); x.set_defaults(func=cmd_diagnose_motion_segment)

    cert = sp.add_parser("certification"); cp = cert.add_subparsers(dest="cert_cmd", required=True)
    x = cp.add_parser("list"); x.add_argument("--asset"); x.add_argument("--latest", action="store_true"); x.add_argument("--limit", type=int, default=100); x.set_defaults(func=cmd_cert_list)
    x = cp.add_parser("record"); x.add_argument("target"); x.add_argument("--test", required=True); x.add_argument("--layer", default="HUMAN_VISUAL"); x.add_argument("--result", required=True, choices=("PASS","FAIL","SKIP")); x.add_argument("--notes"); x.set_defaults(func=cmd_cert_record)
    x = cp.add_parser("rigid-candidate-review", help="verify a pt_build rigid candidate + provenance and record automatic controlled-edit evidence plus an explicit human review; never authorizes runtime/production"); x.add_argument("target"); x.add_argument("--artifact", required=True, help="candidate SMD under pt_build; sibling .build.json must contain R12 controlled-edit evidence; run `view rigid-candidate` first"); x.add_argument("--result", required=True, choices=("PASS","FAIL","SKIP")); x.add_argument("--notes"); x.set_defaults(func=cmd_cert_rigid_candidate_review)
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    try:
        return int(a.func(a) or 0)
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"pt_asset_error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
