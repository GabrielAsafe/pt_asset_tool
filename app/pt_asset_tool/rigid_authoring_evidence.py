from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from .authoring import authoring_plan, verify_selected_context_for_asset
from .build_provenance import provenance_path, sha256_file, verify_build_provenance
from .rigid_authoring_candidate import inspect_rigid_candidate_scope
from .rigid_authoring_stress import inspect_rigid_profile_stress_scope, stress_context_key
from .blender_workspace import asset_workspace_name
from .texture_overlay import prepare_texture_overlay
from .utils import run_logged

VERIFY_FORMAT = "PT_RIGID_SAVED_BLENDER_EVIDENCE_VERIFY_V1"
PLAN_FORMAT = "PT_RIGID_SAVED_BLENDER_CERTIFICATION_PLAN_V1"
AUTOMATIC_TEST = "RIGID_SAVED_BLENDER_CONTROLLED_EDIT"
AUTOMATIC_LAYER = "BLENDER_CANDIDATE"
HUMAN_LAYER = "HUMAN_VISUAL"
REVIEW_MANIFEST_FORMAT = "PT_RIGID_CANDIDATE_REVIEW_WORKSPACE_V1"


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve()
    path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def _norm(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def rigid_candidate_context_key(asset_path: str, selected_context: dict[str, Any] | None, object_name: str) -> str:
    context = dict(selected_context or {})
    basis = dict(context.get("selection_basis") or {})
    payload = {
        "asset": _norm(asset_path).casefold(),
        "model_info_inx": _norm((context.get("model_info_inx") or {}).get("logical")).casefold(),
        "skeleton_smb": _norm((context.get("skeleton_smb") or {}).get("logical")).casefold(),
        "lod": str(context.get("lod") or "").casefold(),
        "lod_groups_signature": str(context.get("lod_groups_signature") or "").lower(),
        "profile_id": str(basis.get("profile_id") or "").casefold(),
        "profile_version": int(basis.get("profile_version") or 0),
        "object": str(object_name or "").casefold(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "RIGIDCTX-" + hashlib.sha256(raw).hexdigest()[:24].upper()


def verify_rigid_candidate_artifact(project_root, resolver, asset, artifact: pathlib.Path | str) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    artifact = pathlib.Path(artifact).expanduser()
    artifact = (project_root / artifact).resolve() if not artifact.is_absolute() else artifact.resolve()
    errors: list[str] = []
    if not _inside(project_root / "pt_build", artifact):
        errors.append("ARTIFACT_OUTSIDE_PT_BUILD")

    try:
        source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    except Exception as exc:
        source = pathlib.Path("/")
        errors.append(f"SOURCE_RESOLVE:{type(exc).__name__}")

    prov_verify = verify_build_provenance(
        artifact, expected_asset_id=asset.asset_id, expected_asset_path=asset.primary_path,
        expected_source=source if source.is_file() else None,
    )
    if prov_verify.get("status") != "PASS":
        errors.extend([f"PROVENANCE:{x}" for x in (prov_verify.get("errors") or [])])

    data: dict[str, Any] = {}
    prov = provenance_path(artifact)
    if prov.is_file():
        try:
            data = json.loads(prov.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"PROVENANCE_PARSE:{type(exc).__name__}")
    build_mode = str(data.get("build_mode") or "")
    stress = build_mode == "CANDIDATE_RIGID_STRESS"
    if build_mode not in {"CANDIDATE_RIGID", "CANDIDATE_RIGID_STRESS"}:
        errors.append("NOT_RIGID_CANDIDATE_BUILD")
    if str(data.get("build_status") or "") != "PASS":
        errors.append("CANDIDATE_BUILD_NOT_PASS")
    if bool(data.get("production_authorized")):
        errors.append("CANDIDATE_PROVENANCE_UNEXPECTEDLY_PRODUCTION_AUTHORIZED")

    selected_context = dict(data.get("selected_context") or {})
    context_verify = verify_selected_context_for_asset(selected_context, asset, resolver=resolver)
    if context_verify.get("status") != "PASS":
        errors.append("SELECTED_CONTEXT_ASSET_MISMATCH")

    evidence = dict(data.get("evidence") or {})
    object_name = str(evidence.get("candidate_object") or "")
    candidate_objects = [str(x) for x in (evidence.get("candidate_objects") or []) if str(x)]
    if stress:
        if not bool(evidence.get("stress_profile")):
            errors.append("STRESS_EVIDENCE_FLAG_MISSING")
        if not candidate_objects:
            errors.append("STRESS_CANDIDATE_OBJECTS_MISSING")
        if not bool(evidence.get("all_target_edits_observed")):
            errors.append("STRESS_ALL_TARGET_EDITS_NOT_OBSERVED")
        if list(evidence.get("targets_without_observed_edit") or []):
            errors.append("STRESS_TARGETS_WITHOUT_EDIT")
        unknown_map = dict(evidence.get("unknown_physique_bones_by_object") or {})
        if any(list(v or []) for v in unknown_map.values()):
            errors.append("UNKNOWN_PHYSIQUE_BONES")
    else:
        if not object_name:
            errors.append("CANDIDATE_OBJECT_EVIDENCE_MISSING")
        if not bool(evidence.get("edit_observed")):
            errors.append("CONTROLLED_EDIT_NOT_OBSERVED")
    if evidence.get("verification_status") != "PASS":
        errors.append("CANDIDATE_VERIFICATION_NOT_PASS")
    if list(evidence.get("verification_errors") or []):
        errors.append("CANDIDATE_VERIFICATION_ERRORS_PRESENT")
    if list(evidence.get("non_target_changed") or []):
        errors.append("NON_TARGET_CHANGED")
    if not stress and list(evidence.get("unknown_physique_bones") or []):
        errors.append("UNKNOWN_PHYSIQUE_BONES")

    scope = None
    if source.is_file():
        try:
            base = authoring_plan(asset, source)
            if stress:
                scope = inspect_rigid_profile_stress_scope(base, selected_context)
                eligible_cf = {x.casefold() for x in (scope.get("eligible_objects") or [])}
                outside = [x for x in candidate_objects if x.casefold() not in eligible_cf]
                if outside:
                    errors.append("STRESS_OBJECT_OUTSIDE_PROFILE_SCOPE")
                if not scope.get("scope_complete"):
                    errors.append("STRESS_PROFILE_SCOPE_INCOMPLETE")
            else:
                scope = inspect_rigid_candidate_scope(base, selected_context)
                if object_name and not any(x.casefold() == object_name.casefold() for x in (scope.get("eligible_objects") or [])):
                    errors.append("CANDIDATE_OBJECT_OUTSIDE_SELECTED_LOD_SCOPE")
        except Exception as exc:
            errors.append(f"CANDIDATE_SCOPE:{type(exc).__name__}")

    context_key = (
        stress_context_key(asset.primary_path, selected_context, candidate_objects) if stress and candidate_objects
        else rigid_candidate_context_key(asset.primary_path, selected_context, object_name) if object_name
        else None
    )
    return {
        "format": VERIFY_FORMAT, "status": "PASS" if not errors else "FAIL",
        "asset_id": asset.asset_id, "asset": asset.primary_path,
        "artifact": str(artifact), "artifact_sha256": sha256_file(artifact) if artifact.is_file() else None,
        "provenance": str(prov), "provenance_verification": prov_verify,
        "build_mode": build_mode, "stress_profile": stress,
        "selected_context": selected_context or None, "selected_context_verification": context_verify,
        "candidate_scope": scope, "candidate_object": object_name or None,
        "candidate_objects": candidate_objects, "stress_object_lods": dict(evidence.get("stress_object_lods") or {}),
        "context_key": context_key, "evidence": evidence, "errors": errors,
        "ready_for_human_review": not errors, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }

def _candidate_review_root(project_root: pathlib.Path, asset_path: str, context_key: str) -> pathlib.Path:
    return (
        pathlib.Path(project_root).resolve() / "pt_build" / "candidate_review" /
        asset_workspace_name(asset_path) / str(context_key)
    ).resolve()


def prepare_rigid_candidate_review_workspace(settings, resolver, asset, artifact: pathlib.Path | str) -> dict[str, Any]:
    verified = verify_rigid_candidate_artifact(settings.project_root, resolver, asset, artifact)
    if verified.get("status") != "PASS":
        raise RuntimeError(f"rigid candidate artifact evidence failed: {verified.get('errors')}")
    context = dict(verified.get("selected_context") or {})
    context_key = str(verified.get("context_key") or "")
    work = _candidate_review_root(pathlib.Path(settings.project_root), asset.primary_path, context_key)
    work.mkdir(parents=True, exist_ok=True)
    overlay, texture_report = prepare_texture_overlay(
        asset=asset, resolver=resolver, root=pathlib.Path(settings.project_root).resolve(), work=work
    )
    inx = pathlib.Path((context.get("model_info_inx") or {}).get("path") or "").resolve()
    smb = pathlib.Path((context.get("skeleton_smb") or {}).get("path") or "").resolve()
    if not inx.is_file():
        raise RuntimeError(f"selected model-info missing for candidate review: {inx}")
    if not smb.is_file():
        raise RuntimeError(f"selected skeleton missing for candidate review: {smb}")
    review_blend = work / "candidate_reimport.blend"
    log = work / "01_candidate_reimport.log"
    cmd = settings.blender_command() + [
        "--background", "--python-exit-code", "1",
        "--python", str(pathlib.Path(settings.project_root).resolve() / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"), "--",
        "--smd", str(pathlib.Path(verified["artifact"]).resolve()),
        "--skeleton", str(smb), "--model-info", str(inx),
        "--lod", str(context.get("lod") or "default"),
        "--client-root", str(overlay), "--out", str(review_blend), "--no-pack",
    ]
    run_logged(cmd, log)
    if not review_blend.is_file():
        raise RuntimeError("candidate reimport completed without review .blend")
    manifest = {
        "format": REVIEW_MANIFEST_FORMAT,
        "status": "READY_FOR_HUMAN_VISUAL_REVIEW",
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "artifact": verified.get("artifact"),
        "artifact_sha256": verified.get("artifact_sha256"),
        "candidate_object": verified.get("candidate_object"),
        "candidate_objects": list(verified.get("candidate_objects") or []),
        "stress_profile": bool(verified.get("stress_profile")),
        "stress_object_lods": dict(verified.get("stress_object_lods") or {}),
        "context_key": context_key,
        "selected_context": context,
        "review_blend": str(review_blend),
        "review_blend_sha256": sha256_file(review_blend),
        "texture_overlay": str(overlay),
        "texture_ready": bool(texture_report.get("ready", True)),
        "log": str(log),
        "review_question": (
            "Does the reimported full-profile stress candidate preserve all intended HIGH/DEFAULT/LOW geometry edits, rig binding and materials without visible corruption?"
            if bool(verified.get("stress_profile")) else
            "Does the reimported candidate output preserve the intended edited geometry, rig binding and materials without visible corruption?"
        ),
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    manifest_path = work / "review_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["review_manifest"] = str(manifest_path)
    return manifest


def verify_rigid_candidate_review_workspace(settings, resolver, asset, artifact: pathlib.Path | str) -> dict[str, Any]:
    verified = verify_rigid_candidate_artifact(settings.project_root, resolver, asset, artifact)
    errors = list(verified.get("errors") or [])
    context_key = str(verified.get("context_key") or "")
    work = _candidate_review_root(pathlib.Path(settings.project_root), asset.primary_path, context_key)
    manifest_path = work / "review_manifest.json"
    data: dict[str, Any] = {}
    if not manifest_path.is_file():
        errors.append("CANDIDATE_REVIEW_MANIFEST_MISSING")
    else:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"CANDIDATE_REVIEW_MANIFEST_PARSE:{type(exc).__name__}")
    if data and data.get("format") != REVIEW_MANIFEST_FORMAT:
        errors.append("CANDIDATE_REVIEW_MANIFEST_FORMAT")
    if data and str(data.get("context_key") or "") != context_key:
        errors.append("CANDIDATE_REVIEW_CONTEXT_KEY_MISMATCH")
    if data and str(data.get("artifact_sha256") or "").lower() != str(verified.get("artifact_sha256") or "").lower():
        errors.append("CANDIDATE_REVIEW_ARTIFACT_DRIFT")
    if data and not bool(data.get("texture_ready")):
        errors.append("CANDIDATE_REVIEW_TEXTURES_NOT_READY")
    review_blend = pathlib.Path(str(data.get("review_blend") or "")) if data else pathlib.Path()
    if data and (not review_blend.is_file() or str(data.get("review_blend_sha256") or "").lower() != sha256_file(review_blend).lower()):
        errors.append("CANDIDATE_REVIEW_BLEND_DRIFT")
    return {
        "format": "PT_RIGID_CANDIDATE_REVIEW_WORKSPACE_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "artifact_verification": verified,
        "review_manifest": str(manifest_path),
        "review": data or None,
        "errors": errors,
        "ready_for_human_review_record": not errors,
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def build_candidate_provenance_evidence(kind: str, candidate: dict[str, Any], writer_report: dict[str, Any], verification: dict[str, Any], *, require_edit: bool) -> dict[str, Any]:
    rigid = str(kind).upper() == "RIGID"
    context = dict(candidate.get("selected_context") or {}) if rigid else {}
    basis = dict(context.get("selection_basis") or {})
    return {
        "verification_format": verification.get("format"),
        "verification_status": verification.get("status"),
        "authorization": "CANDIDATE_PT_BUILD_ONLY",
        "candidate_object": candidate.get("object"),
        "selected_lod": context.get("lod") if rigid else None,
        "profile_id": basis.get("profile_id") if rigid else None,
        "edit_observed": bool(verification.get("edit_observed")),
        "edit_required": bool(require_edit),
        "verification_errors": list(verification.get("errors") or []),
        "non_target_changed": list(verification.get("non_target_changed") or []),
        "unknown_physique_bones": list(verification.get("unknown_physique_bones") or []),
        "target": dict(verification.get("target") or {}),
        "writer_tool": writer_report.get("tool"),
        "writer_output_sha256": writer_report.get("output_sha256"),
        "writer_source_counts": writer_report.get("source_counts"),
        "writer_output_counts": writer_report.get("output_counts"),
        "unrelated_object_blocks_byte_identical": writer_report.get("unrelated_object_blocks_byte_identical"),
        "max_vertex_fit_error": writer_report.get("max_vertex_fit_error"),
    }


def _latest_evidence_by_context(certifications) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for row in certifications.records():
        meta = dict(row.get("metadata") or {})
        key = str(meta.get("rigid_candidate_context_key") or "")
        if not key or row.get("test") != AUTOMATIC_TEST:
            continue
        out.setdefault(key, {})[str(row.get("layer") or "")] = row
    return out


def build_rigid_authoring_certification_plan(profile_registry, asset_registry, resolver, certifications, *, profile_id: str | None = None) -> dict[str, Any]:
    profiles = [profile_registry.get(profile_id)] if profile_id else profile_registry.list()
    latest = _latest_evidence_by_context(certifications)
    external_witnesses: list[dict[str, Any]] = []
    try:
        evidence_path = pathlib.Path(profile_registry.directory).resolve().parent / "development_evidence" / "rigid_saved_blender_external_witnesses_v1.json"
        if evidence_path.is_file():
            external_witnesses = list((json.loads(evidence_path.read_text(encoding="utf-8")) or {}).get("witnesses") or [])
    except Exception:
        external_witnesses = []
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for profile in profiles:
        try:
            asset = asset_registry.resolve(profile.roundtrip_target)
            source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
            base_plan = authoring_plan(asset, source)
        except Exception as exc:
            errors.append({"profile_id": profile.profile_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for lod in ("high", "default", "low"):
            nodes = list(profile.lod_groups.get(lod) or [])
            context = {
                "lod": lod,
                "selected_lod_nodes": nodes,
                "selection_basis": {
                    "kind": "CANONICAL_PROFILE",
                    "profile_id": profile.profile_id,
                    "profile_version": profile.profile_version,
                    "roundtrip_target": profile.roundtrip_target,
                },
            }
            scope = inspect_rigid_candidate_scope(base_plan, context)
            eligible_cf = {x.casefold(): x for x in (scope.get("eligible_objects") or [])}
            for node in nodes:
                eligible_name = eligible_cf.get(str(node).casefold())
                # Plan keys do not require physical INX hashes; recorded evidence
                # does, so match certification rows by profile/lod/object metadata
                # as the human-readable fallback in addition to the stable key.
                candidates = []
                for key, layers in latest.items():
                    auto = layers.get(AUTOMATIC_LAYER) or {}
                    meta = dict(auto.get("metadata") or {})
                    if (
                        str(meta.get("profile_id") or "").casefold() == profile.profile_id.casefold()
                        and str(meta.get("lod") or "").casefold() == lod
                        and str(meta.get("object") or "").casefold() == str(node).casefold()
                        and _norm(meta.get("asset")).casefold() == _norm(asset.primary_path).casefold()
                    ):
                        candidates.append((key, layers))
                layers = candidates[-1][1] if candidates else {}
                auto = layers.get(AUTOMATIC_LAYER)
                human = layers.get(HUMAN_LAYER)
                auto_meta = dict((auto or {}).get("metadata") or {})
                human_meta = dict((human or {}).get("metadata") or {})
                auto_artifact_sha = str((auto or {}).get("artifact_sha256") or auto_meta.get("artifact_sha256") or "").lower()
                human_artifact_sha = str((human or {}).get("artifact_sha256") or human_meta.get("artifact_sha256") or "").lower()
                review_matches_candidate_artifact = bool(auto_artifact_sha and human_artifact_sha and auto_artifact_sha == human_artifact_sha)
                external_matches = [
                    w for w in external_witnesses
                    if _norm(w.get("asset")).casefold() == _norm(asset.primary_path).casefold()
                    and str(w.get("profile_id") or "").casefold() == profile.profile_id.casefold()
                    and str(w.get("lod") or "").casefold() == lod
                    and str(w.get("object") or "").casefold() == str(node).casefold()
                    and w.get("status") == "PASS_REPORTED"
                ]
                rows.append({
                    "profile_id": profile.profile_id,
                    "profile_version": profile.profile_version,
                    "asset_id": asset.asset_id,
                    "asset": asset.primary_path,
                    "lod": lod,
                    "object": node,
                    "candidate_eligible": bool(eligible_name),
                    "automatic_candidate_result": (auto or {}).get("result"),
                    "automatic_artifact_sha256": auto_artifact_sha or None,
                    "human_review_result": (human or {}).get("result"),
                    "human_review_artifact_sha256": human_artifact_sha or None,
                    "review_matches_candidate_artifact": review_matches_candidate_artifact,
                    "external_real_blender_reported": bool(external_matches),
                    "external_reported_artifact_sha256": (external_matches[-1].get("artifact_sha256") if external_matches else None),
                    "controlled_edit_proven": (auto or {}).get("result") == "PASS",
                    "human_visual_reviewed": (human or {}).get("result") in {"PASS", "FAIL", "SKIP"},
                    "context_pass": (auto or {}).get("result") == "PASS" and (human or {}).get("result") == "PASS" and review_matches_candidate_artifact,
                    "rigid_candidate_context_key": candidates[-1][0] if candidates else None,
                    "production_authorized": False,
                })

    eligible = [r for r in rows if r["candidate_eligible"]]
    return {
        "format": PLAN_FORMAT,
        "status": "PASS" if not errors else "WARN",
        "profile_count": len(profiles),
        "row_count": len(rows),
        "eligible_row_count": len(eligible),
        "external_real_blender_reported_count": sum(1 for r in rows if r.get("external_real_blender_reported")),
        "controlled_edit_pass_count": sum(1 for r in rows if r["controlled_edit_proven"]),
        "human_review_pass_count": sum(1 for r in rows if r["human_review_result"] == "PASS"),
        "context_pass_count": sum(1 for r in rows if r["context_pass"]),
        "rows": rows,
        "errors": errors,
        "interpretation": "External reported witnesses are preserved but do not count as reverified controlled-edit PASS. Context PASS requires a locally reverified controlled candidate edit and explicit human visual PASS for the same profile/LOD/object AND the same artifact SHA-256. It is still below runtime and production authorization.",
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
