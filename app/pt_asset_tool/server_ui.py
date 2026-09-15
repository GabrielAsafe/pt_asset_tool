from __future__ import annotations

import json
import pathlib
from typing import Any

from .server_lifecycle import (
    ASSET_MAP_METADATA,
    ASSET_MAP_METADATA_REVIEW,
    ASSET_SHARED_3D,
    ASSET_SHARED_VISUAL,
    ASSET_STATIC,
    CONFIG_REVIEW,
    LOG_FORENSICS_EXCLUDED,
    PERSISTENCE_BLOCKED,
    RUNTIME_INTEGRITY_BLOCKED,
    SECURITY_STATE_BLOCKED,
)

FORMAT = "PT_ASSET_SERVER_UI_SUMMARY_V1"

_REPORTS = {
    "environment": "devtest/server_environment_auto/result.json",
    "inventory": "devtest/server_inventory/result.json",
    "entities": "devtest/server_bundle_census/result.json",
    "fields": "devtest/server_field_census/result.json",
    "items": "devtest/server_item_census/result.json",
    "design": "devtest/server_design_auto/result.json",
    "integration": "devtest/integration_regression_auto/result.json",
    "release1": "devtest/release_1_auto/result.json",
    "vendor_plan": "enrichment_vendor/migration_plan.result.json",
    "vendor_graph": "enrichment_vendor/dependency_graph.result.json",
}


def _read_report(project_root: pathlib.Path, rel: str) -> dict[str, Any] | None:
    path = project_root / "pt_build" / pathlib.PurePosixPath(rel)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data = dict(data)
    data["_mtime"] = path.stat().st_mtime
    data["_path"] = str(path)
    return data


def _summaries(project_root: pathlib.Path) -> dict[str, Any]:
    reports = {name: _read_report(project_root, rel) for name, rel in _REPORTS.items()}
    inventory = reports.get("inventory") or {}
    entities = reports.get("entities") or {}
    fields = reports.get("fields") or {}
    items = reports.get("items") or {}
    design = reports.get("design") or {}
    environment = reports.get("environment") or {}
    integration = reports.get("integration") or {}
    release1 = reports.get("release1") or {}
    vendor_plan = reports.get("vendor_plan") or {}
    vendor_graph = reports.get("vendor_graph") or {}
    return {
        "environment": {
            "status": environment.get("status"),
            "server_environment_ready": environment.get("server_environment_ready"),
            "shared_sample_count": len(environment.get("client_server_shared_samples") or []),
            "mtime": environment.get("_mtime"),
            "report": environment.get("_path"),
        } if environment else None,
        "inventory": {
            "status": inventory.get("status"),
            "total_files": inventory.get("total_files"),
            "total_bytes": inventory.get("total_bytes"),
            "asset_candidate_files": inventory.get("asset_candidate_files"),
            "design_visible_files": inventory.get("design_visible_files"),
            "hard_excluded_files": inventory.get("hard_excluded_files"),
            "lifecycle_counts": inventory.get("lifecycle_counts") or {},
            "layout_counts": inventory.get("layout_counts") or {},
            "mtime": inventory.get("_mtime"),
            "report": inventory.get("_path"),
        } if inventory else None,
        "entities": {
            "status": entities.get("status"),
            "definition_count": entities.get("definition_count"),
            "resolved_visual_entry_count": entities.get("resolved_visual_entry_count"),
            "unresolved_count": entities.get("unresolved_count"),
            "status_counts": entities.get("status_counts") or {},
            "reason_counts": entities.get("reason_counts") or {},
            "mtime": entities.get("_mtime"),
            "report": entities.get("_path"),
        } if entities else None,
        "fields": {
            "status": fields.get("status"),
            "field_bundle_count": fields.get("field_bundle_count"),
            "resolved_count": fields.get("resolved_count"),
            "unresolved_count": fields.get("unresolved_count"),
            "status_counts": fields.get("status_counts") or {},
            "mtime": fields.get("_mtime"),
            "report": fields.get("_path"),
        } if fields else None,
        "items": {
            "status": items.get("status"),
            "item_definition_count": items.get("item_definition_count"),
            "identity_parsed_count": items.get("identity_parsed_count"),
            "review_count": items.get("review_count"),
            "duplicate_code_count": items.get("duplicate_code_count"),
            "reason_counts": items.get("reason_counts") or {},
            "mtime": items.get("_mtime"),
            "report": items.get("_path"),
        } if items else None,
        "design": {
            "status": design.get("status"),
            "server_design_catalog_ready": design.get("server_design_catalog_ready"),
            "bundle_closure_complete": design.get("bundle_closure_complete"),
            "unresolved_or_review_count": design.get("unresolved_or_review_count"),
            "mtime": design.get("_mtime"),
            "report": design.get("_path"),
        } if design else None,
        "integration": {
            "status": integration.get("status"),
            "integration_regression_ready": integration.get("integration_regression_ready"),
            "required_failures": integration.get("required_failures") or [],
            "next_gate": integration.get("next_gate"),
            "mtime": integration.get("_mtime"),
            "report": integration.get("_path"),
        } if integration else None,
        "release1": {
            "status": release1.get("status"),
            "automatic_gate_status": release1.get("automatic_gate_status"),
            "manual_review_required_now": release1.get("manual_review_required_now"),
            "external_input_required": release1.get("external_input_required"),
            "runtime_game_acceptance_pending": release1.get("runtime_game_acceptance_pending"),
            "production_authorized": release1.get("production_authorized"),
            "server_design_status": (release1.get("server_design") or {}).get("status"),
            "blocker_count": len(release1.get("blockers") or []),
            "mtime": release1.get("_mtime"),
            "report": release1.get("_path"),
        } if release1 else None,
        "vendor_plan": {
            "status": vendor_plan.get("status"),
            "available_donor_count": vendor_plan.get("available_donor_count"),
            "unavailable_donor_count": vendor_plan.get("unavailable_donor_count"),
            "manifest": vendor_plan.get("manifest"),
            "summary_data": vendor_plan.get("summary_data") or {},
            "mtime": vendor_plan.get("_mtime"),
            "report": vendor_plan.get("_path"),
        } if vendor_plan else None,
        "vendor_graph": {
            "status": vendor_graph.get("status"),
            "available_donor_count": vendor_graph.get("available_donor_count"),
            "unavailable_donor_count": vendor_graph.get("unavailable_donor_count"),
            "graph_dir": vendor_graph.get("graph_dir"),
            "summary_data": vendor_graph.get("summary_data") or {},
            "mtime": vendor_graph.get("_mtime"),
            "report": vendor_graph.get("_path"),
        } if vendor_graph else None,
    }



