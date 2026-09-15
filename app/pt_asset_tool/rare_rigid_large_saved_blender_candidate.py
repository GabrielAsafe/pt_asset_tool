from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import shutil
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_edit import (
    _at_dragon_binding,
    _reimport_and_check_transaction,
    prepare_at_dragon_edit_workspace,
    write_at_dragon_edit_workspace,
)
from .rare_rigid_geometry import _parse_skeleton_tms
from .rare_rigid_large_transaction_probe import (
    EXPECTED_WRITER_HASHES,
    PROBE_COUNTS,
    PROBE_MAX,
    discover_large_representatives,
)
from .rare_rigid_multibone_bridge import TARGET
from .rare_support import prepare_model062_tooling_source
from .utils import run_logged, sha256_file
from . import rare_rigid_multivertex as mv

FORMAT = "PT_RARE_RIGID_LARGE_SAVED_BLENDER_CANDIDATE_AUDIT_V2"
RELEASE_VERSION = "0.8.16"
PRIOR_REPORT = "pt_build/rare_rigid_large_transaction_workflow_v0814.json"
PRIOR_FAILED_REPORT = "pt_build/rare_rigid_large_saved_blender_workflow_v0815.json"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(root / rel) for rel in EXPECTED_WRITER_HASHES}


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _prior_gate(root: pathlib.Path) -> dict[str, Any]:
    p = root / PRIOR_REPORT
    if not p.is_file():
        raise RuntimeError(f"PRIOR_V0814_REPORT_MISSING:{p}")
    r = _json(p)
    checks = [
        r.get("format") == "PT_RARE_RIGID_LARGE_TRANSACTION_PROBE_AUDIT_V1",
        r.get("status") == "PASS",
        list(r.get("probe_vertex_counts") or []) == list(PROBE_COUNTS),
        bool(r.get("probe_representatives_complete")),
        r.get("writer_modules_modified") is False,
        r.get("client_modified") is False,
        int(r.get("artist_writer_max_vertices", -1)) == 4,
        r.get("large_transaction_write_authorized") is False,
        r.get("certified_writer_hashes_after") == EXPECTED_WRITER_HASHES,
    ]
    if not all(checks):
        raise RuntimeError(f"PRIOR_V0814_GATE_NOT_STRICT_PASS:{r}")
    rows = list(r.get("rows") or [])
    if [int(x.get("changed_vertex_count", -1)) for x in rows] != list(PROBE_COUNTS):
        raise RuntimeError("PRIOR_V0814_ROWS_MISMATCH")
    if not all(x.get("check") == "PASS" for x in rows):
        raise RuntimeError("PRIOR_V0814_ROW_FAIL")
    return r


def _prior_v0815_failure(root: pathlib.Path) -> dict[str, Any]:
    p = root / PRIOR_FAILED_REPORT
    if not p.is_file():
        raise RuntimeError(f"PRIOR_V0815_FAIL_REPORT_MISSING:{p}")
    r = _json(p)
    rows = list(r.get("rows") or [])
    checks = [
        r.get("format") == "PT_RARE_RIGID_LARGE_SAVED_BLENDER_CANDIDATE_AUDIT_V1",
        r.get("status") == "FAIL",
        [int(x.get("changed_vertex_count", -1)) for x in rows] == list(PROBE_COUNTS),
        all(x.get("status") == "PASS" for x in rows),
        r.get("live_writer_five_vertex_saved_blender_blocked") is True,
        r.get("live_writer_output_created") is False,
        r.get("negative_saved_blender_blocked") is True,
        r.get("negative_output_created") is False,
        r.get("candidate_certification_written") is True,
        int(r.get("certification_count_after", -1)) == int(r.get("certification_count_before", -1)) + 1,
        r.get("writer_modules_modified") is False,
        r.get("client_modified") is False,
        int(r.get("artist_writer_max_vertices", -1)) == 4,
        int(r.get("candidate_max_vertices", -1)) == PROBE_MAX,
        r.get("large_transaction_live_write_authorized") is False,
    ]
    if not all(checks):
        raise RuntimeError(f"PRIOR_V0815_FAIL_SIGNATURE_MISMATCH:{r}")
    return r


