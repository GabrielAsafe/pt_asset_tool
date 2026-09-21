from __future__ import annotations

import json
import pathlib
from typing import Any

from .item_runtime_catalog import lookup_item_runtime
from .legacy_management_contracts import classify_item_code, legacy_management_summary, verify_management_root

FORMAT = "PT_LEGACY_MANAGEMENT_WEB_V1"
_REPORT_REL = pathlib.Path("pt_build/devtest/legacy_management/result.json")


def _load_report(project_root: pathlib.Path) -> dict[str, Any] | None:
    path = pathlib.Path(project_root).resolve() / _REPORT_REL
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "INVALID_REPORT", "report": str(path)}
    if isinstance(data, dict):
        data = dict(data)
        data.setdefault("report", str(path))
        return data
    return {"status": "INVALID_REPORT", "report": str(path)}


def _load_json_report(project_root: pathlib.Path, relative: pathlib.Path) -> dict[str, Any] | None:
    path = pathlib.Path(project_root).resolve() / relative
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _item_authoring_definitions(project_root: pathlib.Path) -> dict[str, list[str]]:
    report = _load_json_report(project_root, pathlib.Path("pt_build/devtest/server_item_census/result.json"))
    out: dict[str, list[str]] = {}
    if not report:
        return out
    for row in report.get("rows") or []:
        code = str((row or {}).get("code") or "").strip().casefold()
        definition = str((row or {}).get("definition") or "").strip().replace("\\", "/")
        if not code or not definition:
            continue
        bucket = out.setdefault(code, [])
        if definition not in bucket:
            bucket.append(definition)
    return out


def _report_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    server = report.get("server_evidence") or {}
    visual = report.get("client_item_visual_evidence") or {}
    verification = report.get("management_verification") or {}
    tutorials = report.get("tutorial_evidence") or {}
    return {
        "status": report.get("status"),
        "report": report.get("report"),
        "server_root": report.get("server_root"),
        "client_root": report.get("client_root"),
        "management_match_count": verification.get("match_count"),
        "management_missing_count": verification.get("missing_count"),
        "management_mismatch_count": verification.get("mismatch_count"),
        "tutorial_unique_item_codes": tutorials.get("unique_item_codes"),
        "openitem_definition_count": (server.get("openitem") or {}).get("definition_count"),
        "monster_definition_count": server.get("monster_definition_count"),
        "npc_definition_count": server.get("npc_definition_count"),
        "field_spm_count": server.get("field_spm_count"),
        "unresolved_spm_actor_count": server.get("unresolved_spm_actor_count"),
        "item_reference_without_openitem_count": server.get("item_reference_without_openitem_count"),
        "client_item_closed_count": visual.get("closed_count"),
        "client_item_review_count": visual.get("review_count"),
        "write_authorized": False,
    }


def legacy_management_dashboard(project_root: pathlib.Path, *, client_root: pathlib.Path | None = None, server_root: pathlib.Path | None = None) -> dict[str, Any]:
    summary = legacy_management_summary()
    report = _load_report(project_root)
    return {
        "format": FORMAT,
        "status": "PASS",
        "client_root": str(pathlib.Path(client_root).resolve()) if client_root is not None else None,
        "server_root": str(pathlib.Path(server_root).resolve()) if server_root is not None else None,
        "legacy_contract": summary,
        "latest_audit": _report_summary(report),
        "capabilities": {
            "summary": True,
            "verify_management": True,
            "item_lookup": True,
            "audit_management": True,
            "world_closure": True,
            "runtime_item_writer_authorized": False,
            "legacy_exe_execution": False,
        },
    }


def _resolve_client_path(resolver, logical: str | None) -> dict[str, Any] | None:
    if not logical:
        return None
    try:
        physical = resolver.resolve(str(logical), required=False) if resolver is not None else None
        return {
            "logical_path": str(logical),
            "status": "PRESENT" if physical is not None else "MISSING",
            "physical_path": str(physical) if physical is not None else None,
        }
    except Exception as exc:
        return {
            "logical_path": str(logical),
            "status": "REVIEW",
            "physical_path": None,
            "error": f"{type(exc).__name__}:{exc}",
        }


def legacy_management_item_detail(code: str, *, resolver=None) -> dict[str, Any]:
    code = str(code or "").strip()
    classification = classify_item_code(code)
    runtime = lookup_item_runtime(code)
    physical: list[dict[str, Any]] = []
    for match in runtime.get("matches") or []:
        expected = match.get("expected_client_paths") or {}
        physical.append({
            "numeric_code_hex": match.get("numeric_code_hex"),
            "dorp_item": match.get("dorp_item"),
            "inventory_icon": _resolve_client_path(resolver, expected.get("inventory_icon")),
            "drop_model_ase": _resolve_client_path(resolver, expected.get("drop_model_ase")),
        })
    return {
        "format": "PT_LEGACY_MANAGEMENT_WEB_ITEM_V1",
        "status": "PASS" if classification.get("status") != "UNCLASSIFIED" or runtime.get("status") == "SOURCE_VERIFIED" else "REVIEW",
        "code": code,
        "legacy": classification,
        "runtime_item_contract": runtime,
        "physical_client_closure": physical,
        "writer_authorized": False,
    }


