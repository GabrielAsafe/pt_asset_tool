from __future__ import annotations

import argparse
import contextlib
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
from .rare_rigid_edit import prepare_at_dragon_edit_workspace
from . import rare_rigid_edit as redit
from . import rare_rigid_multivertex as mv
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, PROBE_COUNTS, PROBE_MAX, discover_large_representatives
from .rare_rigid_large_saved_blender_candidate import _apply_saved_blender_plan
from .rare_rigid_multibone_bridge import TARGET

FORMAT = "PT_RARE_RIGID_LARGE_LIVE_WRITER_CANDIDATE_AUDIT_V1"
RELEASE_VERSION = "0.8.17"
PRIOR_REPORT = "pt_build/rare_rigid_large_saved_blender_workflow_v0816.json"
CANDIDATE_TEST = "RARE_RIGID_ARTIST_GUARDED_LARGE_TRANSACTION_WRITE_CANDIDATE"
CANDIDATE_SCOPE = "AT_DRAGON_FIVE_TO_EIGHT_CHANGED_MULTIBONE_BOUNDARY_VERTICES_SINGLE_OBJECT_INTERIOR_ATOMIC_TRANSACTION_CANDIDATE_ONLY"


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


def _cert_sha(cert: CertificationRegistry) -> str | None:
    return _sha256(cert.path) if cert.path.is_file() else None


def _prior_v0816(root: pathlib.Path) -> dict[str, Any]:
    p = root / PRIOR_REPORT
    if not p.is_file():
        raise RuntimeError(f"PRIOR_V0816_REPORT_MISSING:{p}")
    r = _json(p)
    rows = list(r.get("rows") or [])
    checks = [
        r.get("format") == "PT_RARE_RIGID_LARGE_SAVED_BLENDER_CANDIDATE_AUDIT_V2",
        r.get("status") == "PASS",
        list(r.get("candidate_vertex_counts") or []) == list(PROBE_COUNTS),
        [int(x.get("changed_vertex_count", -1)) for x in rows] == list(PROBE_COUNTS),
        all(x.get("status") == "PASS" for x in rows),
        all(x.get("candidate_only") is True for x in rows),
        all(x.get("certification_written") is False for x in rows),
        r.get("live_writer_five_vertex_saved_blender_blocked") is True,
        r.get("live_writer_output_created") is False,
        r.get("negative_saved_blender_blocked") is True,
        r.get("negative_output_created") is False,
        r.get("prior_v0815_failure_understood") is True,
        r.get("real_certification_registry_modified") is False,
        r.get("candidate_certification_written") is False,
        r.get("writer_modules_modified") is False,
        r.get("client_modified") is False,
        int(r.get("artist_writer_max_vertices", -1)) == 4,
        int(r.get("candidate_max_vertices", -1)) == PROBE_MAX,
        r.get("large_transaction_live_write_authorized") is False,
        r.get("certified_writer_hashes_after") == EXPECTED_WRITER_HASHES,
    ]
    if not all(checks):
        raise RuntimeError(f"PRIOR_V0816_GATE_NOT_STRICT_PASS:{r}")
    return r


class _CandidateCertificationProxy:
    """Redirect the exact core writer's success record into candidate-only semantics."""
    def __init__(self, backing: CertificationRegistry):
        self.backing = backing
        self.directory = backing.directory
        self.path = backing.path

    def records(self) -> list[dict]:
        return self.backing.records()

    def add(self, **kwargs: Any) -> dict:
        test = str(kwargs.get("test") or "")
        metadata = dict(kwargs.get("metadata") or {})
        if test != "RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE":
            raise RuntimeError(f"UNEXPECTED_CERTIFICATION_FROM_LIVE_CANDIDATE:{test}")
        n = int(metadata.get("artist_changed_vertices", -1))
        if not (5 <= n <= PROBE_MAX):
            raise RuntimeError(f"CANDIDATE_CERT_VERTEX_COUNT_{n}_OUTSIDE_5_{PROBE_MAX}")
        metadata.update({
            "candidate_only": True,
            "candidate_release": RELEASE_VERSION,
            "candidate_max_vertices": PROBE_MAX,
            "production_authorized": False,
            "original_core_test": test,
            "original_core_write_scope": metadata.get("write_scope"),
            "write_scope": CANDIDATE_SCOPE,
        })
        kwargs["test"] = CANDIDATE_TEST
        kwargs["metadata"] = metadata
        notes = str(kwargs.get("notes") or "")
        marker = "V0.8.17 isolated live-writer candidate only; not a production authorization."
        kwargs["notes"] = (notes + " " + marker).strip()
        return self.backing.add(**kwargs)


