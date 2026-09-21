from __future__ import annotations

import collections
import json
import pathlib
from typing import Any, Callable

from .entity_catalog import build_live_entities, query_entities
from .general_asset_census import query_general_asset_census

FORMAT = "PT_ASSET_CLIENT_ENRICHMENT_UI_V2"
REPORT_FORMAT = "PT_ASSET_CLIENT_ENRICHMENT_REPORT_V1"

ACTOR_GROUPS = {"CHARACTER", "MONSTER", "NPC", "MOB_MONSTER", "MOB_NPC"}


def _is_actor_group(value: object) -> bool:
    return str(value or "").upper() in ACTOR_GROUPS


def _registry_asset_expects_animation(row: dict[str, Any]) -> bool:
    if list(row.get("motions") or []):
        return True
    for cfg in row.get("configs") or []:
        if not isinstance(cfg, dict):
            continue
        if cfg.get("motion_inx") or cfg.get("motion_smb"):
            return True
    return False


def _read_json(path: pathlib.Path) -> dict[str, Any] | None:
    path = pathlib.Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    out = dict(data)
    out["_path"] = str(path)
    try:
        out["_mtime"] = path.stat().st_mtime
    except OSError:
        pass
    return out


def _latest_certifications(path: pathlib.Path) -> dict[str, Any]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("asset_id") or ""),
                str(row.get("test") or ""),
                str(row.get("layer") or ""),
            )
            latest[key] = row
    result_counts: collections.Counter[str] = collections.Counter()
    test_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    assets: set[str] = set()
    recent = sorted(latest.values(), key=lambda x: str(x.get("timestamp") or ""), reverse=True)[:20]
    for row in latest.values():
        result = str(row.get("result") or "UNKNOWN").upper()
        test = str(row.get("test") or "UNKNOWN").upper()
        aid = str(row.get("asset_id") or "")
        if aid:
            assets.add(aid)
        result_counts[result] += 1
        test_counts[test][result] += 1
    return {
        "latest_record_count": len(latest),
        "certified_asset_count": len(assets),
        "result_counts": dict(result_counts),
        "test_counts": {k: dict(v) for k, v in sorted(test_counts.items())},
        "recent": [
            {
                "asset_id": x.get("asset_id"),
                "asset_path": x.get("asset_path"),
                "test": x.get("test"),
                "layer": x.get("layer"),
                "result": x.get("result"),
                "timestamp": x.get("timestamp"),
            }
            for x in recent
        ],
        "path": str(path) if path.is_file() else None,
    }


