from __future__ import annotations

import csv
import json
import pathlib
from collections import Counter
from typing import Any

FORMAT = "PT_ASSET_COOKED_TEXTURE_EVIDENCE_V1"


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _entry_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("entries")
    if not isinstance(rows, list):
        return []
    return [dict(x) for x in rows if isinstance(x, dict)]


def audit_cooked_texture_evidence(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    *,
    manifest_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """Import Summit DDS cooker evidence without promoting it to runtime need.

    V1 cooker manifests remain readable. V2 adds persistent failure rows. The
    audit is evidence-only: a failed cook never makes an asset removable and a
    successful cook never makes the original source disposable.
    """
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    manifest = pathlib.Path(manifest_path).resolve() if manifest_path else client / "cooked" / "manifest.json"
    failed_path = client / "cooked" / "failed.json"
    out_dir = project / "pt_build" / "cooked_texture_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = _load_json(manifest)
    failed_raw = _load_json(failed_path)
    rows = _entry_rows(raw)
    if not rows and isinstance(failed_raw.get("entries"), list):
        rows = [dict(x) for x in failed_raw.get("entries") if isinstance(x, dict)]

    normalized: list[dict[str, Any]] = []
    for row in rows:
        source = _norm(row.get("source") or "")
        if not source:
            continue
        cooked = _norm(row.get("cooked") or "")
        status = str(row.get("status") or "unknown").casefold()
        source_path = client / source
        cooked_path = (client / "cooked" / cooked) if cooked else None
        normalized.append({
            "source": source,
            "canonical_source": source.casefold(),
            "cooked": cooked,
            "status": status,
            "source_exists": source_path.is_file(),
            "cooked_exists": bool(cooked_path and cooked_path.is_file()),
            "extension": str(row.get("extension") or pathlib.PurePosixPath(source).suffix.casefold()),
            "format": row.get("format") or "",
            "width": row.get("width") or "",
            "height": row.get("height") or "",
            "failure_stage": row.get("failure_stage") or "",
            "failure_class": row.get("failure_class") or "",
            "error_type": row.get("error_type") or "",
            "error_message": row.get("error_message") or "",
            "source_bytes": row.get("source_bytes") or "",
            "source_mtime_ns": row.get("source_mtime_ns") or "",
            "source_sha256": row.get("source_sha256") or "",
            "source_header_hex": row.get("source_header_hex") or "",
            "skip_reason": row.get("skip_reason") or "",
            "skip_class": row.get("skip_class") or "",
            "legacy_decode_mode": row.get("legacy_decode_mode") or "",
            "decoded_width": row.get("decoded_width") or "",
            "decoded_height": row.get("decoded_height") or "",
            "asset_integrity_state": row.get("asset_integrity_state") or "",
            "documented_outlier": bool(row.get("documented_outlier")),
            "asset_classification": row.get("asset_classification") or "",
            "cook_policy": row.get("cook_policy") or "",
            "runtime_note": row.get("runtime_note") or "",
            "outlier_reason": row.get("outlier_reason") or "",
            "retention_decision_required": bool(row.get("retention_decision_required")),
            "deletion_authorized": False,
        })

    normalized.sort(key=lambda x: x["canonical_source"])
    statuses = Counter(str(x["status"]) for x in normalized)
    failures = [x for x in normalized if x["status"] == "error"]
    failure_classes = Counter(str(x.get("failure_class") or "UNCLASSIFIED_FAILURE") for x in failures)
    failure_stages = Counter(str(x.get("failure_stage") or "unknown") for x in failures)
    failure_roots = Counter((x["source"].split("/", 1)[0] if "/" in x["source"] else x["source"]) for x in failures)
    failure_exts = Counter(str(x.get("extension") or "<none>") for x in failures)
    skips = [x for x in normalized if x["status"] == "skipped"]
    skip_classes = Counter(str(x.get("skip_class") or "UNCLASSIFIED_SKIP") for x in skips)
    integrity_states = Counter(str(x.get("asset_integrity_state") or "UNSPECIFIED") for x in normalized)
    documented_outlier_failures = [x for x in failures if bool(x.get("documented_outlier"))]

    tsv = out_dir / "entries.tsv"
    columns = [
        "source", "status", "source_exists", "cooked", "cooked_exists", "extension", "format",
        "width", "height", "failure_stage", "failure_class", "error_type", "error_message",
        "source_bytes", "source_mtime_ns", "source_sha256", "source_header_hex", "skip_reason",
        "skip_class", "legacy_decode_mode", "decoded_width", "decoded_height", "asset_integrity_state",
        "documented_outlier", "asset_classification", "cook_policy", "runtime_note", "outlier_reason",
        "retention_decision_required", "deletion_authorized",
    ]
    with tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        w.writeheader(); w.writerows(normalized)

    result = {
        "format": FORMAT,
        "status": "PASS",
        "state": "REVIEW_REQUIRED" if failures else ("READY" if normalized else "NOT_PRESENT"),
        "client_root": str(client),
        "manifest": str(manifest),
        "manifest_present": manifest.is_file(),
        "manifest_format": raw.get("format") or ("LEGACY_V1" if raw else "NOT_PRESENT"),
        "manifest_version": raw.get("version"),
        "failed_manifest": str(failed_path),
        "failed_manifest_present": failed_path.is_file(),
        "entry_count": len(normalized),
        "status_counts": dict(sorted(statuses.items())),
        "failure_count": len(failures),
        "failure_class_counts": dict(sorted(failure_classes.items())),
        "failure_stage_counts": dict(sorted(failure_stages.items())),
        "failure_root_counts": dict(sorted(failure_roots.items())),
        "failure_extension_counts": dict(sorted(failure_exts.items())),
        "documented_outlier_failure_count": len(documented_outlier_failures),
        "skip_count": len(skips),
        "skip_class_counts": dict(sorted(skip_classes.items())),
        "asset_integrity_state_counts": dict(sorted(integrity_states.items())),
        "entries_tsv": str(tsv),
        "policy": {
            "cooker_manifest_is_build_evidence_not_runtime_need": True,
            "failed_cook_does_not_make_source_removable": True,
            "successful_cook_does_not_make_source_removable": True,
            "source_assets_remain_authoritative_fallback": True,
            "client_write_authorized": False,
            "production_authorized": False,
            "documented_outlier_is_integrity_evidence_not_retention_authority": True,
            "skipped_after_successful_decode_is_not_a_failure": True,
            "deletion_authorized": False,
        },
        "failures": failures,
    }
    report = out_dir / "result.json"
    result["report"] = str(report)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def cooked_index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tsv = pathlib.Path(str(report.get("entries_tsv") or ""))
    if tsv.is_file():
        with tsv.open("r", encoding="utf-8", newline="") as f:
            rows = [dict(x) for x in csv.DictReader(f, delimiter="\t")]
    return {str(x.get("source") or "").casefold(): x for x in rows if x.get("source")}