def _cert_file_sha(cert: CertificationRegistry) -> str | None:
    return _sha256(cert.path) if cert.path.is_file() else None


def _classify_v0815_side_effect(real_cert: CertificationRegistry, prior_fail: dict[str, Any]) -> dict[str, Any]:
    rows = real_cert.records()
    before = int(prior_fail["certification_count_before"])
    after = int(prior_fail["certification_count_after"])
    if len(rows) < after:
        raise RuntimeError(f"CERT_REGISTRY_SHORTER_THAN_V0815_REPORT:{len(rows)}<{after}")
    added = rows[before:after]
    if len(added) != 1:
        raise RuntimeError(f"V0815_SIDE_EFFECT_RECORD_COUNT_{len(added)}")
    row = added[0]
    expected = (
        row.get("asset_path") == TARGET
        and row.get("test") == "RARE_RIGID_BLENDER_PREVIEW"
        and row.get("layer") == "AUTOMATIC"
        and row.get("result") == "PASS"
    )
    if not expected:
        raise RuntimeError(f"V0815_SIDE_EFFECT_NOT_PREVIEW_CERT:{row}")
    return {
        "certification_id": row.get("certification_id"),
        "asset_path": row.get("asset_path"),
        "test": row.get("test"),
        "layer": row.get("layer"),
        "result": row.get("result"),
        "classified_as": "EXPECTED_PREVIEW_CERTIFICATION_FROM_WORKSPACE_PREPARATION",
    }


def _apply_saved_blender_plan(
    *, settings: Settings, project_root: pathlib.Path, base_blend: pathlib.Path,
    plan: dict[str, Any], out_blend: pathlib.Path, work: pathlib.Path,
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    out_blend.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_blend, out_blend)
    plan_path = work / "artist_transaction_plan.json"
    report_path = work / "artist_transaction_apply.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    script = project_root / "pt_asset_tool/blender/apply_rare_rigid_transaction_witness.py"
    run_logged(settings.blender_command() + [
        "--background", str(out_blend), "--python-exit-code", "1", "--python", str(script), "--",
        "--plan", str(plan_path), "--report", str(report_path),
    ], work / "apply_saved_artist_transaction.log")
    report = _json(report_path)
    if report.get("check") != "PASS":
        raise RuntimeError(f"SAVED_BLENDER_APPLY_FAILED:{report}")
    if int(report.get("changed_vertex_count", -1)) != len(plan.get("changed_vertices") or []):
        raise RuntimeError("SAVED_BLENDER_APPLY_COUNT_MISMATCH")
    if report.get("saved_mode") != "EDIT_MESH":
        raise RuntimeError(f"SAVED_BLENDER_NOT_EDIT_MESH:{report.get('saved_mode')}")
    return report


def _candidate_plan(prepared: pathlib.Path, skeleton: pathlib.Path, changes: list[dict[str, Any]]) -> dict[str, Any]:
    old = mv.MAX_TRANSACTION_VERTICES
    try:
        mv.MAX_TRANSACTION_VERTICES = PROBE_MAX
        return mv.plan_requested_at_dragon_transaction(prepared, skeleton, changes=changes)
    finally:
        mv.MAX_TRANSACTION_VERTICES = old