def asset_analysis_evidence(settings, asset_id: str) -> dict[str, Any]:
    """Collect existing pt_build evidence for one registry asset without rescanning it."""
    work = pathlib.Path(settings.work_dir) / str(asset_id)
    reports: dict[str, Any] = {}
    candidates = {
        "structural": work / "structural" / "summary.json",
        "visual_geometry": work / "visual_geometry" / "summary.json",
        "animation": work / "animation" / "summary.json",
        "roundtrip": work / "roundtrip" / "summary.json",
    }
    for key, path in candidates.items():
        data = _read_json(path)
        if not data:
            continue
        if key == "structural":
            result = data.get("check") or data.get("status") or "REPORT"
        elif key == "visual_geometry":
            result = data.get("visual_asset") or data.get("status") or "REPORT"
        else:
            result = data.get("status") or data.get("check") or data.get("result") or "REPORT"
        reports[key] = {
            "result": result,
            "path": str(path),
            "mtime": data.get("_mtime"),
            "mode": data.get("mode"),
            "lod": data.get("lod"),
            "texture_prepare": data.get("texture_prepare"),
            "authoring_ready_v1": data.get("authoring_ready_v1"),
        }

    artifacts: dict[str, Any] = {}
    artifact_candidates = {
        "structural_static_capability": work / "structural" / "static_capability.json",
        "visual_witness": work / "visual_geometry" / "witness.json",
        "visual_texture_overlay": work / "visual_geometry" / "texture_overlay_report.json",
    }
    for key, path in artifact_candidates.items():
        data = _read_json(path)
        if not data:
            continue
        artifacts[key] = {
            "result": data.get("status") or data.get("check") or data.get("result") or "PRESENT",
            "path": str(path),
            "mtime": data.get("_mtime"),
            "format": data.get("format"),
            "entry_count": len(data.get("entries") or []) if isinstance(data.get("entries"), list) else None,
        }

    cert_path = pathlib.Path(settings.certifications_dir) / "assets.jsonl"
    cert_rows: list[dict[str, Any]] = []
    if cert_path.is_file():
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for line in cert_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict) or str(row.get("asset_id") or "") != str(asset_id):
                continue
            latest[(str(row.get("test") or ""), str(row.get("layer") or ""))] = row
        cert_rows = sorted(
            [
                {
                    "test": row.get("test"), "layer": row.get("layer"),
                    "result": row.get("result"), "timestamp": row.get("timestamp"),
                    "source_sha256": row.get("source_sha256"),
                }
                for row in latest.values()
            ],
            key=lambda x: (str(x.get("test") or ""), str(x.get("layer") or "")),
        )
    return {
        "status": "AVAILABLE" if reports or artifacts or cert_rows else "NO_EVIDENCE",
        "reports": reports,
        "artifacts": artifacts,
        "certifications": cert_rows,
        "workdir": str(work),
    }



def _latest_certification_rows(path: pathlib.Path) -> tuple[dict[str, dict[tuple[str, str], dict[str, Any]]], dict[str, int]]:
    by_asset: dict[str, dict[tuple[str, str], dict[str, Any]]] = collections.defaultdict(dict)
    results: collections.Counter[str] = collections.Counter()
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            aid = str(row.get("asset_id") or "")
            if not aid:
                continue
            key = (str(row.get("test") or "").upper(), str(row.get("layer") or "").upper())
            previous = by_asset[aid].get(key)
            if previous is None or str(row.get("timestamp") or "") >= str(previous.get("timestamp") or ""):
                by_asset[aid][key] = row
    for rows in by_asset.values():
        for row in rows.values():
            results[str(row.get("result") or "UNKNOWN").upper()] += 1
    return by_asset, dict(results)


def _entity_gap_reasons(entity: dict[str, Any]) -> list[str]:
    group = str(entity.get("semantic_group") or "").upper()
    models = list(entity.get("model_paths") or [])
    textures = list(entity.get("texture_paths") or [])
    icons = list(entity.get("icon_paths") or [])
    configs = list(entity.get("config_paths") or [])
    animations = list(entity.get("animation_paths") or [])
    reasons: list[str] = []

    if group in {"CHARACTER", "ITEM", "MONSTER", "NPC"} and not models:
        reasons.append("NO_MODEL_RELATION")
    if group in {"CHARACTER", "MONSTER", "NPC"} and models and not textures:
        reasons.append("NO_TEXTURE_RELATION")
    if group == "ITEM" and models and not (textures or icons):
        reasons.append("NO_TEXTURE_OR_ICON_RELATION")
    if group == "CHARACTER" and int(entity.get("registry_asset_count") or 0) > 0 and models and not configs:
        reasons.append("NO_CONFIG_RELATION")

    # Rigid/animation readiness is actor-specific evidence. Static Effect/Map/UI
    # meshes can be perfectly valid without actor model-info or motion bindings.
    if _is_actor_group(group):
        rigid = int(entity.get("rigid_model_count") or 0)
        rigid_ready = int(entity.get("rigid_binding_ready_count") or 0)
        if rigid and rigid_ready < rigid:
            reasons.append("RIGID_BINDING_INCOMPLETE")

        registry_assets = [x for x in (entity.get("registry_assets") or []) if isinstance(x, dict)]
        if registry_assets:
            expected_anim = [x for x in registry_assets if _registry_asset_expects_animation(x)]
            if expected_anim and any(not bool(x.get("animation_binding_ready")) for x in expected_anim):
                reasons.append("ANIMATION_CONTEXT_PARTIAL")
        else:
            physical_anim_ready = int(entity.get("physical_animation_binding_ready_count") or 0)
            if rigid_ready and animations and physical_anim_ready < rigid_ready:
                reasons.append("ANIMATION_CONTEXT_PARTIAL")

    if group == "EFFECT" and not (models or textures or entity.get("support_paths")):
        reasons.append("NO_EFFECT_PAYLOAD_RELATION")
    if group == "MAP_FIELD" and not (models or textures or entity.get("support_paths") or configs):
        reasons.append("NO_FIELD_PAYLOAD_RELATION")
    return reasons