@contextlib.contextmanager
def _candidate_widening():
    old_edit = int(redit.MAX_TRANSACTION_VERTICES)
    old_mv = int(mv.MAX_TRANSACTION_VERTICES)
    if old_edit != 4 or old_mv != 4:
        raise RuntimeError(f"LIVE_WRITER_BASE_LIMIT_NOT_4:edit={old_edit}:mv={old_mv}")
    redit.MAX_TRANSACTION_VERTICES = PROBE_MAX
    mv.MAX_TRANSACTION_VERTICES = PROBE_MAX
    try:
        yield
    finally:
        redit.MAX_TRANSACTION_VERTICES = old_edit
        mv.MAX_TRANSACTION_VERTICES = old_mv


def _patch_manifest_edit_blend(workspace: pathlib.Path, edit_blend: pathlib.Path) -> dict[str, Any]:
    p = workspace / "workspace_manifest.json"
    original = _json(p)
    patched = copy.deepcopy(original)
    patched["edit_blend"] = str(pathlib.Path(edit_blend).resolve())
    p.write_text(json.dumps(patched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return original


def _restore_manifest(workspace: pathlib.Path, original: dict[str, Any]) -> None:
    (workspace / "workspace_manifest.json").write_text(
        json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _candidate_live_write(
    *, reg: AssetRegistry, resolver: ClientResolver, cert: CertificationRegistry, settings: Settings,
    project_root: pathlib.Path, workspace: pathlib.Path, edit_blend: pathlib.Path, output: pathlib.Path,
) -> dict[str, Any]:
    original = _patch_manifest_edit_blend(workspace, edit_blend)
    proxy = _CandidateCertificationProxy(cert)
    try:
        with _candidate_widening():
            result = redit.write_at_dragon_edit_workspace(
                reg, resolver, proxy, settings,
                project_root=project_root, output=output, workspace_root=workspace,
            )
            if int(redit.MAX_TRANSACTION_VERTICES) != PROBE_MAX or int(mv.MAX_TRANSACTION_VERTICES) != PROBE_MAX:
                raise RuntimeError("CANDIDATE_LIMIT_NOT_ACTIVE_DURING_WRITE")
    finally:
        _restore_manifest(workspace, original)
    if int(redit.MAX_TRANSACTION_VERTICES) != 4 or int(mv.MAX_TRANSACTION_VERTICES) != 4:
        raise RuntimeError("CANDIDATE_LIMIT_NOT_RESTORED_TO_4")
    n = int(result.get("artist_changed_vertices", -1))
    if not (5 <= n <= PROBE_MAX):
        raise RuntimeError(f"LIVE_CANDIDATE_RESULT_COUNT_{n}_OUTSIDE_5_{PROBE_MAX}")
    return {
        **result,
        "core_write_format_raw": result.get("format"),
        "core_write_scope_raw": result.get("write_scope"),
        "candidate_format": "PT_RARE_RIGID_GUARDED_LARGE_EDIT_WRITE_CANDIDATE_V1",
        "candidate_write_scope": CANDIDATE_SCOPE,
        "candidate_only": True,
        "candidate_live_writer_max_vertices": PROBE_MAX,
        "production_live_writer_max_vertices": 4,
        "production_authorized": False,
        "exact_core_writer_function_exercised": "write_at_dragon_edit_workspace",
        "process_local_limit_restored": True,
    }


def _production_writer_rejects_five(
    *, reg: AssetRegistry, resolver: ClientResolver, cert: CertificationRegistry, settings: Settings,
    project_root: pathlib.Path, workspace: pathlib.Path, edit_blend: pathlib.Path, output: pathlib.Path,
) -> tuple[bool, str, dict[str, Any] | None]:
    original = _patch_manifest_edit_blend(workspace, edit_blend)
    output.unlink(missing_ok=True)
    error = ""
    try:
        redit.write_at_dragon_edit_workspace(
            reg, resolver, cert, settings,
            project_root=project_root, output=output, workspace_root=workspace,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        _restore_manifest(workspace, original)
    extract_path = workspace / "artist_edit_extract.json"
    extraction = _json(extract_path) if extract_path.is_file() else None
    blocked = bool(
        extraction
        and int(extraction.get("changed_vertex_count", -1)) == 5
        and any(str(e).startswith("TOO_MANY_VERTEX_POSITION_CHANGES_5") for e in (extraction.get("errors") or []))
    )
    return blocked and not output.exists(), error, extraction


def _nine_vertex_apply_plan(eight_plan: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    plan = copy.deepcopy(eight_plan)
    oi = int(plan["object_index"])
    used = {int(r["vertex_index"]) for r in plan.get("changed_vertices") or []}
    base_row = next((r for r in baseline.get("rows") or [] if int(r.get("object_index", -1)) == oi), None)
    if base_row is None:
        raise RuntimeError(f"BASELINE_OBJECT_{oi}_MISSING")
    positions = list(base_row.get("positions_fixed") or [])
    for vi, before in enumerate(positions):
        if vi in used:
            continue
        after = [int(x) for x in before]
        after[2] += 1
        plan["changed_vertices"].append({
            "vertex_index": vi,
            "before_world_fixed": [int(x) for x in before],
            "requested_after_world_fixed": after,
        })
        return plan
    raise RuntimeError("NO_NINTH_VERTEX_AVAILABLE")


def _attempt_candidate_should_fail(
    *, reg: AssetRegistry, resolver: ClientResolver, cert: CertificationRegistry, settings: Settings,
    project_root: pathlib.Path, workspace: pathlib.Path, edit_blend: pathlib.Path, output: pathlib.Path,
) -> tuple[bool, str, dict[str, Any] | None]:
    original = _patch_manifest_edit_blend(workspace, edit_blend)
    output.unlink(missing_ok=True)
    error = ""
    try:
        with _candidate_widening():
            redit.write_at_dragon_edit_workspace(
                reg, resolver, _CandidateCertificationProxy(cert), settings,
                project_root=project_root, output=output, workspace_root=workspace,
            )
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        _restore_manifest(workspace, original)
    if int(redit.MAX_TRANSACTION_VERTICES) != 4 or int(mv.MAX_TRANSACTION_VERTICES) != 4:
        raise RuntimeError("FAILED_CANDIDATE_DID_NOT_RESTORE_LIMIT_4")
    extract_path = workspace / "artist_edit_extract.json"
    extraction = _json(extract_path) if extract_path.is_file() else None
    return not output.exists(), error, extraction


def run_audit(project_root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(project_root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + "_workspace")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    prior = _prior_v0816(root)
    writer_before = _writer_hashes(root)
    if writer_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError(f"CERTIFIED_WRITER_HASH_MISMATCH:{writer_before}")
    if int(redit.MAX_TRANSACTION_VERTICES) != 4 or int(mv.MAX_TRANSACTION_VERTICES) != 4:
        raise RuntimeError("INSTALLED_PRODUCTION_LIMIT_NOT_4_AT_START")

    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir)
    real_count_before = len(real_cert.records())
    real_sha_before = _cert_sha(real_cert)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)
    if source_sha_before != prior.get("client_source_sha256_after"):
        raise RuntimeError("SOURCE_SHA_DOES_NOT_MATCH_V0816_GATE")

    isolated_cert = CertificationRegistry(work / "isolated_certifications")
    master_workspace = work / "master_isolated_artist_workspace"
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, isolated_cert, settings,
        project_root=root, open_gui=False, reset=True,
        workspace_root=master_workspace, workspace_origin="AUDIT_V0817_ISOLATED_LIVE_WRITER_CANDIDATE",
    )
    preview_records = isolated_cert.records()
    if len(preview_records) != 1 or preview_records[0].get("test") != "RARE_RIGID_BLENDER_PREVIEW" or preview_records[0].get("result") != "PASS":
        raise RuntimeError(f"ISOLATED_PREVIEW_CERT_UNEXPECTED:{preview_records}")
    candidate_cert_start_count = len(preview_records)

    prepared = pathlib.Path(manifest["prepared_source"])
    skeleton = pathlib.Path(manifest["skeleton"])
    discovery = discover_large_representatives(prepared, skeleton)
    if not discovery.get("complete"):
        raise RuntimeError(f"LARGE_REPRESENTATIVE_DISCOVERY_INCOMPLETE:{discovery}")

    prior_rows = {int(r["changed_vertex_count"]): r for r in prior.get("rows") or []}
    for n in PROBE_COUNTS:
        plan = discovery["representatives"][f"vertices_{n}"]
        pr = prior_rows[n]
        if int(plan["object_index"]) != int(pr["object_index"]) or list(plan["changed_vertex_indices"]) != list(pr["changed_vertex_indices"]):
            raise RuntimeError(f"V0817_REPRESENTATIVE_{n}_DIVERGES_FROM_V0816")

    base_blend = pathlib.Path(manifest["edit_blend"])
    rows: list[dict[str, Any]] = []
    saved_blends: dict[int, pathlib.Path] = {}
    for n in PROBE_COUNTS:
        plan = discovery["representatives"][f"vertices_{n}"]
        row_root = work / f"live_candidate_{n}"
        saved_blend = row_root / f"artist_saved_transaction_{n}.blend"
        apply_report = _apply_saved_blender_plan(
            settings=settings, project_root=root, base_blend=base_blend,
            plan=plan, out_blend=saved_blend, work=row_root / "artist_apply",
        )
        saved_blends[n] = saved_blend
        row_workspace = row_root / "writer_workspace"
        shutil.copytree(master_workspace, row_workspace)
        out_smd = row_root / f"live_candidate_transaction_{n}.smd"
        cert_before = len(isolated_cert.records())
        result = _candidate_live_write(
            reg=reg, resolver=resolver, cert=isolated_cert, settings=settings,
            project_root=root, workspace=row_workspace, edit_blend=saved_blend, output=out_smd,
        )
        cert_after = len(isolated_cert.records())
        if cert_after != cert_before + 1:
            raise RuntimeError(f"CANDIDATE_{n}_CERT_COUNT_DELTA_{cert_after-cert_before}_NE_1")
        last = isolated_cert.records()[-1]
        if last.get("test") != CANDIDATE_TEST or last.get("result") != "PASS":
            raise RuntimeError(f"CANDIDATE_{n}_CERT_UNEXPECTED:{last}")
        meta = dict(last.get("metadata") or {})
        if int(meta.get("artist_changed_vertices", -1)) != n or meta.get("candidate_only") is not True or meta.get("production_authorized") is not False:
            raise RuntimeError(f"CANDIDATE_{n}_CERT_METADATA_UNEXPECTED:{meta}")
        if result.get("status") != "PASS" or int(result.get("artist_changed_vertices", -1)) != n:
            raise RuntimeError(f"CANDIDATE_{n}_WRITE_FAILED:{result}")
        if result.get("writer_input_mode_before") != "EDIT_MESH" or result.get("writer_input_mode_after") != "OBJECT":
            raise RuntimeError(f"CANDIDATE_{n}_MODE_PATH_UNEXPECTED")
        if result.get("all_non_authorized_bytes_byte_identical") is not True or result.get("bounds_header_byte_identical") is not True:
            raise RuntimeError(f"CANDIDATE_{n}_BYTE_GUARD_FAIL")
        if result.get("transaction_atomic") is not True or result.get("atomic_output_replace") is not True:
            raise RuntimeError(f"CANDIDATE_{n}_ATOMICITY_FAIL")
        if int(result.get("max_transaction_vertices_authorized", -1)) != PROBE_MAX:
            raise RuntimeError(f"CANDIDATE_{n}_CORE_MAX_NOT_8")
        expected_sha = str(prior_rows[n].get("output_sha256"))
        if _sha256(out_smd) != expected_sha:
            raise RuntimeError(f"CANDIDATE_{n}_OUTPUT_SHA_DIVERGES_FROM_V0816")
        rows.append({
            "status": "PASS",
            "changed_vertex_count": n,
            "object_index": result.get("object_index"),
            "changed_vertex_indices": result.get("changed_vertex_indices"),
            "changed_vertex_pairs_sharing_face": result.get("changed_vertex_pairs_sharing_face"),
            "affected_bone_count": result.get("affected_bone_count"),
            "affected_bones": result.get("affected_bones"),
            "max_requested_reimport_error_fixed": result.get("max_requested_reimport_error_fixed"),
            "max_current_source_normal_delta_fixed": result.get("max_current_source_normal_delta_fixed"),
            "max_target_reimport_normal_error_fixed": result.get("max_target_reimport_normal_error_fixed"),
            "all_non_authorized_bytes_byte_identical": result.get("all_non_authorized_bytes_byte_identical"),
            "bounds_header_byte_identical": result.get("bounds_header_byte_identical"),
            "transport_position_error": result.get("transport_position_error"),
            "transport_uv_error": result.get("transport_uv_error"),
            "physique_mismatch_count": result.get("physique_mismatch_count"),
            "writer_input_mode_before": result.get("writer_input_mode_before"),
            "writer_input_mode_after": result.get("writer_input_mode_after"),
            "non_position_semantic_state_pass": result.get("non_position_semantic_state_pass"),
            "transaction_atomic": result.get("transaction_atomic"),
            "atomic_output_replace": result.get("atomic_output_replace"),
            "joint_final_geometry_guard": result.get("joint_final_geometry_guard"),
            "exact_core_writer_function_exercised": result.get("exact_core_writer_function_exercised"),
            "process_local_limit_restored": result.get("process_local_limit_restored"),
            "candidate_certification_id": last.get("certification_id"),
            "candidate_certification_test": last.get("test"),
            "candidate_write_scope": result.get("candidate_write_scope"),
            "core_write_scope_raw": result.get("core_write_scope_raw"),
            "output_smd": str(out_smd),
            "output_sha256": _sha256(out_smd),
            "matches_v0816_output_sha256": True,
            "saved_blender_apply_pass": apply_report.get("check") == "PASS",
            "saved_blender_saved_mode": apply_report.get("saved_mode"),
            "candidate_only": True,
            "production_authorized": False,
        })

    candidate_cert_count_after_rows = len(isolated_cert.records())
    candidate_records = [r for r in isolated_cert.records() if r.get("test") == CANDIDATE_TEST]
    if len(candidate_records) != len(PROBE_COUNTS):
        raise RuntimeError(f"CANDIDATE_CERT_RECORD_COUNT_{len(candidate_records)}_NE_{len(PROBE_COUNTS)}")

    # Production path remains capped at 4 after candidate contexts restore module globals.
    prod_workspace = work / "production_limit_control_workspace"
    shutil.copytree(master_workspace, prod_workspace)
    prod_out = work / "production_writer_5_should_not_exist.smd"
    cert_before_prod = len(isolated_cert.records())
    prod_blocked, prod_error, prod_extract = _production_writer_rejects_five(
        reg=reg, resolver=resolver, cert=isolated_cert, settings=settings,
        project_root=root, workspace=prod_workspace, edit_blend=saved_blends[5], output=prod_out,
    )
    prod_cert_unchanged = len(isolated_cert.records()) == cert_before_prod

    # Candidate hard cap control: 9 saved vertex edits must fail in extraction before planning or certification.
    baseline = _json(pathlib.Path(manifest["baseline_blender_report"]))
    nine_plan = _nine_vertex_apply_plan(discovery["representatives"]["vertices_8"], baseline)
    nine_root = work / "candidate_nine_vertex_control"
    nine_blend = nine_root / "artist_saved_transaction_9.blend"
    nine_apply = _apply_saved_blender_plan(
        settings=settings, project_root=root, base_blend=base_blend,
        plan=nine_plan, out_blend=nine_blend, work=nine_root / "artist_apply",
    )
    nine_workspace = nine_root / "writer_workspace"
    shutil.copytree(master_workspace, nine_workspace)
    nine_out = nine_root / "candidate_9_should_not_exist.smd"
    cert_before_nine = len(isolated_cert.records())
    nine_blocked, nine_error, nine_extract = _attempt_candidate_should_fail(
        reg=reg, resolver=resolver, cert=isolated_cert, settings=settings,
        project_root=root, workspace=nine_workspace, edit_blend=nine_blend, output=nine_out,
    )
    nine_count_gate = bool(
        nine_extract
        and int(nine_extract.get("changed_vertex_count", -1)) == 9
        and any(str(e).startswith("TOO_MANY_VERTEX_POSITION_CHANGES_9") for e in (nine_extract.get("errors") or []))
        and int(nine_extract.get("max_changed_authorized", -1)) == PROBE_MAX
    )
    nine_cert_unchanged = len(isolated_cert.records()) == cert_before_nine

    # Guard control: candidate widening must not bypass extent/bounds protection.
    bad_plan = copy.deepcopy(discovery["representatives"]["vertices_5"])
    bad_plan["changed_vertices"][0]["requested_after_world_fixed"][0] += 1_000_000
    neg_root = work / "candidate_bounds_control"
    neg_blend = neg_root / "artist_saved_invalid_5.blend"
    neg_apply = _apply_saved_blender_plan(
        settings=settings, project_root=root, base_blend=base_blend,
        plan=bad_plan, out_blend=neg_blend, work=neg_root / "artist_apply",
    )
    neg_workspace = neg_root / "writer_workspace"
    shutil.copytree(master_workspace, neg_workspace)
    neg_out = neg_root / "candidate_bounds_should_not_exist.smd"
    cert_before_neg = len(isolated_cert.records())
    neg_blocked, neg_error, neg_extract = _attempt_candidate_should_fail(
        reg=reg, resolver=resolver, cert=isolated_cert, settings=settings,
        project_root=root, workspace=neg_workspace, edit_blend=neg_blend, output=neg_out,
    )
    neg_bound_gate = "EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED" in neg_error
    neg_cert_unchanged = len(isolated_cert.records()) == cert_before_neg

    writer_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_count_after = len(real_cert.records())
    real_sha_after = _cert_sha(real_cert)
    limits_restored = int(redit.MAX_TRANSACTION_VERTICES) == 4 and int(mv.MAX_TRANSACTION_VERTICES) == 4
    writer_unchanged = writer_before == writer_after == EXPECTED_WRITER_HASHES
    client_unchanged = source_sha_before == source_sha_after
    real_cert_unchanged = real_count_before == real_count_after and real_sha_before == real_sha_after
    isolated_final = isolated_cert.records()
    candidate_final = [r for r in isolated_final if r.get("test") == CANDIDATE_TEST]
    candidate_cert_counts = sorted(int((r.get("metadata") or {}).get("artist_changed_vertices", -1)) for r in candidate_final)

    complete = (
        len(rows) == len(PROBE_COUNTS)
        and all(r.get("status") == "PASS" for r in rows)
        and all(r.get("saved_blender_apply_pass") and r.get("saved_blender_saved_mode") == "EDIT_MESH" for r in rows)
        and all(r.get("process_local_limit_restored") for r in rows)
        and all(r.get("matches_v0816_output_sha256") for r in rows)
        and candidate_cert_counts == list(PROBE_COUNTS)
        and candidate_cert_count_after_rows == candidate_cert_start_count + len(PROBE_COUNTS)
        and prod_blocked and prod_cert_unchanged and not prod_out.exists()
        and nine_blocked and nine_count_gate and nine_cert_unchanged and not nine_out.exists()
        and neg_blocked and neg_bound_gate and neg_cert_unchanged and not neg_out.exists()
        and writer_unchanged and client_unchanged and real_cert_unchanged and limits_restored
    )

    return {
        "format": FORMAT,
        "status": "PASS" if complete else "FAIL",
        "logical": TARGET,
        "release_version": RELEASE_VERSION,
        "base_release": "0.8.16",
        "prior_v0816_gate_pass": True,
        "candidate_vertex_counts": list(PROBE_COUNTS),
        "candidate_live_writer_max_vertices": PROBE_MAX,
        "production_live_writer_max_vertices": 4,
        "exact_core_writer_function_exercised": "write_at_dragon_edit_workspace",
        "process_local_widening_only": True,
        "process_local_limits_restored": limits_restored,
        "rows": rows,
        "candidate_certification_test": CANDIDATE_TEST,
        "isolated_preview_certification_count": candidate_cert_start_count,
        "isolated_candidate_certification_count": len(candidate_final),
        "isolated_candidate_certification_vertex_counts": candidate_cert_counts,
        "candidate_certification_count_after_rows": candidate_cert_count_after_rows,
        "production_writer_five_vertex_blocked": prod_blocked,
        "production_writer_rejection_error": prod_error,
        "production_writer_extraction_errors": list((prod_extract or {}).get("errors") or []),
        "production_writer_output_created": prod_out.exists(),
        "production_writer_certification_written": not prod_cert_unchanged,
        "candidate_nine_vertex_blocked": nine_blocked and nine_count_gate,
        "candidate_nine_vertex_rejection_error": nine_error,
        "candidate_nine_vertex_extraction_errors": list((nine_extract or {}).get("errors") or []),
        "candidate_nine_vertex_max_changed_authorized": (nine_extract or {}).get("max_changed_authorized"),
        "candidate_nine_vertex_output_created": nine_out.exists(),
        "candidate_nine_vertex_certification_written": not nine_cert_unchanged,
        "candidate_bounds_negative_blocked": neg_blocked and neg_bound_gate,
        "candidate_bounds_negative_error": neg_error,
        "candidate_bounds_negative_output_created": neg_out.exists(),
        "candidate_bounds_negative_certification_written": not neg_cert_unchanged,
        "real_certification_count_before": real_count_before,
        "real_certification_count_after": real_count_after,
        "real_certification_registry_sha256_before": real_sha_before,
        "real_certification_registry_sha256_after": real_sha_after,
        "real_certification_registry_modified": not real_cert_unchanged,
        "certified_writer_hashes_before": writer_before,
        "certified_writer_hashes_after": writer_after,
        "writer_modules_modified": not writer_unchanged,
        "client_source_sha256_before": source_sha_before,
        "client_source_sha256_after": source_sha_after,
        "client_modified": not client_unchanged,
        "large_transaction_live_write_authorized": False,
        "manual_artist_proof_required_before_authorization": True,
        "policy": {
            "scope": "isolated live-writer candidate gate for 5..8 changed vertices in one at_dragon mesh object; interior only",
            "core_path": "the exact V0.8.9 write_at_dragon_edit_workspace function is exercised with MAX_TRANSACTION_VERTICES widened to 8 only process-locally; both module constants are restored to 4 after every attempt",
            "certification": "successful candidate writes append only candidate-labelled records to an isolated registry; the real append-only registry must remain count/hash identical",
            "production_writer": "without process-local widening, the byte-identical production writer must still reject the same five-vertex saved Blender edit",
            "upper_bound": "a nine-vertex saved Blender edit must be rejected by extraction at max_changed=8 with zero output and zero certification",
            "guards": "extent/bounds negative remains blocked with zero output and zero certification",
            "authorization": "PASS proves isolated live-writer candidate behavior only; production artist writes above four vertices remain unauthorized",
            "next_on_pass": "build V0.8.18 interactive candidate workspace/write command for one manual 5..8 artist transaction, still isolated from production certification, then promote only after physical manual PASS",
            "deferred": "cross-object transactions, extent changes, topology, and production authorization above four vertices remain fail-closed",
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Isolated live-writer candidate gate for at_dragon 5..8 vertex transactions")
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
            "candidate_live_writer_max_vertices": PROBE_MAX,
            "production_live_writer_max_vertices": 4,
            "large_transaction_live_write_authorized": False,
            "manual_artist_proof_required_before_authorization": True,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") == "PASS":
        print("rare_rigid_large_live_writer_candidate=PASS counts=5,6,7,8 candidate_max=8 production_max=4 nine_blocked=true real_cert_unchanged=true live_write_authorized=false client_modified=false")
        return 0
    print("rare_rigid_large_live_writer_candidate=FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
