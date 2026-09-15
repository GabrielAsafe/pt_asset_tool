from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from . import rare_rigid_edit as redit
from . import rare_rigid_multivertex as mv
from .rare_rigid_edit import prepare_at_dragon_edit_workspace, audit_rare_rigid_edit_workflow
from .rare_rigid_large_live_writer_candidate import run_audit as run_live_candidate_audit
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, PROBE_MAX, discover_large_representatives
from .rare_rigid_multivertex import plan_requested_at_dragon_transaction
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_large_production import POLICY_FORMAT, POLICY_REL, MANUAL_REL

FORMAT = "PT_RARE_RIGID_LARGE_PRODUCTION_PROMOTION_AUDIT_V2"
RELEASE_VERSION = "0.8.21"
PRIOR_LIVE = pathlib.Path("pt_build/rare_rigid_large_live_writer_candidate_workflow_v0817.json")
PRIOR_FAILED_PROMOTION = pathlib.Path("pt_build/rare_rigid_large_production_promotion_workflow_v0820.json")


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(root / rel) for rel in EXPECTED_WRITER_HASHES}


def _cert_sha(cert: CertificationRegistry) -> str | None:
    return _sha256(cert.path) if cert.path.is_file() else None


def _strict_manual(root: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path]:
    p = root / MANUAL_REL
    if not p.is_file():
        raise RuntimeError(f"MANUAL_V0819_REPORT_MISSING:{p}")
    r = _json(p)
    checks = [
        r.get("format") == "PT_RARE_RIGID_LARGE_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V2",
        r.get("status") == "PASS",
        r.get("manual_artist_proof") is True,
        int(r.get("artist_changed_vertices", -1)) == 5,
        r.get("all_non_authorized_bytes_byte_identical") is True,
        r.get("bounds_header_byte_identical") is True,
        float(r.get("transport_position_error", 999)) == 0.0,
        float(r.get("transport_uv_error", 999)) == 0.0,
        int(r.get("physique_mismatch_count", -1)) == 0,
        r.get("transaction_atomic") is True,
        r.get("atomic_output_replace") is True,
        r.get("joint_final_geometry_guard") is True,
        r.get("candidate_certification_isolated") is True,
        r.get("real_certification_registry_modified") is False,
        r.get("writer_modules_modified") is False,
        r.get("client_modified") is False,
        int(r.get("candidate_max_vertices", -1)) == PROBE_MAX,
        int(r.get("production_writer_max_vertices", -1)) == 4,
        r.get("production_authorized") is False,
        r.get("ready_for_promotion_gate") is True,
    ]
    if not all(checks):
        raise RuntimeError("MANUAL_V0819_NOT_STRICT_PASS")
    out = pathlib.Path(str(r.get("output_smd") or ""))
    if not out.is_file() or _sha256(out) != r.get("output_sha256"):
        raise RuntimeError("MANUAL_V0819_OUTPUT_HASH_MISMATCH")
    return r, p


def _strict_prior_live(root: pathlib.Path) -> dict[str, Any]:
    p = root / PRIOR_LIVE
    if not p.is_file():
        raise RuntimeError(f"PRIOR_V0817_REPORT_MISSING:{p}")
    r = _json(p)
    rows = list(r.get("rows") or [])
    checks = [
        r.get("format") == "PT_RARE_RIGID_LARGE_LIVE_WRITER_CANDIDATE_AUDIT_V1",
        r.get("status") == "PASS",
        [int(x.get("changed_vertex_count", -1)) for x in rows] == [5, 6, 7, 8],
        all(x.get("status") == "PASS" for x in rows),
        r.get("candidate_nine_vertex_blocked") is True,
        r.get("candidate_bounds_negative_blocked") is True,
        r.get("real_certification_registry_modified") is False,
        r.get("writer_modules_modified") is False,
        r.get("client_modified") is False,
        r.get("large_transaction_live_write_authorized") is False,
    ]
    if not all(checks):
        raise RuntimeError("PRIOR_V0817_NOT_STRICT_PASS")
    return r


def _strict_prior_failed_promotion(root: pathlib.Path) -> dict[str, Any]:
    p = root / PRIOR_FAILED_PROMOTION
    if not p.is_file():
        raise RuntimeError(f"PRIOR_V0820_FAILURE_REPORT_MISSING:{p}")
    r = _json(p)
    checks = [
        r.get("format") == "PT_RARE_RIGID_LARGE_PRODUCTION_PROMOTION_AUDIT_V1",
        r.get("status") == "FAIL",
        str(r.get("error") or "") == "KeyError:'object_index'",
        r.get("production_live_write_authorized") is False,
        int(r.get("production_max_vertices", -1)) == 4,
    ]
    if not all(checks):
        raise RuntimeError("PRIOR_V0820_FAILURE_NOT_EXPECTED_SCHEMA_BUG")
    return r


