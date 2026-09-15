from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .blender_workspace import asset_workspace_name
from .build_provenance import sha256_file, write_build_provenance
from .mixed_authoring_candidate import (
    analyze_mixed_source,
    build_mixed_candidate_step_command,
    validate_mixed_candidate_output,
)
from .release_1_coverage import content_domain
from .rigid_model_info import effective_lod_node_coverage, lod_model_info_configs
from .static_roundtrip import _parse as parse_model062_bytes
from .utils import run_logged
from .validation import ValidationContext, ValidationRunner

FORMAT = "PT_MIXED_PHYSIQUE_PHYSICAL_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT = "PT_MIXED_PHYSIQUE_PHYSICAL_AUTOMATED_DEVTEST_BATCH_V1"


def _norm(value: str | None) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def choose_mixed_physique_representatives(registry) -> list[dict[str, Any]]:
    """Return every physical Mixed-Physique asset; Release 1.0 does not sample Mixed."""
    rows = []
    for asset in registry.assets:
        if asset.family != "SMD_MODEL_062_MIXED_PHYSIQUE":
            continue
        rows.append({
            "asset_id": asset.asset_id,
            "asset": asset.primary_path,
            "domain": content_domain(asset),
            "object_count": int(asset.object_count or 0),
            "total_vertices": int(asset.total_vertices or 0),
            "total_faces": int(asset.total_faces or 0),
        })
    rows.sort(key=lambda row: (str(row["domain"]), str(row["asset"]).casefold()))
    return rows


def _sibling_smbs(registry, asset) -> list[dict[str, str]]:
    rel = pathlib.PurePosixPath(_norm(asset.primary_path))
    parent = rel.parent.as_posix().casefold()
    stem = rel.stem.casefold()
    siblings = []
    for record in registry.records:
        if str(record.get("extension") or "").casefold() != ".smb":
            continue
        logical = _norm(record.get("relative_path"))
        if pathlib.PurePosixPath(logical).parent.as_posix().casefold() == parent:
            siblings.append(logical)
    siblings = sorted(set(siblings), key=str.casefold)
    exact = [logical for logical in siblings if pathlib.PurePosixPath(logical).stem.casefold() == stem]
    if len(exact) == 1:
        return [{"skeleton_smb": exact[0], "basis": "EXACT_SIBLING_STEM"}]
    if len(siblings) == 1:
        return [{"skeleton_smb": siblings[0], "basis": "UNIQUE_DIRECTORY_SMB"}]
    return []


def mixed_skeleton_candidates(registry, asset) -> list[dict[str, str]]:
    """Build deterministic skeleton hypotheses; the structural gate is authoritative."""
    candidates: list[dict[str, str]] = []
    for cfg in asset.configs:
        logical = _norm(cfg.get("motion_smb"))
        if logical:
            candidates.append({"skeleton_smb": logical, "basis": "MODEL_INFO_MOTION_SMB"})
    bound = _norm(getattr(asset, "binding_skeleton_smb", ""))
    if bound:
        candidates.append({"skeleton_smb": bound, "basis": "RESOLVED_BINDING_SKELETON"})
    candidates.extend(_sibling_smbs(registry, asset))
    rank = {
        "MODEL_INFO_MOTION_SMB": 0,
        "RESOLVED_BINDING_SKELETON": 1,
        "EXACT_SIBLING_STEM": 2,
        "UNIQUE_DIRECTORY_SMB": 3,
    }
    dedup: dict[str, dict[str, str]] = {}
    for row in sorted(candidates, key=lambda r: (rank.get(r["basis"], 9), r["skeleton_smb"].casefold())):
        dedup.setdefault(row["skeleton_smb"].casefold(), row)
    return list(dedup.values())


