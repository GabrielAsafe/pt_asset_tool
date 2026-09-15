from __future__ import annotations

"""Focused client+server integration regression gate.

This gate intentionally excludes the already-green material/rigid/static breadth
from ``physical-regression-auto``.  It exists to validate the fixes discovered
by the 2026-09-04 physical run: non-TRS animation persistence, structural SMB
outliers, the protected crow2 TGA variant, and the server bundle parser.
"""

import json
import pathlib
from typing import Any, Callable

from .affine_animation_selftest import run_affine_animation_selftest
from .animation_pose_devtest import (
    choose_animation_pose_physical_representatives,
    run_animation_pose_automated_devtest_batch,
)
from .environment_validation import run_environment_validation
from .server_bundle_census import audit_server_entity_bundles
from .server_environment_validation import run_server_environment_validation
from .server_field_census import audit_server_field_bundles
from .server_item_census import audit_server_item_bundles
from .standalone_animation_devtest import (
    audit_smb_animation_corpus,
    choose_standalone_animation_representatives,
    run_standalone_animation_pose_devtest_batch,
)
from .texture_codec_devtest import (
    audit_proprietary_texture_codecs,
    audit_proprietary_texture_exact_regressions,
)
from .writer_corpus_audit import audit_smb_writer_corpus, audit_smb_writer_edit_corpus