def _cross_object_changes_from_discovery(d: dict[str, Any]) -> list[dict[str, Any]]:
    if not d.get("complete"):
        raise RuntimeError("PROMOTION_DISCOVERY_INCOMPLETE")
    reps = dict(d.get("representatives") or {})
    ordered = [reps.get(f"vertices_{n}") for n in (5, 6, 7, 8)]
    ordered = [r for r in ordered if isinstance(r, dict)]
    if len(ordered) < 2:
        raise RuntimeError("PROMOTION_REPRESENTATIVES_MISSING")

    first = ordered[0]
    first_oi = int(first["object_index"])
    second = next((r for r in ordered[1:] if int(r["object_index"]) != first_oi), None)
    if second is None:
        raise RuntimeError("NO_DISTINCT_OBJECT_REPRESENTATIVES")
    second_oi = int(second["object_index"])

    a = list(first.get("changed_vertices") or [])[0]
    b = list(second.get("changed_vertices") or [])[0]
    # Physical plan schema stores object_index on the representative, not on each
    # changed_vertices row. Keep that distinction explicit to avoid another schema drift.
    return [
        {
            "object_index": first_oi,
            "vertex_index": int(a["vertex_index"]),
            "after_world_fixed": list(a["requested_after_world_fixed"]),
        },
        {
            "object_index": second_oi,
            "vertex_index": int(b["vertex_index"]),
            "after_world_fixed": list(b["requested_after_world_fixed"]),
        },
    ]