def _entity_evidence_state(entity: dict[str, Any], reasons: list[str]) -> str:
    if not reasons:
        return "CLOSED_EVIDENCE"
    payload_count = sum(len(entity.get(k) or []) for k in (
        "model_paths", "texture_paths", "icon_paths", "config_paths", "animation_paths", "audio_paths", "support_paths"
    ))
    return "PARTIAL_EVIDENCE" if payload_count else "IDENTITY_ONLY"


def _availability_rows(project: pathlib.Path) -> tuple[str, list[dict[str, Any]]]:
    decisions = (
        "RECOVERABLE_REACHABLE_CANDIDATE",
        "MISSING_REACHABLE_NO_DONOR",
        "REVIEW_REACHABLE_DONOR_CONFLICT",
        "REVIEW_HARD_CONFLICT",
    )
    all_rows: list[dict[str, Any]] = []
    status = "NOT_RUN"
    for decision in decisions:
        offset = 0
        while True:
            report = query_general_asset_census(
                project, side="CLIENT", decision=decision, offset=offset, limit=1000
            )
            status = str(report.get("status") or status)
            rows = [dict(x) for x in (report.get("rows") or []) if isinstance(x, dict)]
            if decision == "REVIEW_HARD_CONFLICT":
                rows = [x for x in rows if str(x.get("required_by_reachable_root") or "").lower() == "true"]
            all_rows.extend(rows)
            raw_count = len(report.get("rows") or [])
            offset += raw_count
            if raw_count == 0 or offset >= int(report.get("filtered_rows") or 0):
                break
    return status, all_rows


def _availability_issue(row: dict[str, Any]) -> dict[str, Any]:
    decision = str(row.get("decision") or "REVIEW").upper()
    if decision == "RECOVERABLE_REACHABLE_CANDIDATE":
        state, action = "RECOVERABLE", "RESTORE_FROM_VERIFIED_DONOR"
    elif decision == "MISSING_REACHABLE_NO_DONOR":
        state, action = "MISSING", "LOCATE_OR_RECONSTRUCT_REQUIRED_ASSET"
    elif decision == "REVIEW_REACHABLE_DONOR_CONFLICT":
        state, action = "REVIEW", "RESOLVE_DONOR_VARIANT_CONFLICT"
    else:
        state, action = "REVIEW", "RESOLVE_HARD_CONFLICT"
    path = str(row.get("path") or "")
    return {
        "state": state,
        "kind": "CLIENT_ASSET_AVAILABILITY",
        "group": str(row.get("category") or row.get("physical_family") or "CLIENT").upper(),
        "target": path,
        "display_name": pathlib.PurePosixPath(path).name if path else decision,
        "path": path,
        "reasons": [decision],
        "evidence": row.get("reachability_evidence") or row.get("review_evidence") or row.get("reason") or "GENERAL_ASSET_CENSUS",
        "suggested_action": action,
        "physical_family": row.get("physical_family"),
        "selected_source": row.get("selected_source"),
        "recovery_bundle_status": row.get("recovery_bundle_status"),
        "related_path_count": int(row.get("recovery_bundle_member_count") or 0),
    }


