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


def _text_contains(row: Any, query: str) -> bool:
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
                "Ícone do inventário não foi fechado no client",
                "O path calculado pelo contrato runtime não resolveu para um arquivo presente. Revise ItemFilePath/DorpItem e o asset físico do client.",
            ))
        if drop != "PRESENT":
            reasons.append(_review_reason(
                "DROP_MODEL_NOT_PRESENT",
                "Modelo visual de drop não foi fechado no client",
                "O ASE esperado em Items/DropItem não foi encontrado. Isso é closure visual; não significa que o item não possa existir no OpenItem.",
            ))
    if row.get("status") == "RUNTIME_CATALOG_MISSING":
        reasons.append(_review_reason(
            "RUNTIME_CATALOG_MISSING",
            "Código não existe no catálogo runtime source-verificado",
            "Não crie um OpenItem para este código até existir contrato sITEM comprovado. Registro de novo código runtime continua fora do writer promovido.",
        ))
    if row.get("authoring_ready"):
        actions.append(_review_action("AUTHORING", "Abrir definição do item", authoring_kind="ITEM", path=row.get("authoring_path")))
    actions.append(_review_action("ITEM_LOOKUP", "Inspecionar contrato runtime", code=row.get("code")))
    row["review_required"] = row.get("status") != "CLOSED"
    row["review_reasons"] = reasons
    row["review_actions"] = actions
    row["review_summary"] = (
        "Closure visual completa." if not row["review_required"]
        else "Revise as dependências visuais abaixo; o estado REVIEW não é, sozinho, prova de item inválido."
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
            "Actor do SPM não encontrou definição Monster",
            f"Sem definição única para: {names}. Corrija o nome no SPM ou crie/corrija a definição do monstro.",
        ))
    if ambiguous:
        names = ", ".join(str(x.get("name") or "?") for x in ambiguous[:8])
        reasons.append(_review_reason(
            "SPM_ACTOR_AMBIGUOUS",
            "Actor do SPM corresponde a mais de uma definição",
            f"Correspondência ambígua para: {names}. Escolha/corrija a definição antes de confiar na closure de drops.",
        ))
    row["review_required"] = bool(reasons)
    row["review_reasons"] = reasons
    row["review_actions"] = [
        _review_action("AUTHORING", "Editar SPM", authoring_kind="SPM", path=row.get("authoring_path"))
    ] if row.get("authoring_ready") else []
    row["review_summary"] = "Mapa resolvido." if not reasons else "A closure do mapa não está completa; siga as ações abaixo."


def _decorate_definition_review(row: dict[str, Any]) -> None:
    kind = str(row.get("kind") or "").upper()
    reasons: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = []
    if row.get("error"):
        reasons.append(_review_reason(
            "READ_OR_DECODE_ERROR",
            "A definição não pôde ser lida corretamente",
            str(row.get("error")),
        ))
    for code in row.get("reasons") or []:
        if code == "READ_OR_DECODE_ERROR":
            continue
        reasons.append(_review_reason(str(code), "Auditoria marcou esta definição para revisão", str(code)))
    missing_refs = [x for x in row.get("item_references") or [] if not bool((x or {}).get("openitem_definition_present"))]
    if missing_refs:
        codes = [str((x or {}).get("code") or "?") for x in missing_refs]
        reasons.append(_review_reason(
            "ITEM_REFERENCE_WITHOUT_OPENITEM",
            "Há referências de item sem definição OpenItem encontrada",
            "Códigos: " + ", ".join(codes[:20]) + (" …" if len(codes) > 20 else "") + ". Pesquise cada código e crie/corrija a definição somente se o código runtime for source-verificado.",
        ))
        for code in codes[:8]:
            actions.append(_review_action("ITEM_LOOKUP", f"Revisar item {code}", code=code))
    if row.get("authoring_ready"):
        actions.insert(0, _review_action(
            "AUTHORING",
            "Editar monstro" if kind == "MONSTER" else "Editar NPC",
            authoring_kind=kind,
            path=row.get("authoring_path"),
        ))
    row["review_required"] = bool(reasons)
    row["review_reasons"] = reasons
    row["review_actions"] = actions
    row["review_summary"] = "Definição sem bloqueios detectados pela closure." if not reasons else "REVIEW significa que existe uma pendência concreta; veja motivo e ação abaixo."
    row["item_reference_note"] = (
        "Esta contagem é uma varredura ampla de códigos de item no arquivo; 0 NÃO significa automaticamente 'sem drop'. "
        "Para MONSTER, use 'Drops item' quando disponível, pois ele olha especificamente FallItem/ExtraFallItem."
    )
    if kind == "MONSTER":
        if row.get("drop_item_reference_count") is None:
            row["drop_note"] = "Relatório antigo: audite novamente para separar drops explícitos de outras referências de item."
        elif int(row.get("drop_item_reference_count") or 0) == 0:
            row["drop_note"] = (
                "Nenhum código de item foi detectado nas diretivas FallItem/ExtraFallItem. Isso não prova 'sem drop': "
                "podem existir diretivas de dinheiro ou mecanismos ainda fora deste contrato."
            )
        else:
            row["drop_note"] = "Códigos detectados especificamente em FallItem/ExtraFallItem."
    row["zhoon_note"] = (
        ".zhoon é uma referência companion/visual histórica do monstro; não é uma tabela de drop e não deve ser interpretada como item."
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