def _cross_object_negative(prepared: pathlib.Path, skeleton: pathlib.Path) -> tuple[bool, str]:
    d = discover_large_representatives(prepared, skeleton)
    changes = _cross_object_changes_from_discovery(d)
    try:
        plan_requested_at_dragon_transaction(prepared, skeleton, changes=changes)
    except Exception as exc:
        msg = f"{type(exc).__name__}:{exc}"
        return "MULTI_OBJECT_TRANSACTION_DEFERRED" in msg, msg
    return False, "UNEXPECTED_PASS"


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + "_workspace")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # A fresh promotion audit starts deauthorized. A previous policy, if any, is removed
    # and is recreated only after every physical/regression gate passes.
    policy_path = root / POLICY_REL
    policy_path.unlink(missing_ok=True)

    manual, manual_path = _strict_manual(root)
    prior_live = _strict_prior_live(root)
    prior_failed_promotion = _strict_prior_failed_promotion(root)
    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_PROMOTION")
    if int(redit.MAX_TRANSACTION_VERTICES) != 4 or int(mv.MAX_TRANSACTION_VERTICES) != 4:
        raise RuntimeError("BASE_PRODUCTION_LIMIT_NOT_4")

    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real = CertificationRegistry(settings.certifications_dir)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)
    real_count_before = len(real.records())
    real_sha_before = _cert_sha(real)

    # Re-run the exact 5..8 live candidate regression, including 9 and bounds negatives.
    live_reg_path = work / "live_candidate_regression_v0821.json"
    live_reg = run_live_candidate_audit(root, live_reg_path)
    if live_reg.get("status") != "PASS":
        raise RuntimeError("LIVE_CANDIDATE_REGRESSION_NOT_PASS")

    # Re-run the original 2..4 production workflow into an isolated certification registry.
    iso = CertificationRegistry(work / "isolated_regression_certifications")
    core_reg = audit_rare_rigid_edit_workflow(
        reg, resolver, iso, settings,
        project_root=root, work=work / "core_2to4_regression",
    )
    if core_reg.get("status") != "PASS" or core_reg.get("multi_vertex_transaction_write_authorized") is not True:
        raise RuntimeError("CORE_2TO4_REGRESSION_NOT_PASS")

    # Prepare a fresh isolated workspace only to exercise the explicit cross-object fail-closed rule.
    cross_iso = CertificationRegistry(work / "cross_object_certifications")
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, cross_iso, settings,
        project_root=root, open_gui=False, reset=True,
        workspace_root=work / "cross_object_workspace", workspace_origin="V0820_PROMOTION_CROSS_OBJECT_NEGATIVE",
    )
    cross_blocked, cross_error = _cross_object_negative(pathlib.Path(manifest["prepared_source"]), pathlib.Path(manifest["skeleton"]))
    if not cross_blocked:
        raise RuntimeError(f"CROSS_OBJECT_NEGATIVE_NOT_BLOCKED:{cross_error}")

    writers_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_count_after = len(real.records())
    real_sha_after = _cert_sha(real)
    writer_unchanged = writers_before == writers_after == EXPECTED_WRITER_HASHES
    client_unchanged = source_sha_before == source_sha_after
    real_unchanged = real_count_before == real_count_after and real_sha_before == real_sha_after
    limits_restored = int(redit.MAX_TRANSACTION_VERTICES) == 4 and int(mv.MAX_TRANSACTION_VERTICES) == 4
    nine_blocked = live_reg.get("candidate_nine_vertex_blocked") is True and live_reg.get("candidate_nine_vertex_output_created") is False
    bounds_blocked = live_reg.get("candidate_bounds_negative_blocked") is True and live_reg.get("candidate_bounds_negative_output_created") is False

    complete = all([writer_unchanged, client_unchanged, real_unchanged, limits_restored, cross_blocked, nine_blocked, bounds_blocked])
    if not complete:
        raise RuntimeError("PROMOTION_REGRESSION_STATE_NOT_CLEAN")

    policy = {
        "format": POLICY_FORMAT,
        "status": "PASS",
        "release_version": RELEASE_VERSION,
        "logical": TARGET,
        "production_authorized": True,
        "production_max_vertices": PROBE_MAX,
        "single_object_only": True,
        "interior_only": True,
        "manual_artist_proof": True,
        "manual_report": str(manual_path),
        "manual_report_sha256": _sha256(manual_path),
        "manual_output_sha256": manual.get("output_sha256"),
        "writer_hashes": writers_after,
        "client_source_sha256": source_sha_after,
        "cross_object_blocked": cross_blocked,
        "nine_vertex_blocked": nine_blocked,
        "bounds_negative_blocked": bounds_blocked,
        "topology_authorized": False,
        "extent_authorized": False,
        "policy": {
            "writer_path": "exact V0.8.9 write_at_dragon_edit_workspace with process-local MAX_TRANSACTION_VERTICES=8 only after this policy validates",
            "certification": "5..8 production writes receive RARE_RIGID_ARTIST_GUARDED_LARGE_TRANSACTION_WRITE in the real append-only registry",
            "deferred": "cross-object, extent/bounds changes, topology and >8 vertices remain fail-closed",
        },
    }
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    staging = policy_path.with_suffix(policy_path.suffix + ".staging")
    staging.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staging.replace(policy_path)

    return {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE_VERSION,
        "logical": TARGET,
        "manual_artist_proof_pass": True,
        "prior_v0820_failure_understood": True,
        "prior_v0820_failure_error": prior_failed_promotion.get("error"),
        "manual_changed_vertices": 5,
        "prior_v0817_pass": True,
        "live_candidate_regression_pass": True,
        "live_candidate_counts": [5, 6, 7, 8],
        "core_2to4_regression_pass": True,
        "cross_object_blocked": cross_blocked,
        "cross_object_error": cross_error,
        "nine_vertex_blocked": nine_blocked,
        "bounds_negative_blocked": bounds_blocked,
        "writer_modules_modified": not writer_unchanged,
        "client_modified": not client_unchanged,
        "real_certification_registry_modified": not real_unchanged,
        "process_local_limits_restored_to_4": limits_restored,
        "production_policy_written": True,
        "production_policy": str(policy_path),
        "production_live_write_authorized": True,
        "production_max_vertices": PROBE_MAX,
        "production_scope": "2..8 changed multibone-boundary vertices in one at_dragon mesh object; interior only",
        "deferred": ["cross-object transactions", "extent/bounds changes", "topology", ">8 vertices"],
        "writer_hashes": writers_after,
        "client_source_sha256": source_sha_after,
        "real_certification_count_before": real_count_before,
        "real_certification_count_after": real_count_after,
        "real_certification_registry_sha256_before": real_sha_before,
        "real_certification_registry_sha256_after": real_sha_after,
        "next": "production writer is now policy-authorized for 5..8; next roadmap milestone is cross-object transaction research",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V0.8.21 corrected production promotion gate for at_dragon transactions up to 8 vertices")
    ap.add_argument("--root", required=True)
    ap.add_argument("--output", required=True)
    ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).expanduser().resolve()
    try:
        report = run(pathlib.Path(ns.root), out)
    except Exception as exc:
        report = {
            "format": FORMAT,
            "status": "FAIL",
            "release_version": RELEASE_VERSION,
            "error": f"{type(exc).__name__}:{exc}",
            "production_live_write_authorized": False,
            "production_max_vertices": 4,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") == "PASS":
        print("rare_rigid_large_production_promotion=PASS production_max=8 manual=true nine_blocked=true cross_object_blocked=true client_modified=false")
        return 0
    print("rare_rigid_large_production_promotion=FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