def verify_management_for_web(root: str | pathlib.Path) -> dict[str, Any]:
    return verify_management_root(pathlib.Path(root).expanduser())


def _text_contains(row: Any, query: str) -> bool:
    if not query:
        return True
    try:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True).casefold()
    except Exception:
        text = str(row).casefold()
    return query.casefold() in text


def query_legacy_management_report(
    project_root: pathlib.Path,
    *,
    section: str = "items",
    query: str = "",
    status: str = "",
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    report = _load_report(project_root)
    if not isinstance(report, dict) or report.get("status") == "INVALID_REPORT":
        return {
            "format": "PT_LEGACY_MANAGEMENT_WEB_REPORT_V1",
            "status": "NO_REPORT" if report is None else "INVALID_REPORT",
            "section": section,
            "rows": [],
            "total_rows": 0,
            "filtered_rows": 0,
            "offset": 0,
            "limit": int(limit),
            "report": report.get("report") if isinstance(report, dict) else None,
            "write_authorized": False,
        }
    server = report.get("server_evidence") or {}
    visual = report.get("client_item_visual_evidence") or {}
    section = str(section or "items").strip().lower()
    if section == "items":
        item_defs = _item_authoring_definitions(project_root)
        rows = []
        for raw in visual.get("rows") or []:
            row = dict(raw)
            paths = list(item_defs.get(str(row.get("code") or "").casefold(), []))
            row["authoring_kind"] = "ITEM"
            row["authoring_paths"] = paths
            row["authoring_path"] = paths[0] if len(paths) == 1 else None
            row["authoring_ready"] = len(paths) == 1
            row["authoring_reason"] = None if len(paths) == 1 else ("OPENITEM_DEFINITION_AMBIGUOUS" if len(paths) > 1 else "OPENITEM_DEFINITION_NOT_FOUND")
            rows.append(row)
    elif section == "maps":
        rows = []
        for raw in server.get("maps") or []:
            row = dict(raw)
            actor_states = {str((x or {}).get("status") or "") for x in row.get("actors") or []}
            row["status"] = "UNRESOLVED" if "UNRESOLVED" in actor_states else ("AMBIGUOUS" if "AMBIGUOUS" in actor_states else "RESOLVED")
            row["authoring_kind"] = "SPM"
            row["authoring_path"] = str(row.get("spm") or "") or None
            row["authoring_paths"] = [row["authoring_path"]] if row["authoring_path"] else []
            row["authoring_ready"] = bool(row["authoring_path"])
            row["authoring_reason"] = None if row["authoring_ready"] else "SPM_PATH_NOT_FOUND"
            rows.append(row)
    elif section == "definitions":
        rows = []
        for raw in server.get("definitions") or []:
            row = dict(raw)
            missing = any(not bool((x or {}).get("openitem_definition_present")) for x in row.get("item_references") or [])
            row["status"] = "REVIEW" if row.get("error") or row.get("reasons") or missing else "PASS"
            kind = str(row.get("kind") or "").upper()
            row["authoring_kind"] = kind if kind in {"MONSTER", "NPC"} else None
            row["authoring_path"] = str(row.get("definition") or "") or None
            row["authoring_paths"] = [row["authoring_path"]] if row["authoring_path"] else []
            row["authoring_ready"] = bool(row["authoring_kind"] and row["authoring_path"])
            row["authoring_reason"] = None if row["authoring_ready"] else "DEFINITION_NOT_AUTHORABLE"
            rows.append(row)
    else:
        raise ValueError("LEGACY_REPORT_SECTION_INVALID")
    wanted_status = str(status or "").strip().casefold()
    filtered = []
    for row in rows:
        if wanted_status and str((row or {}).get("status") or "").casefold() != wanted_status:
            continue
        if not _text_contains(row, str(query or "")):
            continue
        filtered.append(row)
    offset = max(0, int(offset or 0))
    limit = max(1, min(500, int(limit or 100)))
    return {
        "format": "PT_LEGACY_MANAGEMENT_WEB_REPORT_V1",
        "status": "PASS",
        "section": section,
        "rows": filtered[offset:offset + limit],
        "total_rows": len(rows),
        "filtered_rows": len(filtered),
        "offset": offset,
        "limit": limit,
        "report": report.get("report"),
        "summary": _report_summary(report),
        "write_authorized": False,
    }