def choose_mixed_physical_context(registry, asset, analysis: dict[str, Any]) -> dict[str, Any]:
    rigid = set(analysis.get("eligible_rigid_objects") or [])
    static = set(analysis.get("eligible_static_objects") or [])
    if not rigid or not static:
        raise RuntimeError("mixed source does not contain writer-eligible rigid and static objects")
    skeletons = mixed_skeleton_candidates(registry, asset)
    if not skeletons:
        raise RuntimeError("mixed source has no deterministic skeleton candidate; authoritative skeleton context is required")

    # Prefer an exact model-info/LOD context when one exists.  It must expose
    # both sides of the mixed container so the physical gate exercises both adapters.
    contexts = []
    for cfg in lod_model_info_configs(asset):
        cfg_smb = _norm(cfg.get("motion_smb"))
        skeleton_options = [row for row in skeletons if not cfg_smb or row["skeleton_smb"].casefold() == cfg_smb.casefold()]
        if not skeleton_options:
            continue
        for lod_rank, lod in enumerate(("default", "high", "low")):
            coverage = effective_lod_node_coverage(asset, cfg, lod)
            if coverage.get("status") != "PASS":
                continue
            selected = list(coverage.get("effective_selected_nodes") or [])
            target_rigid = sorted(rigid.intersection(selected), key=str.casefold)
            target_static = sorted(static.intersection(selected), key=str.casefold)
            if not target_rigid or not target_static:
                continue
            for skeleton in skeleton_options:
                contexts.append({
                    "mode": "MODEL_INFO_LOD",
                    "model_info_inx": _norm(cfg.get("inx")),
                    "lod": lod,
                    "lod_rank": lod_rank,
                    "lod_selection_mode": str(coverage.get("selection_mode") or "MODEL_GROUP_KEYS"),
                    "skeleton_smb": skeleton["skeleton_smb"],
                    "skeleton_basis": skeleton["basis"],
                    "rigid_targets": target_rigid,
                    "static_targets": target_static,
                    "target_count": len(target_rigid) + len(target_static),
                })
    if contexts:
        contexts.sort(key=lambda row: (-int(row["target_count"]), int(row["lod_rank"]), str(row["model_info_inx"]).casefold(), str(row["skeleton_smb"]).casefold()))
        return contexts[0]

    # If any authorable LOD exists but none exposes both modes, fail closed;
    # do not bypass a real model-info context through a standalone hypothesis.
    if any(
        effective_lod_node_coverage(asset, cfg, lod).get("status") == "PASS"
        for cfg in lod_model_info_configs(asset)
        for lod in ("default", "high", "low")
    ):
        raise RuntimeError("mixed model-info/LOD contexts do not expose eligible rigid and static targets together")

    chosen = skeletons[0]
    return {
        "mode": "STANDALONE_SKELETON",
        "model_info_inx": None,
        "lod": "standalone",
        "lod_selection_mode": "FULL_CONTAINER",
        "skeleton_smb": chosen["skeleton_smb"],
        "skeleton_basis": chosen["basis"],
        "rigid_targets": sorted(rigid, key=str.casefold),
        "static_targets": sorted(static, key=str.casefold),
        "target_count": len(rigid) + len(static),
    }


def _work_root(project_root: pathlib.Path, domain: str, asset_path: str) -> pathlib.Path:
    return project_root / "pt_build" / "devtest" / "mixed_physical_auto" / str(domain).lower() / asset_workspace_name(asset_path)