FORMAT = "PT_ASSET_INTEGRATION_REGRESSION_AUTO_V1"
KNOWN_SMB_OUTLIERS = (
    "char/monster/Darkmage/skullma_A.smb",
    "Effect/PcBangPet/Pet_Phoenimin/Phoenix.smb",
)
KNOWN_TEXTURE_OUTLIERS = ("weapons/crow2.tga",)


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("asset") or "").replace("\\", "/").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _compact_failure_detail(name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Keep actionable failure evidence small enough to survive terminal scrollback."""
    out: dict[str, Any] = {"gate": name, "status": str(row.get("status") or "UNKNOWN")}
    for key in ("error", "failure"):
        value = row.get(key)
        if value:
            out[key] = str(value)[:1800]
    sample = row.get("failure_sample")
    if isinstance(sample, list) and sample:
        out["failure_sample"] = sample[:3]
    failed_assets = row.get("failed_assets")
    if isinstance(failed_assets, list) and failed_assets:
        rows = []
        for item in failed_assets[:3]:
            if not isinstance(item, dict):
                continue
            rows.append({
                key: item.get(key)
                for key in ("asset", "domain", "model_info_inx", "error", "pose_diagnostic")
                if item.get(key) is not None
            })
        if rows:
            out["failed_assets"] = rows
    build = row.get("build")
    if isinstance(build, dict) and build.get("status") != "PASS":
        out["build"] = {
            key: build.get(key)
            for key in ("status", "live_max_abs_matrix_error", "live_failures", "max_factor_reconstruction_error", "target_contract")
            if build.get(key) is not None
        }
    reopen = row.get("reopen_check")
    if isinstance(reopen, dict) and reopen.get("status") != "PASS":
        out["reopen_check"] = {
            key: reopen.get(key)
            for key in ("status", "max_abs_matrix_error", "failures")
            if reopen.get(key) is not None
        }
    report = row.get("report")
    if report:
        out["report"] = report
    return out


def run_integration_regression_auto(
    settings,
    registry,
    resolver,
    certifications,
    *,
    fps: int = 30,
    environment_blender_timeout_seconds: float = 60.0,
    affine_blender_timeout_seconds: float = 90.0,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(settings.project_root).resolve()
    server_root = getattr(settings, "server_root", None)
    report_dir = root / "pt_build" / "devtest" / "integration_regression_auto"
    report_path = report_dir / "result.json"

    def emit(message: str) -> None:
        if progress:
            progress(message)

    def run(label: str, fn):
        emit(f"START {label}")
        try:
            row = fn()
        except Exception as exc:
            row = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        emit(f"DONE  {label} status={row.get('status') if isinstance(row, dict) else 'UNKNOWN'}")
        return row

    emit(f"BEGIN client_root={settings.client_root} server_root={server_root}")
    gates: dict[str, Any] = {}
    gates["client_environment"] = run(
        "client_environment",
        lambda: run_environment_validation(
            settings, registry, resolver,
            blender_timeout_seconds=float(environment_blender_timeout_seconds),
        ),
    )
    gates["server_environment"] = run(
        "server_environment",
        lambda: run_server_environment_validation(settings, server_root=server_root),
    )
    if gates["client_environment"].get("status") != "PASS" or gates["server_environment"].get("status") != "PASS":
        required = [name for name in ("client_environment", "server_environment") if gates[name].get("status") != "PASS"]
        failure_summary = {name: _compact_failure_detail(name, gates[name]) for name in required}
        failure_summary_path = report_dir / "failure_summary.json"
        result = {
            "format": FORMAT,
            "status": "FAIL",
            "integration_regression_ready": False,
            "required_failures": required,
            "failure_summary": failure_summary,
            "failure_summary_report": str(failure_summary_path),
            "gates": gates,
            "next_gate": "FIX_ENVIRONMENT",
            "production_authorized": False,
            "client_write_authorized": False,
            "server_write_authorized": False,
            "client_modified": bool(gates["client_environment"].get("client_modified")),
            "server_modified": bool(gates["server_environment"].get("server_modified")),
            "report": str(report_path),
        }
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        failure_summary_path.write_text(json.dumps({
            "format": "PT_ASSET_INTEGRATION_FAILURE_SUMMARY_V1",
            "status": "FAIL",
            "required_failures": required,
            "failures": failure_summary,
            "result_report": str(report_path),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name in required:
            compact = json.dumps(failure_summary[name], ensure_ascii=False, separators=(",", ":"))
            emit(f"FAILURE {name} {compact[:2200]}")
        emit(f"REPORT result={report_path} failure_summary={failure_summary_path}")
        emit(f"END status=FAIL failures={len(required)}")
        return result

    # Fast synthetic Blender proof first.  If this fails, the expensive physical
    # animation witnesses are still useful diagnostics, but cannot be promoted.
    gates["affine_animation_selftest"] = run(
        "affine_animation_selftest",
        lambda: run_affine_animation_selftest(settings, timeout_seconds=float(affine_blender_timeout_seconds)),
    )

    animation_rows: list[dict[str, Any]] = []
    for domain in ("PLAYER", "NPC", "MONSTER"):
        rows = choose_animation_pose_physical_representatives(registry, resolver, domain, limit=1)
        animation_rows.extend(rows)
    animation_rows = _dedupe(animation_rows)
    gates["bound_animation_pose"] = run(
        "bound_animation_pose",
        lambda: run_animation_pose_automated_devtest_batch(
            settings, registry, resolver, certifications, animation_rows, fps=int(fps)
        ),
    ) if animation_rows else {"status": "EMPTY", "requested": 0}

    standalone_rows: list[dict[str, Any]] = []
    for rows in choose_standalone_animation_representatives(registry, resolver, per_domain=1).values():
        standalone_rows.extend(rows)
    standalone_rows = _dedupe(standalone_rows)
    gates["standalone_animation_pose"] = run(
        "standalone_animation_pose",
        lambda: run_standalone_animation_pose_devtest_batch(
            settings, registry, resolver, certifications, standalone_rows, fps=int(fps)
        ),
    ) if standalone_rows else {"status": "EMPTY", "requested": 0}

    gates["smb_animation_corpus"] = run(
        "smb_animation_corpus",
        lambda: audit_smb_animation_corpus(registry, resolver, sample_limit=100),
    )

    gates["smb_outlier_noop"] = run(
        "smb_outlier_noop",
        lambda: audit_smb_writer_corpus(
            root, settings.client_root, logical_paths=KNOWN_SMB_OUTLIERS, sample_limit=20
        ),
    )
    gates["smb_outlier_edit"] = run(
        "smb_outlier_edit",
        lambda: audit_smb_writer_edit_corpus(
            root, settings.client_root, logical_paths=KNOWN_SMB_OUTLIERS, sample_limit=20
        ),
    )

    gates["texture_exact_outlier"] = run(
        "texture_exact_outlier",
        lambda: audit_proprietary_texture_exact_regressions(
            root, registry, resolver, KNOWN_TEXTURE_OUTLIERS
        ),
    )
    gates["texture_codec_representatives"] = run(
        "texture_codec_representatives",
        lambda: audit_proprietary_texture_codecs(root, registry, resolver, per_family=1),
    )

    # The server regression is parser/closure discovery only, not authoring.
    # Skip the 153k-file full inventory: server-environment already verifies
    # lifecycle separation and samples; these three censors target the fixed
    # path/identity/basename logic directly.
    server = pathlib.Path(server_root).expanduser().resolve() if server_root else None
    gates["server_entity_bundles"] = run(
        "server_entity_bundles",
        lambda: audit_server_entity_bundles(
            root, server, pathlib.Path(settings.client_root).resolve(),
            progress=lambda m: emit(m),
        ),
    ) if server else {"status": "FAIL", "error": "SERVER_ROOT_NOT_CONFIGURED"}
    gates["server_field_bundles"] = run(
        "server_field_bundles",
        lambda: audit_server_field_bundles(root, server, progress=lambda m: emit(m)),
    ) if server else {"status": "FAIL", "error": "SERVER_ROOT_NOT_CONFIGURED"}
    gates["server_item_bundles"] = run(
        "server_item_bundles",
        lambda: audit_server_item_bundles(root, server, progress=lambda m: emit(m)),
    ) if server else {"status": "FAIL", "error": "SERVER_ROOT_NOT_CONFIGURED"}

    server_regression = {
        "entity_definitions_detected": int(gates["server_entity_bundles"].get("definition_count") or 0) > 0,
        "item_definitions_detected": int(gates["server_item_bundles"].get("item_definition_count") or 0) > 0,
        "item_identities_parsed": int(gates["server_item_bundles"].get("identity_parsed_count") or 0) > 0,
        "field_bundles_detected": int(gates["server_field_bundles"].get("field_bundle_count") or 0) > 0,
        "field_stage_match_detected": any(bool(row.get("selected_stage")) for row in (gates["server_field_bundles"].get("rows") or [])),
    }
    server_regression["status"] = "PASS" if all(server_regression.values()) else "FAIL"
    gates["server_parser_regression"] = server_regression
    emit(f"DONE  server_parser_regression status={server_regression['status']}")

    required = [
        "client_environment",
        "server_environment",
        "affine_animation_selftest",
        "bound_animation_pose",
        "standalone_animation_pose",
        "smb_animation_corpus",
        "smb_outlier_noop",
        "smb_outlier_edit",
        "texture_exact_outlier",
        "texture_codec_representatives",
        "server_entity_bundles",
        "server_field_bundles",
        "server_item_bundles",
        "server_parser_regression",
    ]
    failures = [name for name in required if str((gates.get(name) or {}).get("status") or "") != "PASS"]
    client_modified = any(bool((row or {}).get("client_modified")) for row in gates.values() if isinstance(row, dict))
    server_modified = any(bool((row or {}).get("server_modified")) for row in gates.values() if isinstance(row, dict))
    if client_modified and "CLIENT_MODIFIED" not in failures:
        failures.append("CLIENT_MODIFIED")
    if server_modified and "SERVER_MODIFIED" not in failures:
        failures.append("SERVER_MODIFIED")

    failure_summary = {
        name: _compact_failure_detail(name, gates.get(name) or {})
        for name in failures
        if name in gates
    }
    failure_summary_path = report_dir / "failure_summary.json"

    result = {
        "format": FORMAT,
        "status": "PASS" if not failures else "FAIL",
        "integration_regression_ready": not failures,
        "required_failures": failures,
        "failure_summary": failure_summary,
        "failure_summary_report": str(failure_summary_path),
        "selection": {
            "bound_animation_assets": [r.get("asset") for r in animation_rows],
            "standalone_animation_assets": [r.get("asset") for r in standalone_rows],
            "known_smb_outliers": list(KNOWN_SMB_OUTLIERS),
            "known_texture_outliers": list(KNOWN_TEXTURE_OUTLIERS),
        },
        "gates": gates,
        "next_gate": "PHYSICAL_REGRESSION_AUTO" if not failures else "FIX_REPORTED_INTEGRATION_REGRESSIONS",
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
        "client_modified": client_modified,
        "server_modified": server_modified,
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failure_summary_path.write_text(json.dumps({
        "format": "PT_ASSET_INTEGRATION_FAILURE_SUMMARY_V1",
        "status": result["status"],
        "required_failures": failures,
        "failures": failure_summary,
        "result_report": str(report_path),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in failures:
        detail = failure_summary.get(name) or {"gate": name}
        compact = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
        emit(f"FAILURE {name} {compact[:2200]}")
    emit(f"REPORT result={report_path} failure_summary={failure_summary_path}")
    emit(f"END status={result['status']} failures={len(failures)}")
    return result