def server_report_rows(
    project_root: pathlib.Path,
    kind: str,
    *,
    query: str = "",
    status: str = "",
    reason: str = "",
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    """Return a filtered, read-only view of one Asset Enrichment report.

    This keeps the browser on the same backend authority as the CLI reports;
    it does not rescan the server and it never exposes an authoring operation.
    """
    key = str(kind or "").strip().lower()
    if key not in {"entities", "fields", "items"}:
        raise ValueError(f"unsupported server report kind: {kind}")
    data = _read_report(pathlib.Path(project_root).resolve(), _REPORTS[key])
    if not data:
        return {
            "format": "PT_ASSET_SERVER_UI_REPORT_ROWS_V1",
            "status": "NO_REPORT",
            "kind": key,
            "total_rows": 0,
            "filtered_rows": 0,
            "offset": 0,
            "limit": max(1, min(int(limit or 200), 500)),
            "rows": [],
        }
    rows = list(data.get("rows") or [])
    q = str(query or "").strip().casefold()
    wanted_status = str(status or "").strip().casefold()
    wanted_reason = str(reason or "").strip().casefold()

    def haystack(row: dict[str, Any]) -> str:
        parts: list[str] = []
        for field in (
            "kind", "definition", "basename", "code", "status", "model_reference",
            "logical_inx", "selected_stage", "stage_selection_basis", "encoding",
        ):
            value = row.get(field)
            if value is not None:
                parts.append(str(value))
        parts.extend(str(x) for x in (row.get("reasons") or []))
        return "\n".join(parts).casefold()

    filtered: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        if wanted_status and str(row.get("status") or "").casefold() != wanted_status:
            continue
        reasons = [str(x) for x in (row.get("reasons") or [])]
        if wanted_reason and not any(wanted_reason in x.casefold() for x in reasons):
            continue
        if q and q not in haystack(row):
            continue
        filtered.append(row)

    start = max(0, int(offset or 0))
    page_limit = max(1, min(int(limit or 200), 500))
    return {
        "format": "PT_ASSET_SERVER_UI_REPORT_ROWS_V1",
        "status": "PASS",
        "kind": key,
        "source_status": data.get("status"),
        "total_rows": len(rows),
        "filtered_rows": len(filtered),
        "offset": start,
        "limit": page_limit,
        "rows": filtered[start:start + page_limit],
        "status_counts": data.get("status_counts") or {},
        "reason_counts": data.get("reason_counts") or {},
        "report": data.get("_path"),
        "server_write_authorized": False,
        "client_write_authorized": False,
    }

def build_server_ui_summary(project_root: pathlib.Path, server_root: pathlib.Path | None, client_root: pathlib.Path) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    client = pathlib.Path(client_root).resolve()
    vendor_base = project_root.parent / "vendor"
    vendor_manifest = next((vendor_base / name / "PACKAGE_MANIFEST.json" for name in ("summit_asset_enrichment_v9", "summit_asset_enrichment_v6") if (vendor_base / name / "PACKAGE_MANIFEST.json").is_file()), vendor_base / "summit_asset_enrichment_v9" / "PACKAGE_MANIFEST.json")
    vendor_info: dict[str, Any] = {"present": False, "version": None, "path": None, "file_count": 0}
    if vendor_manifest.is_file():
        try:
            manifest = json.loads(vendor_manifest.read_text(encoding="utf-8"))
            vendor_info = {
                "present": True,
                "version": manifest.get("version"),
                "path": str(vendor_manifest.parent),
                "file_count": len(manifest.get("files") or []),
                "writes_exposed_in_ui": False,
            }
        except Exception:
            vendor_info = {"present": True, "version": "UNKNOWN", "path": str(vendor_manifest.parent), "file_count": 0, "writes_exposed_in_ui": False}
    return {
        "format": FORMAT,
        "status": "READY" if server and server.is_dir() else "UNCONFIGURED",
        "server_root": str(server) if server else None,
        "server_root_exists": bool(server and server.is_dir()),
        "client_root": str(client),
        "asset_enrichment_tool": vendor_info,
        "reports": _summaries(project_root),
        "lifecycle_policy": [
            {"lifecycle": ASSET_STATIC, "ui": "Asset estático", "policy": "bundle validation before authoring"},
            {"lifecycle": ASSET_MAP_METADATA, "ui": "Metadata de field", "policy": "layout validation"},
            {"lifecycle": ASSET_MAP_METADATA_REVIEW, "ui": "Metadata de field em review", "policy": "typed clone only"},
            {"lifecycle": ASSET_SHARED_3D, "ui": "3D compartilhado", "policy": "PT Asset pipeline; server copy read-only"},
            {"lifecycle": ASSET_SHARED_VISUAL, "ui": "Visual compartilhado", "policy": "reference required"},
            {"lifecycle": CONFIG_REVIEW, "ui": "Configuração operacional", "policy": "review only"},
            {"lifecycle": PERSISTENCE_BLOCKED, "ui": "Persistência", "policy": "blocked from asset graph"},
            {"lifecycle": SECURITY_STATE_BLOCKED, "ui": "Estado/segurança", "policy": "blocked from asset graph"},
            {"lifecycle": RUNTIME_INTEGRITY_BLOCKED, "ui": "Integridade de runtime", "policy": "blocked from asset graph"},
            {"lifecycle": LOG_FORENSICS_EXCLUDED, "ui": "Logs/forensics", "policy": "excluded from authoring"},
        ],
        "bundle_model": [
            "Monster: INF → ZHOON → INI lógico/INX → SMD/SMB/texturas + drops + spawn",
            "NPC: NPC → ZHOON → model package + SPC/event/quest/shop quando aplicável",
            "Field: stage SMD/ASE → SPP/SPC/SPM → entidades referenciadas",
            "Item: OpenItem/ZHOON → server code map → client catalog/model/icon",
        ],
        "safety": {
            "server_source_write": False,
            "persistence_write": False,
            "client_source_write": False,
            "outputs_only_under_pt_build": True,
        },
    }