def _candidate_write_saved_blender(
    *, reg: AssetRegistry, resolver: ClientResolver, certifications: CertificationRegistry,
    settings: Settings, project_root: pathlib.Path, manifest: dict[str, Any],
    edit_blend: pathlib.Path, output: pathlib.Path, work: pathlib.Path,
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    if sha256_file(source) != manifest.get("source_sha256"):
        raise RuntimeError("PHYSICAL_SOURCE_CHANGED_SINCE_WORKSPACE")
    skeleton = pathlib.Path(resolver.resolve(manifest["motion_smb"], required=True))
    if sha256_file(skeleton) != manifest.get("skeleton_sha256"):
        raise RuntimeError("PHYSICAL_SKELETON_CHANGED_SINCE_WORKSPACE")
    prepared = pathlib.Path(manifest["prepared_source"])
    if not prepared.is_file() or sha256_file(prepared) != manifest.get("prepared_source_sha256"):
        raise RuntimeError("PREPARED_SOURCE_CHANGED_OR_MISSING")

    binding = audit_rare_rigid_binding(
        reg, resolver, project_root=project_root, work=work / "binding_recheck", bundle=None
    )
    if binding.get("status") != "PASS":
        raise RuntimeError("BINDING_RECHECK_FAILED")
    _at_dragon_binding(binding)

    extraction_report = work / "artist_edit_extract.json"
    extract_script = project_root / "pt_asset_tool/blender/extract_rare_rigid_edit.py"
    run_logged(settings.blender_command() + [
        "--background", str(edit_blend), "--python-exit-code", "1", "--python", str(extract_script), "--",
        "--baseline", str(manifest["baseline_blender_report"]), "--report", str(extraction_report),
        "--max-changed", str(PROBE_MAX),
    ], work / "extract_saved_artist_edit.log")
    extraction = _json(extraction_report)
    if extraction.get("check") != "PASS":
        raise RuntimeError(f"SAVED_BLENDER_EXTRACTION_FAILED:{extraction}")
    changed = list(extraction.get("changed_vertices") or [])
    if not (5 <= len(changed) <= PROBE_MAX):
        raise RuntimeError(f"CANDIDATE_REQUIRES_5_TO_{PROBE_MAX}_CHANGES_GOT_{len(changed)}")
    changed_objects = sorted({int(r["object_index"]) for r in changed})
    if len(changed_objects) != 1:
        raise RuntimeError("MULTI_OBJECT_TRANSACTION_DEFERRED")
    if extraction.get("writer_input_mode_before") != "EDIT_MESH":
        raise RuntimeError(f"SAVED_BLENDER_INPUT_MODE_NOT_EDIT_MESH:{extraction.get('writer_input_mode_before')}")
    if extraction.get("writer_input_mode_after") != "OBJECT":
        raise RuntimeError("EXTRACTION_DID_NOT_CANONICALIZE_TO_OBJECT")
    if not extraction.get("non_position_semantic_state_pass"):
        raise RuntimeError("NON_POSITION_SEMANTIC_STATE_FAILED")
    if float(extraction.get("max_uv_state_delta", 1.0)) != 0.0:
        raise RuntimeError("UV_STATE_DELTA_NONZERO")
    if float(extraction.get("max_physique_weight_delta", 1.0)) != 0.0:
        raise RuntimeError("PHYSIQUE_STATE_DELTA_NONZERO")

    plan = _candidate_plan(
        prepared, skeleton,
        [{
            "object_index": int(ch["object_index"]),
            "vertex_index": int(ch["vertex_index"]),
            "before_world_fixed": [int(x) for x in ch["before_world_fixed"]],
            "after_world_fixed": [int(x) for x in ch["after_world_fixed"]],
        } for ch in changed],
    )
    extract_by_vi = {int(ch["vertex_index"]): ch for ch in changed}
    for row in plan["changed_vertices"]:
        vi = int(row["vertex_index"])
        ch = extract_by_vi.get(vi)
        if ch is None or list(row["before_world_fixed"]) != list(ch["before_world_fixed"]):
            raise RuntimeError(f"WORKSPACE_BASELINE_MISMATCH_VERTEX_{vi}")

    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    staging = output.with_name(output.name + ".v0816_candidate_staging")
    prepared_output = work / "prepared_candidate_output.smd"
    staging.unlink(missing_ok=True)
    prepared_output.unlink(missing_ok=True)
    try:
        patch = mv.patch_guarded_multivertex(source, prepared, staging, plan)
        prepare_model062_tooling_source(staging, prepared_output)
        bone_tms = _parse_skeleton_tms(skeleton)
        binary = mv.compare_guarded_multivertex(source, staging, prepared_output, plan, patch, bone_tms)
        preview = _json(pathlib.Path(manifest["edit_blend"]).parent / "base_preview" / "summary.json")
        validation = _reimport_and_check_transaction(
            reg=reg, resolver=resolver, certifications=certifications, settings=settings,
            project_root=project_root, preview=preview, skeleton=skeleton,
            prepared_output=prepared_output, plan=plan, work=work / "write_validation",
        )
        staging.replace(output)
    except Exception:
        staging.unlink(missing_ok=True)
        raise

    return {
        "status": "PASS",
        "changed_vertex_count": len(changed),
        "object_index": int(plan["object_index"]),
        "changed_vertex_indices": [int(x) for x in plan["changed_vertex_indices"]],
        "changed_vertex_pairs_sharing_face": int(plan["changed_vertex_pairs_sharing_face"]),
        "affected_bone_count": int(plan["affected_bone_count"]),
        "affected_bones": list(plan["affected_bones"]),
        "max_requested_reimport_error_fixed": int(plan["max_requested_reimport_error_fixed"]),
        "max_current_source_normal_delta_fixed": int(plan["max_current_source_normal_delta_fixed"]),
        "max_target_reimport_normal_error_fixed": int(binary["max_target_reimport_normal_error_fixed"]),
        "all_non_authorized_bytes_byte_identical": bool(binary["all_non_authorized_bytes_byte_identical"]),
        "bounds_header_byte_identical": bool(binary["bounds_header_byte_identical"]),
        "binary_diff_byte_count": int(binary["diff_byte_count"]),
        "saved_blender_input_mode_before": extraction.get("writer_input_mode_before"),
        "saved_blender_input_mode_after": extraction.get("writer_input_mode_after"),
        "writer_input_object_mode_canonicalized": extraction.get("writer_input_object_mode_canonicalized"),
        "non_position_semantic_state_pass": extraction.get("non_position_semantic_state_pass"),
        "max_uv_state_delta": extraction.get("max_uv_state_delta"),
        "max_physique_weight_delta": extraction.get("max_physique_weight_delta"),
        "transport_position_error": validation["transport"].get("max_position_abs_error"),
        "transport_uv_error": validation["transport"].get("max_uv_abs_error"),
        "physique_mismatch_count": validation["transport"].get("physique_mismatch_count"),
        "transaction_witness_pass": validation["witness"].get("check") == "PASS",
        "atomic_candidate_publish": True,
        "output_smd": str(output),
        "output_sha256": _sha256(output),
        "certification_written": False,
    }


def _live_writer_rejection_on_five(
    *, reg: AssetRegistry, resolver: ClientResolver, certifications: CertificationRegistry,
    settings: Settings, project_root: pathlib.Path, manifest_path: pathlib.Path,
    five_blend: pathlib.Path, workspace: pathlib.Path, output: pathlib.Path,
) -> tuple[bool, str, dict[str, Any] | None]:
    original = _json(manifest_path)
    patched = copy.deepcopy(original)
    patched["edit_blend"] = str(five_blend)
    manifest_path.write_text(json.dumps(patched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.unlink(missing_ok=True)
    error = ""
    try:
        write_at_dragon_edit_workspace(
            reg, resolver, certifications, settings,
            project_root=project_root, output=output, workspace_root=workspace,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        manifest_path.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extract_path = workspace / "artist_edit_extract.json"
    extract = _json(extract_path) if extract_path.is_file() else None
    blocked_for_count = bool(
        extract and int(extract.get("changed_vertex_count", -1)) == 5
        and any(str(e).startswith("TOO_MANY_VERTEX_POSITION_CHANGES_5") for e in (extract.get("errors") or []))
    )
    return blocked_for_count and not output.exists(), error, extract


def run_audit(project_root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(project_root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + "_workspace")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    prior = _prior_gate(root)
    prior_fail = _prior_v0815_failure(root)
    writer_before = _writer_hashes(root)
    if writer_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError(f"CERTIFIED_WRITER_HASH_MISMATCH:{writer_before}")

    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir)
    real_cert_count_before = len(real_cert.records())
    real_cert_sha_before = _cert_file_sha(real_cert)
    v0815_side_effect = _classify_v0815_side_effect(real_cert, prior_fail)

    isolated_cert_dir = work / "isolated_certifications"
    audit_cert = CertificationRegistry(isolated_cert_dir)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)
    if source_sha_before != prior.get("client_source_sha256_after"):
        raise RuntimeError("SOURCE_SHA_DOES_NOT_MATCH_V0814_GATE")

    workspace = work / "isolated_artist_workspace"
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, audit_cert, settings,
        project_root=root, open_gui=False, reset=True,
        workspace_root=workspace, workspace_origin="AUDIT_V0816_LARGE_SAVED_BLENDER_CERT_ISOLATED",
    )
    isolated_records_after_prepare = audit_cert.records()
    if len(isolated_records_after_prepare) != 1:
        raise RuntimeError(f"ISOLATED_PREVIEW_CERT_COUNT_{len(isolated_records_after_prepare)}_NE_1")
    isolated_preview_cert = isolated_records_after_prepare[0]
    if not (
        isolated_preview_cert.get("asset_path") == TARGET
        and isolated_preview_cert.get("test") == "RARE_RIGID_BLENDER_PREVIEW"
        and isolated_preview_cert.get("result") == "PASS"
    ):
        raise RuntimeError(f"ISOLATED_PREVIEW_CERT_UNEXPECTED:{isolated_preview_cert}")
    isolated_cert_count_after_prepare = len(isolated_records_after_prepare)
    isolated_cert_sha_after_prepare = _cert_file_sha(audit_cert)

    prepared = pathlib.Path(manifest["prepared_source"])
    skeleton = pathlib.Path(manifest["skeleton"])
    discovery = discover_large_representatives(prepared, skeleton)
    if not discovery.get("complete"):
        raise RuntimeError(f"LARGE_REPRESENTATIVE_DISCOVERY_INCOMPLETE:{discovery}")

    prior_rows = {int(r["changed_vertex_count"]): r for r in prior.get("rows") or []}
    representative_match_prior = True
    for n in PROBE_COUNTS:
        plan = discovery["representatives"][f"vertices_{n}"]
        pr = prior_rows[n]
        if int(plan["object_index"]) != int(pr["object_index"]) or list(plan["changed_vertex_indices"]) != list(pr["changed_vertex_indices"]):
            representative_match_prior = False
            break
    if not representative_match_prior:
        raise RuntimeError("V0815_REPRESENTATIVES_DIVERGE_FROM_V0814_PHYSICAL_GATE")

    base_blend = pathlib.Path(manifest["edit_blend"])
    rows: list[dict[str, Any]] = []
    saved_blends: dict[int, pathlib.Path] = {}
    for n in PROBE_COUNTS:
        plan = discovery["representatives"][f"vertices_{n}"]
        row_work = work / f"candidate_{n}"
        saved_blend = row_work / f"artist_saved_transaction_{n}.blend"
        apply_report = _apply_saved_blender_plan(
            settings=settings, project_root=root, base_blend=base_blend,
            plan=plan, out_blend=saved_blend, work=row_work / "artist_apply",
        )
        saved_blends[n] = saved_blend
        candidate = _candidate_write_saved_blender(
            reg=reg, resolver=resolver, certifications=audit_cert, settings=settings,
            project_root=root, manifest=manifest, edit_blend=saved_blend,
            output=row_work / f"candidate_transaction_{n}.smd", work=row_work / "candidate_write",
        )
        candidate["saved_blender_apply_pass"] = apply_report.get("check") == "PASS"
        candidate["saved_blender_saved_mode"] = apply_report.get("saved_mode")
        candidate["candidate_only"] = True
        rows.append(candidate)

    # The exact same 5-vertex saved Blender file must still be rejected by the live V0.8.9 writer.
    live_output = work / "live_writer_5_should_not_exist.smd"
    live_blocked, live_error, live_extract = _live_writer_rejection_on_five(
        reg=reg, resolver=resolver, certifications=audit_cert, settings=settings,
        project_root=root, manifest_path=workspace / "workspace_manifest.json",
        five_blend=saved_blends[5], workspace=workspace, output=live_output,
    )

    # Negative saved-Blender control: save five edits, but push one beyond historical bounds.
    bad_plan = copy.deepcopy(discovery["representatives"]["vertices_5"])
    bad_plan["changed_vertices"][0]["requested_after_world_fixed"][0] += 1_000_000
    neg_work = work / "negative_saved_blender"
    neg_blend = neg_work / "artist_saved_invalid_5.blend"
    _apply_saved_blender_plan(
        settings=settings, project_root=root, base_blend=base_blend,
        plan=bad_plan, out_blend=neg_blend, work=neg_work / "artist_apply",
    )
    neg_output = neg_work / "candidate_negative_should_not_exist.smd"
    negative_blocked = False
    negative_error = ""
    try:
        _candidate_write_saved_blender(
            reg=reg, resolver=resolver, certifications=audit_cert, settings=settings,
            project_root=root, manifest=manifest, edit_blend=neg_blend,
            output=neg_output, work=neg_work / "candidate_write",
        )
    except Exception as exc:
        negative_blocked = True
        negative_error = f"{type(exc).__name__}:{exc}"
    negative_output_created = neg_output.exists()

    writer_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_cert_count_after = len(real_cert.records())
    real_cert_sha_after = _cert_file_sha(real_cert)
    isolated_cert_count_after_candidate = len(audit_cert.records())
    isolated_cert_sha_after_candidate = _cert_file_sha(audit_cert)
    writer_unchanged = writer_before == writer_after == EXPECTED_WRITER_HASHES
    client_unchanged = source_sha_before == source_sha_after
    real_cert_unchanged = (
        real_cert_count_before == real_cert_count_after
        and real_cert_sha_before == real_cert_sha_after
    )
    candidate_cert_unchanged = (
        isolated_cert_count_after_prepare == isolated_cert_count_after_candidate
        and isolated_cert_sha_after_prepare == isolated_cert_sha_after_candidate
    )
    complete = (
        len(rows) == len(PROBE_COUNTS)
        and all(r.get("status") == "PASS" for r in rows)
        and all(r.get("saved_blender_apply_pass") and r.get("saved_blender_saved_mode") == "EDIT_MESH" for r in rows)
        and all(r.get("saved_blender_input_mode_before") == "EDIT_MESH" and r.get("saved_blender_input_mode_after") == "OBJECT" for r in rows)
        and all(r.get("all_non_authorized_bytes_byte_identical") and r.get("bounds_header_byte_identical") for r in rows)
        and all(r.get("transaction_witness_pass") and r.get("atomic_candidate_publish") for r in rows)
        and live_blocked
        and negative_blocked and not negative_output_created
        and writer_unchanged and client_unchanged and real_cert_unchanged and candidate_cert_unchanged
    )
    return {
        "format": FORMAT,
        "status": "PASS" if complete else "FAIL",
        "logical": TARGET,
        "release_version": RELEASE_VERSION,
        "base_release": "0.8.15-failed-gate-fix",
        "prior_v0814_gate_pass": True,
        "representatives_match_v0814": representative_match_prior,
        "candidate_vertex_counts": list(PROBE_COUNTS),
        "rows": rows,
        "live_writer_five_vertex_saved_blender_blocked": live_blocked,
        "live_writer_rejection_error": live_error,
        "live_writer_extraction_errors": (live_extract or {}).get("errors"),
        "live_writer_output_created": live_output.exists(),
        "negative_saved_blender_blocked": negative_blocked,
        "negative_saved_blender_error": negative_error,
        "negative_output_created": negative_output_created,
        "prior_v0815_failure_understood": True,
        "prior_v0815_side_effect_record": v0815_side_effect,
        "real_certification_count_before": real_cert_count_before,
        "real_certification_count_after": real_cert_count_after,
        "real_certification_registry_sha256_before": real_cert_sha_before,
        "real_certification_registry_sha256_after": real_cert_sha_after,
        "real_certification_registry_modified": not real_cert_unchanged,
        "isolated_preview_certification_count": isolated_cert_count_after_prepare,
        "isolated_preview_certification_id": isolated_preview_cert.get("certification_id"),
        "isolated_candidate_certification_count_after": isolated_cert_count_after_candidate,
        "candidate_certification_written": not candidate_cert_unchanged,
        "certified_writer_hashes_before": writer_before,
        "certified_writer_hashes_after": writer_after,
        "writer_modules_modified": not writer_unchanged,
        "client_source_sha256_before": source_sha_before,
        "client_source_sha256_after": source_sha_after,
        "client_modified": not client_unchanged,
        "artist_writer_max_vertices": 4,
        "candidate_max_vertices": PROBE_MAX,
        "large_transaction_live_write_authorized": False,
        "policy": {
            "scope": "isolated saved-Blender candidate writer gate for 5..8 changed vertices in one at_dragon mesh object; interior only",
            "saved_blender": "each representative is physically saved in EDIT_MESH, then re-extracted from the .blend before planning/writing",
            "candidate_widening": "MAX_TRANSACTION_VERTICES is widened to 8 only process-locally inside candidate planning; certified writer files remain byte-identical",
            "live_writer": "the byte-identical V0.8.9 live writer must reject the same five-vertex saved .blend and remains capped at four",
            "certification": "workspace preview certification is redirected to an isolated audit registry; the real append-only registry must remain count/hash identical and candidate operations may not append even inside the isolated registry after workspace preparation",
            "v0815_failure": "the one V0.8.15 registry addition is classified and preserved as the expected RARE_RIGID_BLENDER_PREVIEW record created by workspace preparation; no historical record is deleted",
            "authorization": "PASS is corrected candidate saved-Blender evidence only; live artist writes above four vertices remain unauthorized",
            "next_on_pass": "build an isolated V0.8.17 live-writer candidate capped at eight, then require physical audit and manual artist proof before authorization",
            "deferred": "cross-object transactions, extent changes, topology, and production authorization above four vertices remain fail-closed",
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Corrected isolated saved-Blender candidate gate with certification-registry isolation for at_dragon 5..8 vertex transactions")
    ap.add_argument("--root", required=True)
    ap.add_argument("--output", required=True)
    ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).expanduser().resolve()
    try:
        report = run_audit(pathlib.Path(ns.root), out)
    except Exception as exc:
        report = {
            "format": FORMAT,
            "status": "FAIL",
            "release_version": RELEASE_VERSION,
            "error": f"{type(exc).__name__}:{exc}",
            "artist_writer_max_vertices": 4,
            "candidate_max_vertices": PROBE_MAX,
            "large_transaction_live_write_authorized": False,
            "writer_modules_modified": None,
            "client_modified": None,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") == "PASS":
        print("rare_rigid_large_saved_blender_candidate=PASS counts=5,6,7,8 cert_registry_unchanged=true live_writer_max=4 live_write_authorized=false client_modified=false")
        return 0
    print("rare_rigid_large_saved_blender_candidate=FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