def audit_client_enrichment(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    catalog,
    entity_seed: dict[str, Any] | None,
    *,
    registry=None,
    settings=None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Build the client-side enrichment report from physical evidence already available locally.

    This is deliberately read-only with respect to the configured client.  The only
    writes are report files under ``pt_build/client_enrichment``.
    """
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    report_dir = project / "pt_build" / "client_enrichment"
    report_path = report_dir / "result.json"
    rows = list(catalog.assets)

    def emit(message: str) -> None:
        if progress:
            progress(message)

    emit(f"catalog files={len(rows)}")
    entities = build_live_entities(rows, entity_seed, registry=registry)
    emit(f"entities={len(entities)}")

    cert_path = pathlib.Path(settings.certifications_dir) / "assets.jsonl" if settings is not None else report_dir / "missing_assets.jsonl"
    cert_by_asset, cert_result_counts = _latest_certification_rows(cert_path)

    issue_rows: list[dict[str, Any]] = []
    entity_state_counts: collections.Counter[str] = collections.Counter()
    entity_group_counts: collections.Counter[str] = collections.Counter()
    entity_gap_reason_counts: collections.Counter[str] = collections.Counter()

    for entity in entities:
        reasons = _entity_gap_reasons(entity)
        state = _entity_evidence_state(entity, reasons)
        group = str(entity.get("semantic_group") or "UNKNOWN")
        entity_state_counts[state] += 1
        entity_group_counts[group] += 1
        entity_gap_reason_counts.update(reasons)
        if reasons:
            issue_rows.append({
                "state": state,
                "kind": "ENTITY_RELATION_GAP",
                "group": group,
                "target": entity.get("entity_key"),
                "display_name": entity.get("display_name"),
                "path": entity.get("representative_model") or entity.get("folder_root") or "",
                "reasons": reasons,
                "evidence": entity.get("identity_evidence"),
                "related_path_count": int(entity.get("asset_count") or 0),
            })

    asset_family_counts: collections.Counter[str] = collections.Counter()
    asset_category_counts: collections.Counter[str] = collections.Counter()
    model_relation_counts: collections.Counter[str] = collections.Counter()
    model_issue_reason_counts: collections.Counter[str] = collections.Counter()
    model_count = 0
    texture_linked_model_count = 0
    configured_model_count = 0
    motion_linked_model_count = 0
    rigid_model_count = 0
    rigid_context_ready_count = 0
    animation_binding_ready_count = 0
    analysis_asset_count = 0
    analysis_problem_count = 0

    for asset in list(getattr(registry, "assets", []) or []):
        asset_family_counts[str(getattr(asset, "family", "") or "UNKNOWN")] += 1
        asset_category_counts[str(getattr(asset, "category", "") or "UNKNOWN")] += 1
        is_model = str(getattr(asset, "kind", "") or "").upper().startswith("SMD_MODEL")
        if not is_model:
            continue
        model_count += 1
        reasons: list[str] = []
        textures = list(getattr(asset, "textures", []) or [])
        configs = list(getattr(asset, "configs", []) or [])
        motions = list(getattr(asset, "motions", []) or [])
        if textures:
            texture_linked_model_count += 1
            model_relation_counts["HAS_TEXTURE_RELATION"] += 1
        else:
            reasons.append("NO_TEXTURE_RELATION")
        if configs:
            configured_model_count += 1
            model_relation_counts["HAS_CONFIG_RELATION"] += 1
        if motions:
            motion_linked_model_count += 1
            model_relation_counts["HAS_MOTION_RELATION"] += 1

        family = str(getattr(asset, "family", "") or "")
        category = str(getattr(asset, "category", "") or "UNKNOWN").upper()
        actor_model = _is_actor_group(category)
        if family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            rigid_model_count += 1
            if bool(getattr(asset, "rigid_context_ready", False)):
                rigid_context_ready_count += 1
            elif actor_model:
                reasons.append("RIGID_CONTEXT_UNRESOLVED")
            if bool(getattr(asset, "animation_binding_ready", False)):
                animation_binding_ready_count += 1
            elif actor_model and motions:
                reasons.append("ANIMATION_BINDING_UNRESOLVED")
            if actor_model and not configs:
                reasons.append("NO_MODEL_INFO_CONFIG")

        cert_rows = cert_by_asset.get(str(getattr(asset, "asset_id", "")), {})
        if cert_rows:
            analysis_asset_count += 1
            bad = sorted({
                f"CERT_{test}_{str(row.get('result') or 'UNKNOWN').upper()}"
                for (test, _layer), row in cert_rows.items()
                if str(row.get("result") or "").upper() not in {"PASS", "N/A", "NA"}
            })
            if bad:
                analysis_problem_count += 1
                reasons.extend(bad)

        if reasons:
            unique_reasons = sorted(set(reasons))
            model_issue_reason_counts.update(unique_reasons)
            issue_rows.append({
                "state": "REVIEW",
                "kind": "MODEL_RELATION_GAP",
                "group": str(getattr(asset, "category", "") or "UNKNOWN"),
                "target": str(getattr(asset, "asset_id", "")),
                "display_name": pathlib.PurePosixPath(str(getattr(asset, "primary_path", "") or "")).name,
                "path": str(getattr(asset, "primary_path", "") or ""),
                "reasons": unique_reasons,
                "evidence": str(getattr(asset, "binding_source", "") or "NONE"),
                "related_path_count": len(set(textures + motions + [str(x.get("inx") or "") for x in configs if isinstance(x, dict)])),
            })

    # Keep certification failures visible even when the asset is not a first-class model.
    for aid, cert_rows in cert_by_asset.items():
        bad_rows = [row for row in cert_rows.values() if str(row.get("result") or "").upper() not in {"PASS", "N/A", "NA"}]
        if not bad_rows:
            continue
        if any(r.get("target") == aid for r in issue_rows):
            continue
        first = bad_rows[0]
        issue_rows.append({
            "state": "REVIEW",
            "kind": "VALIDATION_EVIDENCE",
            "group": "ANALYSIS",
            "target": aid,
            "display_name": first.get("asset_path") or aid,
            "path": first.get("asset_path") or "",
            "reasons": sorted({f"CERT_{str(r.get('test') or 'UNKNOWN').upper()}_{str(r.get('result') or 'UNKNOWN').upper()}" for r in bad_rows}),
            "evidence": "LATEST_CERTIFICATION_RECORD",
            "related_path_count": len(bad_rows),
        })

    census_status, availability_rows = _availability_rows(project)
    availability_decision_counts: collections.Counter[str] = collections.Counter()
    availability_action_counts: collections.Counter[str] = collections.Counter()
    existing_availability = {(str(x.get("kind")), str(x.get("path") or "").casefold()) for x in issue_rows}
    for row in availability_rows:
        issue = _availability_issue(row)
        key = ("CLIENT_ASSET_AVAILABILITY", str(issue.get("path") or "").casefold())
        if key in existing_availability:
            continue
        issue_rows.append(issue)
        existing_availability.add(key)
        availability_decision_counts.update(issue.get("reasons") or [])
        availability_action_counts[str(issue.get("suggested_action") or "REVIEW")] += 1

    issue_rows.sort(key=lambda x: (str(x.get("state")), str(x.get("group")), str(x.get("kind")), str(x.get("path") or x.get("target")).casefold()))
    issue_kind_counts = collections.Counter(str(x.get("kind") or "UNKNOWN") for x in issue_rows)
    issue_state_counts = collections.Counter(str(x.get("state") or "UNKNOWN") for x in issue_rows)

    previewable_count = sum(1 for row in rows if bool(row.get("previewable")))
    image_category_counts = collections.Counter(str(row.get("category") or "OTHER") for row in rows if bool(row.get("previewable")))
    image_extension_counts = collections.Counter(str(row.get("ext") or "(none)") for row in rows if bool(row.get("previewable")))

    assessment_status = "REVIEW_REQUIRED" if issue_rows else "CLOSED_EVIDENCE"

    result = {
        "format": REPORT_FORMAT,
        "status": "PASS" if client.is_dir() else "FAIL",
        "assessment_status": assessment_status if client.is_dir() else "UNAVAILABLE",
        "scope": "CLIENT_READ_ONLY_EVIDENCE_ENRICHMENT",
        "client_root": str(client),
        "catalog": {
            "file_count": len(rows),
            "total_bytes": int(catalog.stats.total_bytes),
            "previewable_image_count": previewable_count,
            "image_category_counts": dict(image_category_counts),
            "image_extension_counts": dict(image_extension_counts),
        },
        "entities": {
            "entity_count": len(entities),
            "group_counts": dict(entity_group_counts),
            "evidence_state_counts": dict(entity_state_counts),
            "gap_reason_counts": dict(entity_gap_reason_counts),
            "closed_evidence_count": int(entity_state_counts.get("CLOSED_EVIDENCE", 0)),
            "partial_evidence_count": int(entity_state_counts.get("PARTIAL_EVIDENCE", 0)),
            "identity_only_count": int(entity_state_counts.get("IDENTITY_ONLY", 0)),
        },
        "registry": {
            "asset_count": len(list(getattr(registry, "assets", []) or [])),
            "family_counts": dict(asset_family_counts),
            "category_counts": dict(asset_category_counts),
            "model_count": model_count,
            "texture_linked_model_count": texture_linked_model_count,
            "configured_model_count": configured_model_count,
            "motion_linked_model_count": motion_linked_model_count,
            "rigid_model_count": rigid_model_count,
            "rigid_context_ready_count": rigid_context_ready_count,
            "animation_binding_ready_count": animation_binding_ready_count,
            "relation_counts": dict(model_relation_counts),
            "gap_reason_counts": dict(model_issue_reason_counts),
        },
        "certifications": {
            "asset_with_evidence_count": analysis_asset_count,
            "asset_with_nonpass_evidence_count": analysis_problem_count,
            "result_counts": cert_result_counts,
            "source": str(cert_path) if cert_path.is_file() else None,
        },
        "asset_availability": {
            "status": census_status,
            "actionable_count": len(availability_rows),
            "decision_counts": dict(availability_decision_counts),
            "suggested_action_counts": dict(availability_action_counts),
            "source": str(project / "pt_build" / "general_asset_census" / "result.json"),
            "automatic_client_import_authorized": False,
        },
        "issues": {
            "count": len(issue_rows),
            "kind_counts": dict(issue_kind_counts),
            "state_counts": dict(issue_state_counts),
            "rows": issue_rows,
        },
        "image_quality_next_step": {
            "candidate_count": previewable_count,
            "policy": "enhance into the project enhancement workspace first; original client remains unchanged until an explicitly armed verified enhancement publish",
        },
        "policy": {
            "client_source_read_only": True,
            "report_is_runtime_certification": False,
            "writer_authorized": False,
            "generated_outputs_outside_client_only": True,
            "enhancement_workspace": str((project.parent / "enhancement").resolve()),
            "filename_guess_is_binding_evidence": False,
        },
        "client_modified": False,
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emit(f"issues={len(issue_rows)} report={report_path}")
    return result


def query_client_enrichment_report(
    project_root: pathlib.Path,
    *,
    query: str = "",
    state: str = "",
    group: str = "",
    kind: str = "",
    offset: int = 0,
    limit: int = 250,
) -> dict[str, Any]:
    path = pathlib.Path(project_root).resolve() / "pt_build" / "client_enrichment" / "result.json"
    report = _read_json(path)
    if not report:
        return {
            "format": REPORT_FORMAT,
            "status": "NO_REPORT",
            "total_rows": 0,
            "filtered_rows": 0,
            "rows": [],
            "state_counts": {},
            "group_counts": {},
            "kind_counts": {},
        }
    rows = list(((report.get("issues") or {}).get("rows") or []))
    terms = [x.casefold() for x in str(query or "").split() if x.strip()]
    state = str(state or "").upper()
    group = str(group or "").upper()
    kind = str(kind or "").upper()
    state_counts = collections.Counter(str(x.get("state") or "UNKNOWN") for x in rows)
    group_counts = collections.Counter(str(x.get("group") or "UNKNOWN") for x in rows)
    kind_counts = collections.Counter(str(x.get("kind") or "UNKNOWN") for x in rows)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if state and str(row.get("state") or "").upper() != state:
            continue
        if group and str(row.get("group") or "").upper() != group:
            continue
        if kind and str(row.get("kind") or "").upper() != kind:
            continue
        if terms:
            hay = " ".join([
                str(row.get("target") or ""), str(row.get("display_name") or ""), str(row.get("path") or ""),
                str(row.get("group") or ""), str(row.get("kind") or ""), " ".join(row.get("reasons") or []),
                str(row.get("evidence") or ""), str(row.get("suggested_action") or ""),
            ]).casefold()
            if not all(t in hay for t in terms):
                continue
        filtered.append(row)
    offset = max(0, int(offset))
    limit = max(1, min(2000, int(limit)))
    return {
        "format": REPORT_FORMAT,
        "status": report.get("status") or "PASS",
        "assessment_status": report.get("assessment_status") or "REVIEW_REQUIRED",
        "report": str(path),
        "total_rows": len(rows),
        "filtered_rows": len(filtered),
        "rows": filtered[offset:offset + limit],
        "state_counts": dict(state_counts),
        "group_counts": dict(group_counts),
        "kind_counts": dict(kind_counts),
        "summary": {
            "entities": report.get("entities") or {},
            "registry": report.get("registry") or {},
            "certifications": report.get("certifications") or {},
            "asset_availability": report.get("asset_availability") or {},
            "catalog": report.get("catalog") or {},
        },
    }

def build_client_enrichment_summary(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    catalog,
    entity_seed: dict[str, Any] | None,
    *,
    registry=None,
    settings=None,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    rows = list(catalog.assets)
    category_counts = collections.Counter(str(x.get("category") or "OTHER") for x in rows)
    visibility_counts = collections.Counter(str(x.get("visibility_tier") or "UNKNOWN") for x in rows)
    physical_counts = collections.Counter(str(x.get("physical_family") or x.get("physical_hint") or "OTHER") for x in rows)

    entity_report = query_entities(rows, entity_seed, limit=1, registry=registry)
    registry_meta = None
    if settings is not None:
        registry_meta = _read_json(pathlib.Path(settings.inventory).parent / "registry_meta.json")
        certifications = _latest_certifications(pathlib.Path(settings.certifications_dir) / "assets.jsonl")
    else:
        certifications = {"latest_record_count": 0, "certified_asset_count": 0, "result_counts": {}, "test_counts": {}, "recent": [], "path": None}

    contracts_dir = project / "pt_build" / "asset_contracts"
    source_contracts = _read_json(contracts_dir / "source_contract_census.json")
    player_classes = _read_json(contracts_dir / "player_class_contract_census.json")
    general_report = _read_json(project / "pt_build" / "general_asset_census" / "result.json")
    client_census = query_general_asset_census(project, side="CLIENT", limit=1)
    vendor_graph = _read_json(project / "pt_build" / "enrichment_vendor" / "dependency_graph.result.json")
    client_superset = _read_json(project / "pt_build" / "aggregate" / "client_superset" / "all" / "manifest.json")
    client_enrichment = _read_json(project / "pt_build" / "client_enrichment" / "result.json")

    graph_summary = (vendor_graph or {}).get("summary_data") or {}
    return {
        "format": FORMAT,
        "status": "READY" if client.is_dir() else "UNCONFIGURED",
        "client_root": str(client),
        "client_root_exists": client.is_dir(),
        "catalog": {
            "file_count": len(rows),
            "total_bytes": int(catalog.stats.total_bytes),
            "category_counts": dict(category_counts),
            "visibility_counts": dict(visibility_counts),
            "physical_family_counts": dict(physical_counts),
            "default_hidden_count": sum(visibility_counts.get(x, 0) for x in ("OPERATIONAL", "USER_DATA", "INSTALLER_SYSTEM", "NOISE")),
        },
        "entities": {
            "live_entity_count": entity_report.get("live_entity_count"),
            "group_counts": entity_report.get("live_group_counts") or {},
            "known_seed_entity_count": entity_report.get("known_seed_entity_count"),
        },
        "registry": {
            "status": "READY" if registry_meta else "NO_REPORT",
            "record_count": (registry_meta or {}).get("record_count"),
            "client_root": (registry_meta or {}).get("client_root"),
            "report": (registry_meta or {}).get("_path"),
        },
        "certifications": certifications,
        "reports": {
            "source_contracts": source_contracts,
            "player_classes": player_classes,
            "general_census": general_report,
            "client_census": {
                "status": client_census.get("status"),
                "census_state": client_census.get("census_state"),
                "client_candidate_count": client_census.get("filtered_rows"),
                "total_candidate_count": client_census.get("total_rows"),
            },
            "vendor_graph": {
                "status": (vendor_graph or {}).get("status"),
                "nodes": graph_summary.get("nodes"),
                "edges": graph_summary.get("edges"),
                "missing_reference_edges": graph_summary.get("missing_reference_edges"),
                "skip_client_scan": (vendor_graph or {}).get("skip_client_scan"),
                "report": (vendor_graph or {}).get("_path"),
            } if vendor_graph else None,
            "client_superset": client_superset,
            "client_enrichment": {
                "status": (client_enrichment or {}).get("assessment_status") or (client_enrichment or {}).get("status"),
                "run_status": (client_enrichment or {}).get("status"),
                "assessment_status": (client_enrichment or {}).get("assessment_status"),
                "issue_count": ((client_enrichment or {}).get("issues") or {}).get("count"),
                "issue_kind_counts": ((client_enrichment or {}).get("issues") or {}).get("kind_counts") or {},
                "entity_state_counts": ((client_enrichment or {}).get("entities") or {}).get("evidence_state_counts") or {},
                "closed_entity_count": ((client_enrichment or {}).get("entities") or {}).get("closed_evidence_count"),
                "model_count": ((client_enrichment or {}).get("registry") or {}).get("model_count"),
                "texture_linked_model_count": ((client_enrichment or {}).get("registry") or {}).get("texture_linked_model_count"),
                "rigid_context_ready_count": ((client_enrichment or {}).get("registry") or {}).get("rigid_context_ready_count"),
                "availability_status": ((client_enrichment or {}).get("asset_availability") or {}).get("status"),
                "availability_count": ((client_enrichment or {}).get("asset_availability") or {}).get("actionable_count"),
                "availability_decision_counts": ((client_enrichment or {}).get("asset_availability") or {}).get("decision_counts") or {},
                "availability_action_counts": ((client_enrichment or {}).get("asset_availability") or {}).get("suggested_action_counts") or {},
                "report": (client_enrichment or {}).get("_path"),
            } if client_enrichment else None,
        },
        "policy": {
            "client_source_read_only_by_default": True,
            "client_write_only_via_verified_bundle": True,
            "client_write_only_via_verified_transactions": True,
            "enrichment_reports_are_evidence_not_runtime_certification": True,
            "analysis_reports_under_pt_build": True,
            "enhancement_candidates_under_workspace": str((project.parent / "enhancement").resolve()),
        },
        "client_modified": False,
    }
