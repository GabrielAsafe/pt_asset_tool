from __future__ import annotations

import json
import pathlib
import shlex
from .runtime_paths import app_command

from typing import Any, Iterable

FORMAT = "PT_ASSET_GENERAL_CENSUS_READINESS_V1"


def _resolved_text(value: pathlib.Path | str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(pathlib.Path(value).expanduser().resolve())
    except Exception:
        return str(value)


def _root_check(key: str, label: str, value: pathlib.Path | str | None, *, required: bool = True) -> dict[str, Any]:
    text = _resolved_text(value)
    exists = bool(text and pathlib.Path(text).is_dir())
    return {
        "key": key,
        "label": label,
        "required": bool(required),
        "configured": bool(text),
        "exists": exists,
        "path": text,
        "status": "READY" if exists else ("MISSING" if required else "OPTIONAL"),
    }


def _donor_rows(values: Iterable[str], side: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in values:
        text = str(raw or "").strip()
        label = ""
        path_text = ""
        if "=" in text:
            label, path_text = text.split("=", 1)
        label = label.strip().upper()
        path = pathlib.Path(path_text.strip()).expanduser().resolve() if path_text.strip() else None
        exists = bool(path and path.is_dir())
        rows.append({
            "side": side,
            "raw": text,
            "label": label,
            "path": str(path) if path else None,
            "exists": exists,
            "status": "READY" if label and exists else "MISSING",
        })
    return rows


def _report(project_root: pathlib.Path) -> dict[str, Any] | None:
    path = project_root / "pt_build" / "general_asset_census" / "result.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "INVALID_REPORT", "report": str(path)}
    if not isinstance(data, dict):
        return {"status": "INVALID_REPORT", "report": str(path)}
    return data


def _normalized_donor_set(rows: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in rows:
        label = str(row.get("label") or "").strip().upper()
        path = _resolved_text(row.get("root") or row.get("path"))
        if label and path:
            out.add((label, path))
    return out


def _current_donor_set(rows: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in rows:
        label = str(row.get("label") or "").strip().upper()
        path = _resolved_text(row.get("path"))
        if label and path:
            out.add((label, path))
    return out


def build_general_census_readiness(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path | None,
    source_root: pathlib.Path | None,
    reference_source_root: pathlib.Path | None,
    donor_clients: Iterable[str],
    donor_servers: Iterable[str],
    *,
    active_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    checks = [
        _root_check("client_root", "Client root", client),
        _root_check("server_root", "Server root", server_root),
        _root_check("source_root", "Source Summit", source_root),
        _root_check("reference_source_root", "Source EU de referência", reference_source_root),
    ]
    donor_client_rows = _donor_rows(donor_clients, "CLIENT")
    donor_server_rows = _donor_rows(donor_servers, "SERVER")

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    notes: list[dict[str, str]] = []
    for check in checks:
        if check["required"] and not check["exists"]:
            blockers.append({
                "code": f"{check['key'].upper()}_REQUIRED",
                "message": f"{check['label']} não está configurado ou não existe.",
            })
    missing_donors = [row for row in donor_client_rows + donor_server_rows if not row["exists"]]
    for row in missing_donors:
        blockers.append({
            "code": f"DONOR_{row['side']}_ROOT_MISSING",
            "message": f"Donor {row['side'].lower()} {row['label'] or row['raw']} está salvo, mas não existe mais em {row['path'] or 'path inválido'}. Remova/corrija a linha e salve novamente.",
        })
    if not donor_client_rows:
        warnings.append({
            "code": "NO_DONOR_CLIENTS_CONFIGURED",
            "message": "Nenhum donor client está salvo. O censo pode rodar, mas não poderá propor recuperação client-side a partir de donors.",
        })
    if not donor_server_rows:
        warnings.append({
            "code": "NO_DONOR_SERVERS_CONFIGURED",
            "message": "Nenhum donor server está salvo. O censo pode rodar, mas não poderá propor recuperação server-side a partir de donors.",
        })
    notes.append({
        "code": "CLI_ARGUMENTS_ARE_ONE_RUN_ONLY",
        "message": "Roots/donors passados com --source-root/--reference-source-root/--donor-* no terminal valem para aquela execução; use Salvar fontes para a GUI reutilizá-los.",
    })
    notes.append({
        "code": "EXTERNAL_JOB_NOT_TRACKED",
        "message": "A GUI acompanha progresso apenas de tarefas iniciadas nela. Um censo iniciado em outro terminal aparece aqui quando o relatório final for gravado.",
    })

    current_paths = {
        "client_root": str(client),
        "server_root": _resolved_text(server_root),
        "source_root": _resolved_text(source_root),
        "reference_source_root": _resolved_text(reference_source_root),
    }
    report = _report(project)
    freshness = "NOT_RUN"
    freshness_reasons: list[str] = []
    report_summary: dict[str, Any] | None = None
    if report is not None:
        if report.get("status") == "INVALID_REPORT":
            freshness = "INVALID_REPORT"
            freshness_reasons.append("REPORT_INVALID_JSON")
        else:
            expected_fields = {
                "client_root": report.get("client_root"),
                "server_root": report.get("server_root"),
                "source_root": report.get("source_root"),
                "reference_source_root": report.get("reference_source_root"),
            }
            for key, old in expected_fields.items():
                old_resolved = _resolved_text(old)
                if old_resolved != current_paths.get(key):
                    freshness_reasons.append(key.upper() + "_CHANGED")
            if _normalized_donor_set(report.get("donor_client_roots") or []) != _current_donor_set(donor_client_rows):
                freshness_reasons.append("DONOR_CLIENTS_CHANGED")
            if _normalized_donor_set(report.get("donor_server_roots") or []) != _current_donor_set(donor_server_rows):
                freshness_reasons.append("DONOR_SERVERS_CHANGED")
            freshness = "STALE_CONFIG" if freshness_reasons else "FRESH_CONFIG"
            report_summary = {
                "status": report.get("status"),
                "census_state": report.get("census_state"),
                "generated_at": report.get("generated_at"),
                "candidate_count": report.get("candidate_count"),
                "recoverable_reachable_candidate_count": report.get("recoverable_reachable_candidate_count"),
                "missing_reachable_no_donor_count": report.get("missing_reachable_no_donor_count"),
                "report": report.get("report") or str(project / "pt_build" / "general_asset_census" / "result.json"),
            }
    if freshness == "STALE_CONFIG":
        warnings.append({
            "code": "GENERAL_CENSUS_REPORT_STALE",
            "message": "O relatório existente foi gerado com roots/donors diferentes dos atualmente salvos; execute o censo novamente antes de interpretar os números.",
        })

    can_run = not blockers and not missing_donors
    cmd = [
        *app_command(project),
        "--client-root", str(client),
        "--server-root", current_paths["server_root"] or "<CONFIGURE_SERVER_ROOT>",
        "audit", "general-asset-census",
        "--source-root", current_paths["source_root"] or "<CONFIGURE_SOURCE_SUMMIT>",
        "--reference-source-root", current_paths["reference_source_root"] or "<CONFIGURE_SOURCE_EU>",
    ]
    for row in donor_client_rows:
        cmd.extend(["--donor-client", f"{row['label']}={row['path']}" if row["label"] and row["path"] else row["raw"]])
    for row in donor_server_rows:
        cmd.extend(["--donor-server", f"{row['label']}={row['path']}" if row["label"] and row["path"] else row["raw"]])

    active = active_job if isinstance(active_job, dict) and active_job.get("status") in {"QUEUED", "RUNNING", "CANCELLING"} else None
    if blockers or missing_donors:
        state = "BLOCKED"
    elif active:
        state = "RUNNING"
    elif freshness == "FRESH_CONFIG":
        state = "REPORT_FRESH"
    elif freshness in {"STALE_CONFIG", "INVALID_REPORT"}:
        state = "REPORT_STALE"
    else:
        state = "READY_TO_RUN"

    return {
        "format": FORMAT,
        "state": state,
        "can_run": can_run,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "notes": notes,
        "donor_clients": donor_client_rows,
        "donor_servers": donor_server_rows,
        "donor_client_count": len(donor_client_rows),
        "donor_server_count": len(donor_server_rows),
        "freshness": freshness,
        "freshness_reasons": freshness_reasons,
        "report": report_summary,
        "active_job": active,
        "command": cmd if can_run else None,
        "command_preview": shlex.join(cmd),
        "command_uses_persisted_configuration": True,
        "policy": {
            "plan_only": True,
            "donors_optional_for_execution": True,
            "donor_gap_is_not_runtime_need": True,
            "target_roots_written": False,
        },
    }
