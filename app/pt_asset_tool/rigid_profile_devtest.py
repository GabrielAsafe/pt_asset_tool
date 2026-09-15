from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .authoring import authoring_plan, build_selected_authoring_context, verify_selected_context_for_asset
from .build_provenance import sha256_file, write_build_provenance
from .profile_authoring import plan_profile_authoring_context
from .rigid_authoring_candidate import build_rigid_candidate_blender_command
from .rigid_authoring_stress import inspect_rigid_profile_stress_scope, validate_rigid_profile_stress_output
from .static_roundtrip import _parse as parse_model062_bytes
from .utils import run_logged
from .validation import ValidationContext, ValidationRunner

FORMAT = "PT_RIGID_PROFILE_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT = "PT_RIGID_PROFILE_AUTOMATED_DEVTEST_BATCH_V1"


def _work_root(project_root: pathlib.Path, profile_id: str) -> pathlib.Path:
    return pathlib.Path(project_root).resolve() / "pt_build" / "devtest" / "rigid_profile_auto" / str(profile_id)


def _compact_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": step.get("index"),
        "object": step.get("object"),
        "lod": step.get("lod"),
        "input_sha256": step.get("input_sha256"),
        "output_sha256": step.get("output_sha256"),
        "source_counts": step.get("source_counts"),
        "output_counts": step.get("output_counts"),
        "topology_changed": step.get("topology_changed"),
        "unrelated_object_blocks_byte_identical": step.get("unrelated_object_blocks_byte_identical"),
        "max_vertex_fit_error": step.get("max_vertex_fit_error"),
    }