def run_mixed_physique_physical_automated_devtest(
    settings, registry, resolver, certifications, *, asset_path: str, domain: str, amplitude: float = 0.08,
) -> dict[str, Any]:
    asset = registry.resolve(asset_path)
    if asset.family != "SMD_MODEL_062_MIXED_PHYSIQUE":
        raise RuntimeError(f"mixed physical devtest requires SMD_MODEL_062_MIXED_PHYSIQUE, got {asset.family}")
    project_root = pathlib.Path(settings.project_root).resolve()
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    analysis = analyze_mixed_source(source)
    if analysis.get("status") != "PASS":
        raise RuntimeError(f"mixed source analysis failed: mode={analysis.get('mode')}")
    context = choose_mixed_physical_context(registry, asset, analysis)
    skeleton_logical = context["skeleton_smb"]
    skeleton = pathlib.Path(resolver.resolve(skeleton_logical, required=True)).resolve()

    work = _work_root(project_root, domain, asset.primary_path)
    if work.exists():
        shutil.rmtree(work)
    import_work, edit_work, build_work, reimport_work = [work / name for name in ("01_import", "02_edit", "03_candidate", "04_reimport")]
    for path in (import_work, edit_work, build_work, reimport_work):
        path.mkdir(parents=True, exist_ok=True)

    runner = ValidationRunner(ValidationContext(settings, resolver, certifications))
    overlay, texture_report = runner._texture_overlay(asset, import_work)
    model_info = None
    if context["mode"] == "MODEL_INFO_LOD":
        preflight = runner._preflight_explicit_skeleton_lod_import(
            asset, context["lod"], model_info=context["model_info_inx"],
            skeleton_logical=skeleton_logical, require_unambiguous=True,
        )
        source, pristine = runner._prepare_explicit_skeleton_lod_blend(asset, import_work, overlay, preflight)
        model_info = pathlib.Path(preflight["model_info"]).resolve()
        context["lod_selection_mode"] = str((preflight.get("lod_node_coverage") or {}).get("selection_mode") or context["lod_selection_mode"])
    else:
        preflight = runner._preflight_standalone_rigid_import(asset, skeleton_logical)
        source, pristine = runner._prepare_standalone_rigid_blend(asset, import_work, overlay, preflight)

    rigid_targets = list(context["rigid_targets"])
    static_targets = list(context["static_targets"])
    targets = rigid_targets + static_targets
    adapters = {name: "pt_blender_to_smd_free_mesh_v3.py" for name in rigid_targets}
    adapters.update({name: "pt_blender_to_smd_static_v1.py" for name in static_targets})
    edit_plan = {
        "format": "PT_MIXED_PHYSIQUE_AUTOMATED_EDIT_PLAN_V1",
        "domain": domain,
        "asset": asset.primary_path,
        "amplitude": float(amplitude),
        "targets": [{"object": name, "adapter": "RIGID" if name in rigid_targets else "STATIC"} for name in targets],
        "source_sha256": sha256_file(source),
        "context": context,
    }
    edit_plan_path = edit_work / "edit_plan.json"
    edit_plan_path.write_text(json.dumps(edit_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    edited_blend = edit_work / "automatically_edited.blend"
    edit_report_path = edit_work / "edit_report.json"
    edit_script = project_root / "pt_asset_tool" / "blender" / "apply_mixed_semantic_devtest.py"
    run_logged(settings.blender_command() + [
        "--background", str(pristine), "--python-exit-code", "1", "--python", str(edit_script), "--",
        "--plan", str(edit_plan_path), "--out", str(edited_blend), "--report", str(edit_report_path),
    ], edit_work / "01_automatic_edit.log")
    edit_report = json.loads(edit_report_path.read_text(encoding="utf-8"))
    if edit_report.get("status") != "PASS" or int(edit_report.get("target_count") or 0) != len(targets):
        raise RuntimeError(f"automatic mixed edit failed: {edit_report}")

    output = build_work / pathlib.PurePosixPath(asset.primary_path).name
    steps_dir = build_work / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    current_source = pathlib.Path(source).resolve()
    steps = []
    candidate = {
        "status": "READY",
        "blend": str(edited_blend),
        "source": str(source),
        "source_sha256": sha256_file(source),
        "skeleton": str(skeleton),
        "objects": targets,
        "object_adapters": adapters,
        "output": str(output),
    }
    for index, object_name in enumerate(targets, start=1):
        step_output = output if index == len(targets) else steps_dir / f"{index:02d}_{object_name}.smd"
        step_report = steps_dir / f"{index:02d}_{object_name}.writer.json"
        step_log = steps_dir / f"{index:02d}_{object_name}.log"
        cmd = build_mixed_candidate_step_command(
            settings, candidate, object_name=object_name, source=current_source, output=step_output, report=step_report,
        )
        run_logged(cmd, step_log)
        data = json.loads(step_report.read_text(encoding="utf-8"))
        steps.append({
            "index": index,
            "object": object_name,
            "adapter": adapters[object_name],
            "input_sha256": sha256_file(current_source),
            "output_sha256": sha256_file(step_output),
            "source_counts": data.get("source_counts"),
            "output_counts": data.get("output_counts"),
            "unrelated_object_blocks_byte_identical": data.get("unrelated_object_blocks_byte_identical"),
            "max_vertex_fit_error": data.get("max_vertex_fit_error"),
        })
        current_source = step_output.resolve()

    verification = validate_mixed_candidate_output(
        source, output, target_objects=targets, project_root=project_root, skeleton=skeleton,
    )
    if verification.get("status") != "PASS" or not verification.get("all_target_edits_observed"):
        raise RuntimeError(f"combined mixed candidate failed: {verification.get('errors')} targets_without_edit={verification.get('targets_without_observed_edit')}")
    if set(row.get("adapter") for row in verification.get("target_results") or []) != {"RIGID", "STATIC"}:
        raise RuntimeError("combined mixed candidate did not verify both rigid and static adapters")

    writer_summary = build_work / "writer_summary.json"
    writer_summary.write_text(json.dumps({
        "tool": "PT_MIXED_PHYSIQUE_PHYSICAL_AUTOMATED_DEVTEST_WRITER_V1",
        "step_count": len(steps), "steps": steps, "output_sha256": sha256_file(output),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = write_build_provenance(
        output, asset=asset, source=source, build_mode="CANDIDATE_MIXED_PHYSICAL_AUTOMATED_DEVTEST",
        adapter="pt_asset_tool.mixed_authoring_candidate", build_status="PASS", production_authorized=False,
        evidence={
            "automated_devtest": True, "semantic_domain": domain, "physical_mixed": True,
            "context": context, "candidate_objects": targets, "object_adapters": adapters,
            "all_target_edits_observed": True,
            "non_target_changed": list(verification.get("non_target_changed") or []),
            "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}),
            "verification_errors": list(verification.get("errors") or []), "writer_summary": str(writer_summary),
        },
    )

    parsed = parse_model062_bytes(output.read_bytes())
    expected = {"format": "PT_MIXED_PHYSIQUE_AUTOMATED_REIMPORT_EXPECTED_V1", "objects": {}}
    for name in targets:
        obj = parsed["objects"].get(name)
        if obj is None:
            raise RuntimeError(f"mixed candidate missing target before reimport: {name}")
        expected["objects"][name] = {"vertices": int(obj["nv"]), "faces": int(obj["nf"])}
    expected_path = reimport_work / "expected.json"
    expected_path.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reimport_blend = reimport_work / "candidate_reimport.blend"
    importer = project_root / "history_py" / "pt_smd_blender_import_v3_static_armature.py"
    reimport_cmd = settings.blender_command() + [
        "--background", "--python-exit-code", "1", "--python", str(importer), "--",
        "--smd", str(output), "--skeleton", str(skeleton),
    ]
    if model_info is not None:
        reimport_cmd += ["--model-info", str(model_info), "--lod", str(context["lod"])]
    reimport_cmd += ["--client-root", str(overlay), "--out", str(reimport_blend), "--no-pack"]
    if model_info is not None and context.get("lod_selection_mode") == "SINGLE_TIER_FULL_CONTAINER":
        reimport_cmd.append("--single-tier-full-container")
    run_logged(reimport_cmd, reimport_work / "01_import.log")
    check_report = reimport_work / "check.json"
    check_script = project_root / "pt_asset_tool" / "blender" / "check_static_semantic_devtest.py"
    run_logged(settings.blender_command() + [
        "--background", str(reimport_blend), "--python-exit-code", "1", "--python", str(check_script), "--",
        "--expected", str(expected_path), "--report", str(check_report),
    ], reimport_work / "02_check.log")
    checked = json.loads(check_report.read_text(encoding="utf-8"))
    if checked.get("status") != "PASS":
        raise RuntimeError(f"mixed candidate reimport check failed: {checked.get('errors')}")

    result = {
        "format": FORMAT, "status": "PASS", "domain": domain, "asset": asset.primary_path,
        "source_sha256": sha256_file(source), "context": context,
        "texture_ready": bool(texture_report.get("ready", True)),
        "automatic_edit": {"status": edit_report.get("status"), "target_count": edit_report.get("target_count"), "report": str(edit_report_path)},
        "candidate": {
            "status": verification.get("status"), "artifact": str(output), "artifact_sha256": sha256_file(output),
            "provenance": str(provenance), "writer_step_count": len(steps), "all_target_edits_observed": True,
            "non_target_changed": list(verification.get("non_target_changed") or []),
            "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}),
            "writer_summary": str(writer_summary),
        },
        "reimport": {"status": checked.get("status"), "checked_object_count": checked.get("checked_object_count"), "blend": str(reimport_blend), "check_report": str(check_report)},
        "physical_mixed_certified": True, "automatic_devtest_pass": True,
        "runtime_authorized": False, "production_authorized": False, "client_write_authorized": False, "client_modified": False,
        "workdir": str(work),
    }
    report_path = work / "result.json"
    result["report"] = str(report_path)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_mixed_physique_physical_automated_devtest_batch(
    settings, registry, resolver, certifications, rows: list[dict[str, Any]], *, amplitude: float = 0.08,
) -> dict[str, Any]:
    results = []
    failed = []
    for row in rows:
        try:
            results.append(run_mixed_physique_physical_automated_devtest(
                settings, registry, resolver, certifications,
                asset_path=row["asset"], domain=row["domain"], amplitude=amplitude,
            ))
        except Exception as exc:
            failed.append({"asset": row.get("asset"), "domain": row.get("domain"), "error": f"{type(exc).__name__}: {exc}"})
    if not rows:
        status = "EMPTY"
    else:
        status = "PASS" if len(results) == len(rows) and not failed else "FAIL"
    result = {
        "format": BATCH_FORMAT, "status": status, "requested": len(rows), "passed": len(results),
        "failed": failed, "results": results,
        "physical_mixed_certified": bool(rows) and status == "PASS" and all(bool(r.get("physical_mixed_certified")) for r in results),
        "automatic_only": True, "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }
    out = pathlib.Path(settings.project_root).resolve() / "pt_build" / "devtest" / "mixed_physical_auto" / "batch_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
