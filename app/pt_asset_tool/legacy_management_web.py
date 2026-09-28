from __future__ import annotations

import json
import pathlib
from typing import Any

from .item_runtime_catalog import lookup_item_runtime
from .legacy_management_contracts import classify_item_code, legacy_management_summary, verify_management_root
from .legacy_apps.reverse_manifest import apps as reversed_management_apps

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


def _replacement_matrix(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Engineering/audit view derived from the single reverse manifest.

    The normal operator UI intentionally hides EXE names, but this endpoint is
    useful for provenance.  Keeping it manifest-derived prevents the stale
    status drift that previously labelled already-ported tools as evidence only.
    """
    tools = {str(x.get("name") or ""): x for x in summary.get("tools") or []}
    out: list[dict[str, Any]] = []
    for app in reversed_management_apps():
        note_parts = list(app.corrections)
        if app.remaining_gaps:
            note_parts.append("Gaps: " + " ".join(app.remaining_gaps))
        note = " ".join(note_parts) or "Python capability is tracked in the reverse manifest."
        for name in app.aliases:
            tool = tools.get(name, {})
            out.append({
                "tool": name,
                "app_id": app.app_id,
                "status": app.python_status,
                "reverse_status": app.reverse_status,
                "note": note,
                "confidence": tool.get("confidence"),
                "capabilities": list(app.capabilities),
                "python_replacement": app.python_replacement,
            })
    return out


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
        "replacement_matrix": _replacement_matrix(summary),
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


def _text_accountins(row: Any, query: str) -> bool:
    if not query:
        return True
    try:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True).casefold()
    except Exception:
        text = str(row).casefold()
    return query.casefold() in text



def _review_reason(code: str, title: str, detail: str) -> dict[str, str]:
    return {"code": code, "title": title, "detail": detail}


def _review_action(kind: str, label: str, **payload: Any) -> dict[str, Any]:
    return {"kind": kind, "label": label, **payload}


def _decorate_item_review(row: dict[str, Any]) -> None:
    reasons: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = []
    for closure in row.get("closures") or []:
        icon = (closure.get("inventory_icon") or {}).get("status")
        drop = (closure.get("drop_model_ase") or {}).get("status")
        if icon != "PRESENT":
            reasons.append(_review_reason(
                "INVENTORY_ICON_NOT_PRESENT",
                "Inventory icon was not resolved in the client",
                "The path computed by the runtime contract did not resolve to an existing file. Review ItemFilePath/DorpItem and the physical client asset.",
            ))
        if drop != "PRESENT":
            reasons.append(_review_reason(
                "DROP_MODEL_NOT_PRESENT",
                "Drop visual model was not resolved in the client",
                "The expected ASE under Items/DropItem was not found. This is visual closure; it does not mean the item cannot exist in OpenItem.",
            ))
    if row.get("status") == "RUNTIME_CATALOG_MISSING":
        reasons.append(_review_reason(
            "RUNTIME_CATALOG_MISSING",
            "Code does not exist in the source-verified runtime catalog",
            "Do not create an OpenItem for this code until a proven sITEM contract exists. Registration of a new runtime code remains outside the promoted writer.",
        ))
    if row.get("authoring_ready"):
        actions.append(_review_action("AUTHORING", "Open item definition", authoring_kind="ITEM", path=row.get("authoring_path")))
    actions.append(_review_action("ITEM_LOOKUP", "Inspect runtime contract", code=row.get("code")))
    row["review_required"] = row.get("status") != "CLOSED"
    row["review_reasons"] = reasons
    row["review_actions"] = actions
    row["review_summary"] = (
        "Visual closure complete." if not row["review_required"]
        else "Review the visual dependencies below; REVIEW status alone does not prove the item is invalid."
    )


def _decorate_map_review(row: dict[str, Any]) -> None:
    actors = row.get("actors") or []
    unresolved = [x for x in actors if str((x or {}).get("status")) == "UNRESOLVED"]
    ambiguous = [x for x in actors if str((x or {}).get("status")) == "AMBIGUOUS"]
    reasons: list[dict[str, str]] = []
    if unresolved:
        names = ", ".join(str(x.get("name") or "?") for x in unresolved[:8])
        reasons.append(_review_reason(
            "SPM_ACTOR_UNRESOLVED",
            "SPM actor did not resolve to a Monster definition",
            f"No unique definition for: {names}. Fix the name in SPM or create/fix the monster definition.",
        ))
    if ambiguous:
        names = ", ".join(str(x.get("name") or "?") for x in ambiguous[:8])
        reasons.append(_review_reason(
            "SPM_ACTOR_AMBIGUOUS",
            "SPM actor matches more than one definition",
            f"Ambiguous match for: {names}. Choose/fix the definition before trusting drop closure.",
        ))
    row["review_required"] = bool(reasons)
    row["review_reasons"] = reasons
    row["review_actions"] = [
        _review_action("AUTHORING", "Edit SPM", authoring_kind="SPM", path=row.get("authoring_path"))
    ] if row.get("authoring_ready") else []
    row["review_summary"] = "Map resolved." if not reasons else "Map closure is incomplete; follow the actions below."


def _decorate_definition_review(row: dict[str, Any]) -> None:
    kind = str(row.get("kind") or "").upper()
    reasons: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = []
    if row.get("error"):
        reasons.append(_review_reason(
            "READ_OR_DECODE_ERROR",
            "The definition could not be read correctly",
            str(row.get("error")),
        ))
    for code in row.get("reasons") or []:
        if code == "READ_OR_DECODE_ERROR":
            continue
        reasons.append(_review_reason(str(code), "The audit marked this definition for review", str(code)))
    missing_refs = [x for x in row.get("item_references") or [] if not bool((x or {}).get("openitem_definition_present"))]
    if missing_refs:
        codes = [str((x or {}).get("code") or "?") for x in missing_refs]
        reasons.append(_review_reason(
            "ITEM_REFERENCE_WITHOUT_OPENITEM",
            "There are item references without a matching OpenItem definition",
            "Codes: " + ", ".join(codes[:20]) + (" …" if len(codes) > 20 else "") + ". Look up each code and create/fix the definition only if the runtime code is source-verified.",
        ))
        for code in codes[:8]:
            actions.append(_review_action("ITEM_LOOKUP", f"Review item {code}", code=code))
    if row.get("authoring_ready"):
        actions.insert(0, _review_action(
            "AUTHORING",
            "Edit monster" if kind == "MONSTER" else "Edit NPC",
            authoring_kind=kind,
            path=row.get("authoring_path"),
        ))
    row["review_required"] = bool(reasons)
    row["review_reasons"] = reasons
    row["review_actions"] = actions
    row["review_summary"] = "Definition with no blockers detected by closure." if not reasons else "REVIEW means there is a concrete pending issue; see the reason and action below."
    row["item_reference_note"] = (
        "This count is a broad scan of item codes in the file; 0 does NOT automatically mean 'no drop'. "
        "For MONSTER, use 'Drops item' when available because it specifically inspects FallItem/ExtraFallItem."
    )
    if kind == "MONSTER":
        if row.get("drop_item_reference_count") is None:
            row["drop_note"] = "Old report: audit again to separate explicit drops from other item references."
        elif int(row.get("drop_item_reference_count") or 0) == 0:
            row["drop_note"] = (
                "No item code was detected in FallItem/ExtraFallItem directives. This does not prove 'no drop': "
                "money directives or mechanisms still outside this contract may exist."
            )
        else:
            row["drop_note"] = "Codes detected specifically in FallItem/ExtraFallItem."
    row["zhoon_note"] = (
        ".zhoon is a historical companion/visual reference for the monster; it is not a drop table and must not be interpreted as an item."
    )


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
            _decorate_item_review(row)
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
            _decorate_map_review(row)
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
            _decorate_definition_review(row)
            rows.append(row)
    else:
        raise ValueError("LEGACY_REPORT_SECTION_INVALID")
    wanted_status = str(status or "").strip().casefold()
    filtered = []
    for row in rows:
        if wanted_status and str((row or {}).get("status") or "").casefold() != wanted_status:
            continue
        if not _text_accountins(row, str(query or "")):
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