def run_rigid_profile_automated_devtest(
    settings,
    asset_registry,
    resolver,
    certifications,
    profile_registry,
    profile_id: str,
    *,
    amplitude: float = 0.12,
) -> dict[str, Any]:
    profile = profile_registry.get(profile_id)
    profile_plan = plan_profile_authoring_context(
        profile_registry, profile.profile_id, resolver, asset_registry, lod="default"
    )
    if profile_plan.get("status") != "READY":
        raise RuntimeError(f"profile authoring context blocked: {profile_plan.get('errors')}")
    asset = asset_registry.resolve(profile_plan["asset"])
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"automated rigid profile devtest requires rigid Model0.62, got {asset.family}")

    project_root = pathlib.Path(settings.project_root).resolve()
    work = _work_root(project_root, profile.profile_id)
    if work.exists():
        shutil.rmtree(work)
    import_work = work / "01_import"
    edit_work = work / "02_edit"
    build_work = work / "03_candidate"
    reimport_work = work / "04_reimport"
    for p in (import_work, edit_work, build_work, reimport_work):
        p.mkdir(parents=True, exist_ok=True)

    runner = ValidationRunner(ValidationContext(settings, resolver, certifications))
    runner.structural(asset)
    overlay, texture_report = runner._texture_overlay(asset, import_work)
    preselected = runner._preflight_rigid_import(
        asset, "default", model_info=profile_plan["model_info_inx"], require_unambiguous=True
    )
    source, pristine, actual_lod, cfg = runner._prepare_rigid_blend(
        asset, "default", import_work, overlay,
        model_info=profile_plan["model_info_inx"], require_unambiguous=True, preselected=preselected,
    )
    model_info = pathlib.Path(resolver.resolve(profile_plan["model_info_inx"], required=True)).resolve()
    skeleton = pathlib.Path(resolver.resolve(profile_plan["skeleton_smb"], required=True)).resolve()
    selected_context = build_selected_authoring_context(
        model_info_logical=profile_plan["model_info_inx"], model_info_path=model_info,
        skeleton_logical=profile_plan["skeleton_smb"], skeleton_path=skeleton,
        lod=actual_lod, lod_groups=profile_plan["lod_groups"], selection_basis=profile_plan["selection_basis"],
    )
    context_verify = verify_selected_context_for_asset(selected_context, asset, resolver=resolver)
    if context_verify.get("status") != "PASS":
        raise RuntimeError(f"automated devtest selected context failed: {context_verify.get('errors')}")

    base_plan = authoring_plan(asset, source)
    scope = inspect_rigid_profile_stress_scope(base_plan, selected_context)
    if not scope.get("scope_complete") or not scope.get("all_lods_present"):
        raise RuntimeError(
            "automated rigid profile devtest requires complete HIGH/DEFAULT/LOW writer scope: "
            f"{scope.get('missing_or_ineligible_objects')}"
        )
    objects = list(scope.get("eligible_objects") or [])
    object_lods = dict(scope.get("object_lods") or {})

    edit_plan = {
        "format": "PT_RIGID_PROFILE_AUTOMATED_EDIT_PLAN_V1",
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "asset": asset.primary_path,
        "objects": objects,
        "object_lods": object_lods,
        "amplitude": float(amplitude),
        "source_sha256": sha256_file(source),
        "selected_context": selected_context,
    }
    edit_plan_path = edit_work / "edit_plan.json"
    edit_plan_path.write_text(json.dumps(edit_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    edited_blend = edit_work / "automatically_edited.blend"
    edit_report_path = edit_work / "edit_report.json"
    edit_script = project_root / "pt_asset_tool" / "blender" / "apply_rigid_profile_devtest.py"
    run_logged(settings.blender_command() + [
        "--background", str(pristine), "--python-exit-code", "1", "--python", str(edit_script), "--",
        "--plan", str(edit_plan_path), "--out", str(edited_blend), "--report", str(edit_report_path),
    ], edit_work / "01_automatic_edit.log")
    edit_report = json.loads(edit_report_path.read_text(encoding="utf-8"))
    if edit_report.get("status") != "PASS" or int(edit_report.get("target_count") or 0) != len(objects):
        raise RuntimeError(f"automatic Blender edit failed: {edit_report}")

    output = build_work / pathlib.PurePosixPath(asset.primary_path).name
    steps_dir = build_work / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    current_source = pathlib.Path(source).resolve()
    steps: list[dict[str, Any]] = []
    for idx, object_name in enumerate(objects, start=1):
        is_last = idx == len(objects)
        step_output = output if is_last else steps_dir / f"{idx:02d}_{object_name}.smd"
        step_report = steps_dir / f"{idx:02d}_{object_name}.writer.json"
        step_log = steps_dir / f"{idx:02d}_{object_name}.build.log"
        candidate = {
            "status": "READY",
            "blend": str(edited_blend),
            "source": str(current_source),
            "source_sha256": sha256_file(current_source),
            "skeleton": str(skeleton),
            "object": object_name,
            "output": str(step_output),
        }
        run_logged(build_rigid_candidate_blender_command(settings, candidate, report=step_report), step_log)
        step_data = json.loads(step_report.read_text(encoding="utf-8"))
        steps.append({
            "index": idx,
            "object": object_name,
            "lod": object_lods.get(object_name),
            "input": str(current_source),
            "input_sha256": sha256_file(current_source),
            "output": str(step_output),
            "output_sha256": sha256_file(step_output),
            "writer_report": str(step_report),
            "log": str(step_log),
            "source_counts": step_data.get("source_counts"),
            "output_counts": step_data.get("output_counts"),
            "topology_changed": (step_data.get("source_counts") or {}) != (step_data.get("output_counts") or {}),
            "unrelated_object_blocks_byte_identical": step_data.get("unrelated_object_blocks_byte_identical"),
            "max_vertex_fit_error": step_data.get("max_vertex_fit_error"),
        })
        current_source = step_output.resolve()

    verification = validate_rigid_profile_stress_output(project_root, source, output, skeleton, objects)
    if verification.get("status") != "PASS":
        raise RuntimeError(f"combined rigid profile candidate failed: {verification.get('errors')}")

    writer_summary = {
        "tool": "PT_RIGID_PROFILE_AUTOMATED_DEVTEST_WRITER_V1",
        "step_count": len(steps),
        "objects": objects,
        "object_lods": object_lods,
        "steps": [_compact_step(x) for x in steps],
        "output_sha256": sha256_file(output),
    }
    writer_summary_path = build_work / "writer_summary.json"
    writer_summary_path.write_text(json.dumps(writer_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = write_build_provenance(
        output, asset=asset, source=source, build_mode="CANDIDATE_RIGID_STRESS_AUTOMATED_DEVTEST",
        adapter="pt_blender_to_smd_free_mesh_v3.py", build_status="PASS", production_authorized=False,
        evidence={
            "automated_devtest": True,
            "profile_id": profile.profile_id,
            "verification_format": verification.get("format"),
            "verification_status": verification.get("status"),
            "candidate_objects": objects,
            "stress_object_lods": object_lods,
            "edit_observed_by_object": dict(verification.get("edit_observed_by_object") or {}),
            "all_target_edits_observed": bool(verification.get("all_target_edits_observed")),
            "targets_without_observed_edit": list(verification.get("targets_without_observed_edit") or []),
            "verification_errors": list(verification.get("errors") or []),
            "non_target_changed": list(verification.get("non_target_changed") or []),
            "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}),
            "automatic_edit_report": str(edit_report_path),
            "writer_summary": str(writer_summary_path),
        },
        selected_context=selected_context,
    )

    parsed_candidate = parse_model062_bytes(output.read_bytes())
    reimport_results: dict[str, Any] = {}
    check_script = project_root / "pt_asset_tool" / "blender" / "check_rigid_profile_devtest.py"
    import_script = project_root / "history_py" / "pt_smd_blender_import_v3_static_armature.py"
    for lod in ("high", "default", "low"):
        expected_names = list((profile_plan.get("lod_groups") or {}).get(lod) or [])
        expected_contract = {"format": "PT_RIGID_PROFILE_AUTOMATED_REIMPORT_EXPECTED_V1", "lod": lod, "objects": {}}
        for name in expected_names:
            obj = parsed_candidate["objects"].get(name)
            if obj is None:
                raise RuntimeError(f"candidate missing profile {lod} object before reimport: {name}")
            expected_contract["objects"][name] = {"vertices": int(obj["nv"]), "faces": int(obj["nf"])}
        expected_path = reimport_work / f"expected_{lod}.json"
        expected_path.write_text(json.dumps(expected_contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        blend = reimport_work / f"candidate_{lod}.blend"
        import_log = reimport_work / f"01_import_{lod}.log"
        run_logged(settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(import_script), "--",
            "--smd", str(output), "--skeleton", str(skeleton), "--model-info", str(model_info),
            "--lod", lod, "--client-root", str(overlay), "--out", str(blend), "--no-pack",
        ], import_log)
        check_report = reimport_work / f"check_{lod}.json"
        check_log = reimport_work / f"02_check_{lod}.log"
        run_logged(settings.blender_command() + [
            "--background", str(blend), "--python-exit-code", "1", "--python", str(check_script), "--",
            "--expected", str(expected_path), "--report", str(check_report),
        ], check_log)
        checked = json.loads(check_report.read_text(encoding="utf-8"))
        if checked.get("status") != "PASS":
            raise RuntimeError(f"candidate {lod} reimport check failed: {checked.get('errors')}")
        reimport_results[lod] = {
            "status": "PASS",
            "expected_objects": expected_names,
            "checked_object_count": checked.get("checked_object_count"),
            "blend": str(blend),
            "check_report": str(check_report),
        }

    result = {
        "format": FORMAT,
        "status": "PASS",
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "asset": asset.primary_path,
        "source_sha256": sha256_file(source),
        "selected_context_verification": context_verify.get("status"),
        "texture_ready": bool(texture_report.get("ready", True)),
        "automatic_edit": {
            "status": edit_report.get("status"),
            "amplitude": edit_report.get("amplitude"),
            "target_count": edit_report.get("target_count"),
            "objects": objects,
            "report": str(edit_report_path),
        },
        "candidate": {
            "status": verification.get("status"),
            "artifact": str(output),
            "artifact_sha256": sha256_file(output),
            "provenance": str(provenance),
            "writer_step_count": len(steps),
            "all_target_edits_observed": bool(verification.get("all_target_edits_observed")),
            "targets_without_observed_edit": list(verification.get("targets_without_observed_edit") or []),
            "non_target_changed": list(verification.get("non_target_changed") or []),
            "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}),
            "errors": list(verification.get("errors") or []),
            "writer_summary": str(writer_summary_path),
        },
        "reimport": reimport_results,
        "automatic_devtest_pass": True,
        "human_visual_review_required_for_runtime_or_production": True,
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
        "workdir": str(work),
    }
    report_path = work / "result.json"
    result["report"] = str(report_path)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_rigid_profile_automated_devtest_batch(
    settings,
    asset_registry,
    resolver,
    certifications,
    profile_registry,
    profile_ids: list[str],
    *,
    amplitude: float = 0.12,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        try:
            row = run_rigid_profile_automated_devtest(
                settings, asset_registry, resolver, certifications, profile_registry, profile_id, amplitude=amplitude
            )
            rows.append(row)
        except Exception as exc:
            failures.append({"profile_id": profile_id, "error": f"{type(exc).__name__}: {exc}"})
    result = {
        "format": BATCH_FORMAT,
        "status": "PASS" if not failures and rows else "FAIL",
        "profile_count": len(profile_ids),
        "passed_profiles": [x.get("profile_id") for x in rows if x.get("status") == "PASS"],
        "failed_profiles": failures,
        "results": rows,
        "automatic_only": True,
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    out = pathlib.Path(settings.project_root).resolve() / "pt_build" / "devtest" / "rigid_profile_auto" / "batch_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
