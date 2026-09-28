from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import shutil
import time
from typing import Any

PLAN_FORMAT = "PT_ASSET_QUARANTINE_PLAN_V2"
TX_FORMAT = "PT_ASSET_QUARANTINE_TRANSACTION_V1"
APPLY_CONFIRM = "MOVE_Q0_TO_QUARANTINE"
Q1_COMPONENT_CONFIRM = "MOVE_Q1_COMPONENT_TO_QUARANTINE"
RESTORE_CONFIRM = "RESTORE_QUARANTINE"
Q1_MANUAL_MAX_COMPONENT_SIZE = 10


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _bool(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "sim"}


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_client_path(client: pathlib.Path, rel: str) -> pathlib.Path:
    rel_norm = _norm(rel)
    if not rel_norm or rel_norm.startswith("../") or "/../" in f"/{rel_norm}/":
        raise ValueError(f"UNSAFE_RELATIVE_PATH:{rel}")
    target = (client / pathlib.PurePosixPath(rel_norm)).resolve()
    try:
        target.relative_to(client.resolve())
    except ValueError as exc:
        raise ValueError(f"PATH_ESCAPES_CLIENT_ROOT:{rel}") from exc
    return target


def _load_tsv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _q0_reason(row: dict[str, str]) -> str | None:
    if row.get("state") != "ORPHAN_CANDIDATE":
        return None
    if _bool(row.get("graph_linked")) or _bool(row.get("root_reachable")):
        return None
    if str(row.get("entity_bundle") or "").strip():
        return None
    if str(row.get("evidence") or "").strip():
        return None
    if str(row.get("cook_status") or "").casefold() != "error":
        return None
    if not _bool(row.get("cook_documented_outlier")):
        return None
    if str(row.get("integrity_action") or "") != "INVALID_UNREACHABLE_QUARANTINE_REVIEW":
        return None
    if _bool(row.get("deletion_authorized")):
        return None
    return "DOCUMENTED_INVALID_OR_NON_RUNTIME_ASSET_WITH_ZERO_KNOWN_LINKAGE"




def _q1_review_score(members: list[dict[str, str]], meta: dict[str, Any]) -> dict[str, Any]:
    """Deterministic review priority only. Never authorizes quarantine/delete."""
    protected = [x for x in members if str(x.get("state") or "").startswith("PROTECTED_")]
    entity_bundle = [x for x in members if str(x.get("entity_bundle") or "").strip()]
    positive_evidence = [
        x for x in members
        if str(x.get("state") or "").startswith("PROTECTED_")
        or str(x.get("evidence") or "").strip() not in {"", "CONTRACT_GRAPH_EDGE"}
    ]
    invalid = [
        x for x in members
        if str(x.get("integrity_action") or "").startswith(("INVALID_", "DECODE_FAILURE_"))
    ]
    documented_invalid = [
        x for x in invalid
        if _bool(x.get("cook_documented_outlier"))
        and str(x.get("cook_status") or "").casefold() == "error"
    ]
    if protected or entity_bundle or positive_evidence:
        return {
            "review_score": 0,
            "review_band": "BLOCKED",
            "review_reason": "POSITIVE_RETENTION_OR_ENTITY_EVIDENCE",
            "review_factors": ["blocked-positive-evidence"],
            "protected_member_count": len(protected),
            "entity_bundle_member_count": len(entity_bundle),
            "positive_evidence_member_count": len(positive_evidence),
            "invalid_member_count": len(invalid),
            "documented_invalid_member_count": len(documented_invalid),
        }

    size = len(members)
    ext_in = int(meta.get("external_incoming_edge_count") or 0)
    ext_out = int(meta.get("external_outgoing_edge_count") or 0)
    entry_count = int(meta.get("entry_count") or len(meta.get("entry_nodes") or []) or 0)
    score = 0
    factors: list[str] = []
    if documented_invalid:
        score += 50; factors.append(f"documented-invalid={len(documented_invalid)}")
    elif invalid:
        score += 35; factors.append(f"invalid-or-decode-failure={len(invalid)}")
    if invalid and len(invalid) == size:
        score += 20; factors.append("all-members-invalid")
    if size <= 3:
        score += 10; factors.append(f"small-component={size}")
    elif size <= 10:
        score += 5; factors.append(f"compact-component={size}")
    if ext_in == 0:
        score += 10; factors.append("no-external-incoming")
    if ext_out == 0:
        score += 5; factors.append("no-external-outgoing")
    if entry_count <= 1:
        score += 5; factors.append(f"entry-count={entry_count}")
    score = min(100, score)
    if score >= 70:
        band = "A"
        reason = "PRIORITY_A_INVALID_ISOLATED_COMPONENT_REVIEW"
    elif score >= 40:
        band = "B"
        reason = "PRIORITY_B_COMPONENT_REVIEW"
    else:
        band = "C"
        reason = "PRIORITY_C_COMPONENT_REVIEW"
    return {
        "review_score": score,
        "review_band": band,
        "review_reason": reason,
        "review_factors": factors,
        "protected_member_count": 0,
        "entity_bundle_member_count": 0,
        "positive_evidence_member_count": 0,
        "invalid_member_count": len(invalid),
        "documented_invalid_member_count": len(documented_invalid),
    }


def quarantine_review_queue(
    project_root: str | pathlib.Path,
    *,
    band: str = "",
    component: str = "",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Read-only query over persisted Q1 review rankings."""
    project = pathlib.Path(project_root).resolve()
    plan_file = _default_plan(project)
    plan = _load_json(plan_file)
    if plan.get("format") != PLAN_FORMAT or plan.get("status") != "PASS":
        return {
            "status": "NOT_RUN",
            "reason": "QUARANTINE_PLAN_REQUIRED",
            "plan": str(plan_file),
            "deletion_authorized": False,
        }
    rows = list(plan.get("q1_components") or [])
    band_u = str(band or "").strip().upper()
    component_u = str(component or "").strip().upper()
    if band_u:
        rows = [x for x in rows if str(x.get("review_band") or "").upper() == band_u]
    if component_u:
        rows = [x for x in rows if str(x.get("component_id") or "").upper() == component_u]
    rows.sort(key=lambda x: (-int(x.get("review_score") or 0), int(x.get("size") or 0), str(x.get("component_id") or "")))
    total = len(rows)
    offset = max(0, int(offset or 0))
    limit = min(500, max(1, int(limit or 50)))
    page = rows[offset:offset + limit]
    return {
        "status": "PASS",
        "plan": str(plan_file),
        "band": band_u,
        "component": component_u,
        "total_rows": total,
        "offset": offset,
        "limit": limit,
        "rows": page,
        "policy": {
            "review_score_is_not_delete_authority": True,
            "q1_is_review_only": True,
            "q1_review_score_is_priority_not_delete_authority": True,
            "q1_blocked_if_positive_retention_or_entity_evidence": True,
            "q1_manual_component_quarantine_requires_separate_explicit_command": True,
            "apply_moves_q0_only": True,
            "deletion_authorized": False,
        },
        "deletion_authorized": False,
    }

def _q1_manual_quarantine_assessment(
    client: pathlib.Path,
    members: list[dict[str, str]],
    meta: dict[str, Any],
    review: dict[str, Any],
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Strict manual-only gate. Ranking never grants move authority by itself."""
    blockers: list[str] = []
    size = len(members)
    if str(review.get("review_band") or "").upper() != "A":
        blockers.append("REVIEW_BAND_NOT_A")
    if size < 1 or size > Q1_MANUAL_MAX_COMPONENT_SIZE:
        blockers.append(f"COMPONENT_SIZE_OUTSIDE_1_{Q1_MANUAL_MAX_COMPONENT_SIZE}")
    if int(meta.get("external_incoming_edge_count") or 0) != 0:
        blockers.append("EXTERNAL_INCOMING_EDGE_PRESENT")
    if int(meta.get("external_outgoing_edge_count") or 0) != 0:
        blockers.append("EXTERNAL_OUTGOING_EDGE_PRESENT")
    if int(review.get("protected_member_count") or 0) != 0:
        blockers.append("PROTECTED_MEMBER_PRESENT")
    if int(review.get("entity_bundle_member_count") or 0) != 0:
        blockers.append("ENTITY_BUNDLE_MEMBER_PRESENT")
    if int(review.get("positive_evidence_member_count") or 0) != 0:
        blockers.append("POSITIVE_EVIDENCE_MEMBER_PRESENT")
    if int(review.get("documented_invalid_member_count") or 0) < 1:
        blockers.append("DOCUMENTED_INVALID_MEMBER_REQUIRED")

    seen: set[str] = set()
    for row in members:
        rel = _norm(row.get("path") or "")
        key = rel.casefold()
        if not rel or key in seen:
            blockers.append("INVALID_OR_DUPLICATE_MEMBER_PATH")
            continue
        seen.add(key)
        if str(row.get("state") or "") != "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE":
            blockers.append(f"MEMBER_NOT_ROOT_UNREACHABLE_REVIEW:{rel}")
        if not _bool(row.get("graph_linked")) or _bool(row.get("root_reachable")):
            blockers.append(f"MEMBER_GRAPH_ROOT_STATE_UNSAFE:{rel}")
        if str(row.get("entity_bundle") or "").strip():
            blockers.append(f"MEMBER_ENTITY_BUNDLE_PRESENT:{rel}")
        evidence = str(row.get("evidence") or "").strip()
        if evidence not in {"", "CONTRACT_GRAPH_EDGE"}:
            blockers.append(f"MEMBER_POSITIVE_EVIDENCE_PRESENT:{rel}")
        if _bool(row.get("deletion_authorized")):
            blockers.append(f"MEMBER_DELETE_FLAG_UNEXPECTED:{rel}")

    blockers = sorted(set(blockers))
    if blockers:
        return False, blockers, []

    # Only strict eligible components pay the physical SHA-256 cost.
    manifest: list[dict[str, Any]] = []
    for row in members:
        rel = _norm(row.get("path") or "")
        try:
            physical = _safe_client_path(client, rel)
        except ValueError:
            blockers.append(f"UNSAFE_MEMBER_PATH:{rel}")
            continue
        if not physical.is_file() or physical.is_symlink():
            blockers.append(f"MEMBER_PHYSICAL_FILE_REQUIRED:{rel}")
            continue
        manifest.append({
            "path": rel,
            "bytes": int(physical.stat().st_size),
            "sha256": _sha256(physical),
        })
    if len(manifest) != size:
        blockers.append("PHYSICAL_MEMBER_MANIFEST_INCOMPLETE")
    blockers = sorted(set(blockers))
    if blockers:
        return False, blockers, []
    return True, [], sorted(manifest, key=lambda x: str(x.get("path") or "").casefold())


def build_quarantine_plan(project_root: str | pathlib.Path, client_root: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    retention_dir = project / "pt_build" / "asset_retention"
    assets_tsv = retention_dir / "assets.tsv"
    retention_json = retention_dir / "result.json"
    components_json = retention_dir / "components.json"
    out_dir = project / "pt_build" / "quarantine_plan"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_tsv(assets_tsv)
    retention = _load_json(retention_json)
    components = _load_json(components_json)
    if not rows:
        result = {
            "format": PLAN_FORMAT,
            "status": "NOT_RUN",
            "reason": "ASSET_RETENTION_REPORT_REQUIRED",
            "deletion_authorized": False,
        }
        (out_dir / "plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    q0: list[dict[str, Any]] = []
    for row in rows:
        reason = _q0_reason(row)
        if not reason:
            continue
        rel = _norm(row.get("path") or "")
        try:
            physical = _safe_client_path(client, rel)
        except ValueError:
            continue
        if not physical.is_file() or physical.is_symlink():
            continue
        st = physical.stat()
        q0.append({
            "path": rel,
            "tier": "Q0_HIGH_CONFIDENCE_INVALID_ORPHAN",
            "action": "QUARANTINE_ELIGIBLE",
            "reason": reason,
            "bytes": int(st.st_size),
            "sha256": _sha256(physical),
            "state": row.get("state") or "",
            "physical_family": row.get("physical_family") or "",
            "cook_failure_class": row.get("cook_failure_class") or "",
            "cook_integrity_state": row.get("cook_integrity_state") or "",
            "cook_asset_classification": row.get("cook_asset_classification") or "",
            "cook_runtime_note": row.get("cook_runtime_note") or "",
            "deletion_authorized": False,
        })
    q0.sort(key=lambda x: str(x.get("path") or "").casefold())

    # Q1 is review-only. Components with positive evidence remain explicitly blocked.
    by_component: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        cid = str(row.get("component_id") or "").strip()
        if cid:
            by_component.setdefault(cid, []).append(row)
    component_meta = {str(x.get("component_id") or ""): x for x in components.get("components", []) if isinstance(x, dict)}
    q1: list[dict[str, Any]] = []
    for cid, members in sorted(by_component.items()):
        meta = component_meta.get(cid, {})
        evidence = sorted({str(x.get("evidence") or "").strip() for x in members if str(x.get("evidence") or "").strip()})
        review = _q1_review_score(members, meta)
        manual_eligible, manual_blockers, member_manifest = _q1_manual_quarantine_assessment(client, members, meta, review)
        state = "Q1_BLOCKED_POSITIVE_EVIDENCE" if review["review_band"] == "BLOCKED" else f"Q1_PRIORITY_{review['review_band']}_REVIEW"
        q1.append({
            "component_id": cid,
            "tier": state,
            "action": "REVIEW_ONLY",
            "review_score": review["review_score"],
            "review_band": review["review_band"],
            "review_reason": review["review_reason"],
            "review_factors": review["review_factors"],
            "size": len(members),
            "entry_nodes": meta.get("entry_nodes") or [],
            "external_incoming_edge_count": int(meta.get("external_incoming_edge_count") or 0),
            "external_outgoing_edge_count": int(meta.get("external_outgoing_edge_count") or 0),
            "protected_member_count": review["protected_member_count"],
            "entity_bundle_member_count": review["entity_bundle_member_count"],
            "positive_evidence_member_count": review["positive_evidence_member_count"],
            "invalid_member_count": review["invalid_member_count"],
            "documented_invalid_member_count": review["documented_invalid_member_count"],
            "manual_quarantine_eligible": manual_eligible,
            "manual_quarantine_blockers": manual_blockers,
            "member_manifest": member_manifest if manual_eligible else [],
            "evidence": evidence,
            "path_sample": sorted([str(x.get("path") or "") for x in members], key=str.casefold)[:20],
            "deletion_authorized": False,
        })

    retention_sha = _sha256(retention_json) if retention_json.is_file() else ""
    assets_sha = _sha256(assets_tsv) if assets_tsv.is_file() else ""
    result = {
        "format": PLAN_FORMAT,
        "status": "PASS",
        "generated_at_epoch": int(time.time()),
        "client_root": str(client),
        "retention_report": str(retention_json),
        "retention_report_sha256": retention_sha,
        "retention_assets_tsv": str(assets_tsv),
        "retention_assets_sha256": assets_sha,
        "q0_count": len(q0),
        "q0_bytes": sum(int(x.get("bytes") or 0) for x in q0),
        "q1_component_count": len(q1),
        "q1_blocked_component_count": sum(1 for x in q1 if x.get("review_band") == "BLOCKED"),
        "q1_review_component_count": sum(1 for x in q1 if x.get("review_band") in {"A", "B", "C"}),
        "q1_priority_a_count": sum(1 for x in q1 if x.get("review_band") == "A"),
        "q1_priority_b_count": sum(1 for x in q1 if x.get("review_band") == "B"),
        "q1_priority_c_count": sum(1 for x in q1 if x.get("review_band") == "C"),
        "q0": q0,
        "q1_components": q1,
        "policy": {
            "q0_requires_documented_invalid_outlier": True,
            "q0_requires_zero_graph_linkage": True,
            "q0_requires_zero_root_reachability": True,
            "q0_requires_zero_positive_evidence": True,
            "q0_requires_no_entity_bundle": True,
            "q1_is_review_only": True,
            "q1_review_score_is_priority_not_delete_authority": True,
            "q1_blocked_if_positive_retention_or_entity_evidence": True,
            "q1_manual_component_quarantine_requires_band_a": True,
            "q1_manual_component_quarantine_requires_exact_component": True,
            "q1_manual_component_quarantine_requires_explicit_confirmation": True,
            "q1_manual_component_quarantine_max_size": Q1_MANUAL_MAX_COMPONENT_SIZE,
            "apply_moves_q0_only": True,
            "apply_component_moves_one_q1_only": True,
            "delete_authorized": False,
            "restore_required_before_any_future_delete_policy": True,
        },
        "deletion_authorized": False,
    }

    plan_json = out_dir / "plan.json"
    summary_json = out_dir / "summary.json"
    q0_tsv = out_dir / "q0_assets.tsv"
    q1_tsv = out_dir / "q1_components.tsv"
    result["plan"] = str(plan_json)
    result["summary_report"] = str(summary_json)
    result["q0_table"] = str(q0_tsv)
    result["q1_table"] = str(q1_tsv)
    plan_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: v for k, v in result.items() if k not in {"q0", "q1_components"}}
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    q0_fields = ["path", "tier", "action", "reason", "bytes", "sha256", "state", "physical_family", "cook_failure_class", "cook_integrity_state", "cook_asset_classification", "cook_runtime_note", "deletion_authorized"]
    with q0_tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=q0_fields, delimiter="\t", extrasaction="ignore")
        w.writeheader(); w.writerows(q0)
    q1_fields = ["component_id", "tier", "action", "review_score", "review_band", "review_reason", "review_factors", "size", "external_incoming_edge_count", "external_outgoing_edge_count", "protected_member_count", "entity_bundle_member_count", "positive_evidence_member_count", "invalid_member_count", "documented_invalid_member_count", "manual_quarantine_eligible", "manual_quarantine_blockers", "evidence", "entry_nodes", "path_sample", "deletion_authorized"]
    with q1_tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=q1_fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in q1:
            cooked = dict(row)
            for key in ("review_factors", "manual_quarantine_blockers", "evidence", "entry_nodes", "path_sample"):
                cooked[key] = " | ".join(map(str, cooked.get(key) or []))
            w.writerow(cooked)
    return result


def _default_plan(project: pathlib.Path) -> pathlib.Path:
    return project / "pt_build" / "quarantine_plan" / "plan.json"


def _latest_transaction_path(project: pathlib.Path) -> pathlib.Path | None:
    pointer = project / "pt_build" / "quarantine_store" / "latest_transaction.txt"
    if not pointer.is_file():
        return None
    text = pointer.read_text(encoding="utf-8").strip()
    if not text:
        return None
    p = pathlib.Path(text)
    if not p.is_absolute():
        p = project / p
    return p


def apply_quarantine_plan(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    *,
    plan_path: str | pathlib.Path | None = None,
    confirm: str = "",
) -> dict[str, Any]:
    if confirm != APPLY_CONFIRM:
        return {"status": "REFUSED", "reason": f"CONFIRM_REQUIRED:{APPLY_CONFIRM}", "deletion_authorized": False}
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    plan_file = pathlib.Path(plan_path).resolve() if plan_path else _default_plan(project)
    plan = _load_json(plan_file)
    if plan.get("format") != PLAN_FORMAT or plan.get("status") != "PASS":
        return {"status": "REFUSED", "reason": "VALID_QUARANTINE_PLAN_REQUIRED", "plan": str(plan_file), "deletion_authorized": False}
    if pathlib.Path(str(plan.get("client_root") or "")).resolve() != client:
        return {"status": "REFUSED", "reason": "CLIENT_ROOT_DIFFERS_FROM_PLAN", "deletion_authorized": False}
    retention_file = pathlib.Path(str(plan.get("retention_report") or ""))
    assets_file = pathlib.Path(str(plan.get("retention_assets_tsv") or ""))
    if not retention_file.is_file() or _sha256(retention_file) != str(plan.get("retention_report_sha256") or ""):
        return {"status": "REFUSED", "reason": "RETENTION_REPORT_CHANGED_REBUILD_PLAN", "deletion_authorized": False}
    if not assets_file.is_file() or _sha256(assets_file) != str(plan.get("retention_assets_sha256") or ""):
        return {"status": "REFUSED", "reason": "RETENTION_ASSETS_CHANGED_REBUILD_PLAN", "deletion_authorized": False}

    items = list(plan.get("q0") or [])
    if not items:
        return {"status": "PASS", "state": "NO_Q0_ASSETS", "moved_count": 0, "deletion_authorized": False}

    prepared: list[tuple[dict[str, Any], pathlib.Path]] = []
    for item in items:
        rel = _norm(item.get("path") or "")
        src = _safe_client_path(client, rel)
        if not src.is_file() or src.is_symlink():
            return {"status": "REFUSED", "reason": f"Q0_SOURCE_MISSING_OR_UNSAFE:{rel}", "deletion_authorized": False}
        if src.stat().st_size != int(item.get("bytes") or -1) or _sha256(src) != str(item.get("sha256") or ""):
            return {"status": "REFUSED", "reason": f"Q0_SOURCE_CHANGED:{rel}", "deletion_authorized": False}
        prepared.append((item, src))

    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    tx_id = f"QTN-{stamp}-{os.getpid()}"
    tx_dir = project / "pt_build" / "quarantine_store" / tx_id
    files_dir = tx_dir / "files"
    tx_dir.mkdir(parents=True, exist_ok=False)
    moved: list[dict[str, Any]] = []
    try:
        for item, src in prepared:
            rel = _norm(item.get("path") or "")
            dst = files_dir / pathlib.PurePosixPath(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                raise FileExistsError(f"QUARANTINE_DEST_EXISTS:{dst}")
            shutil.move(str(src), str(dst))
            if not dst.is_file() or _sha256(dst) != str(item.get("sha256") or ""):
                raise IOError(f"QUARANTINE_POST_MOVE_HASH_MISMATCH:{rel}")
            moved.append({
                "path": rel,
                "source": str(src),
                "quarantine_path": str(dst),
                "bytes": int(item.get("bytes") or 0),
                "sha256": str(item.get("sha256") or ""),
                "tier": str(item.get("tier") or ""),
                "restored": False,
            })
    except Exception as exc:
        rollback_errors: list[str] = []
        for row in reversed(moved):
            src = pathlib.Path(row["source"]); dst = pathlib.Path(row["quarantine_path"])
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and not src.exists():
                    shutil.move(str(dst), str(src))
            except Exception as rb_exc:
                rollback_errors.append(f"{row['path']}:{type(rb_exc).__name__}:{rb_exc}")
        return {"status": "FAIL", "reason": f"APPLY_FAILED:{type(exc).__name__}:{exc}", "rollback_errors": rollback_errors, "deletion_authorized": False}

    tx = {
        "format": TX_FORMAT,
        "status": "QUARANTINED",
        "transaction_id": tx_id,
        "created_at_epoch": int(time.time()),
        "project_root": str(project),
        "client_root": str(client),
        "plan": str(plan_file),
        "plan_sha256": _sha256(plan_file),
        "moved_count": len(moved),
        "moved_bytes": sum(int(x.get("bytes") or 0) for x in moved),
        "items": moved,
        "delete_authorized": False,
        "restore_available": True,
    }
    manifest = tx_dir / "transaction.json"
    manifest.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pointer = project / "pt_build" / "quarantine_store" / "latest_transaction.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(manifest) + "\n", encoding="utf-8")
    tx["transaction"] = str(manifest)
    tx["deletion_authorized"] = False
    return tx


def apply_q1_component_quarantine(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    *,
    component_id: str,
    plan_path: str | pathlib.Path | None = None,
    confirm: str = "",
) -> dict[str, Any]:
    if confirm != Q1_COMPONENT_CONFIRM:
        return {"status": "REFUSED", "reason": f"CONFIRM_REQUIRED:{Q1_COMPONENT_CONFIRM}", "deletion_authorized": False}
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    cid = str(component_id or "").strip().upper()
    if not cid.startswith("URC-"):
        return {"status": "REFUSED", "reason": "EXACT_URC_COMPONENT_REQUIRED", "deletion_authorized": False}
    plan_file = pathlib.Path(plan_path).resolve() if plan_path else _default_plan(project)
    plan = _load_json(plan_file)
    if plan.get("format") != PLAN_FORMAT or plan.get("status") != "PASS":
        return {"status": "REFUSED", "reason": "VALID_V2_QUARANTINE_PLAN_REQUIRED", "plan": str(plan_file), "deletion_authorized": False}
    if pathlib.Path(str(plan.get("client_root") or "")).resolve() != client:
        return {"status": "REFUSED", "reason": "CLIENT_ROOT_DIFFERS_FROM_PLAN", "deletion_authorized": False}
    retention_file = pathlib.Path(str(plan.get("retention_report") or ""))
    assets_file = pathlib.Path(str(plan.get("retention_assets_tsv") or ""))
    if not retention_file.is_file() or _sha256(retention_file) != str(plan.get("retention_report_sha256") or ""):
        return {"status": "REFUSED", "reason": "RETENTION_REPORT_CHANGED_REBUILD_PLAN", "deletion_authorized": False}
    if not assets_file.is_file() or _sha256(assets_file) != str(plan.get("retention_assets_sha256") or ""):
        return {"status": "REFUSED", "reason": "RETENTION_ASSETS_CHANGED_REBUILD_PLAN", "deletion_authorized": False}

    matches = [x for x in (plan.get("q1_components") or []) if str(x.get("component_id") or "").upper() == cid]
    if len(matches) != 1:
        return {"status": "REFUSED", "reason": "COMPONENT_NOT_FOUND_IN_PLAN", "component_id": cid, "deletion_authorized": False}
    comp = matches[0]
    if not bool(comp.get("manual_quarantine_eligible")):
        return {
            "status": "REFUSED", "reason": "COMPONENT_NOT_MANUAL_QUARANTINE_ELIGIBLE",
            "component_id": cid, "blockers": comp.get("manual_quarantine_blockers") or [], "deletion_authorized": False,
        }
    if str(comp.get("review_band") or "").upper() != "A":
        return {"status": "REFUSED", "reason": "COMPONENT_REVIEW_BAND_NOT_A", "component_id": cid, "deletion_authorized": False}

    rows = _load_tsv(assets_file)
    members = [x for x in rows if str(x.get("component_id") or "").upper() == cid]
    manifest = list(comp.get("member_manifest") or [])
    if not members or len(members) != int(comp.get("size") or 0) or len(manifest) != len(members):
        return {"status": "REFUSED", "reason": "COMPONENT_MEMBERSHIP_CHANGED_REBUILD_PLAN", "component_id": cid, "deletion_authorized": False}
    row_paths = {_norm(x.get("path") or "").casefold() for x in members}
    manifest_paths = {_norm(x.get("path") or "").casefold() for x in manifest}
    if row_paths != manifest_paths:
        return {"status": "REFUSED", "reason": "COMPONENT_MEMBER_MANIFEST_MISMATCH", "component_id": cid, "deletion_authorized": False}
    for row in members:
        rel = _norm(row.get("path") or "")
        if str(row.get("state") or "") != "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE":
            return {"status": "REFUSED", "reason": f"UNSAFE_MEMBER_STATE:{rel}", "component_id": cid, "deletion_authorized": False}
        if not _bool(row.get("graph_linked")) or _bool(row.get("root_reachable")):
            return {"status": "REFUSED", "reason": f"UNSAFE_MEMBER_REACHABILITY:{rel}", "component_id": cid, "deletion_authorized": False}
        if str(row.get("entity_bundle") or "").strip():
            return {"status": "REFUSED", "reason": f"ENTITY_BUNDLE_MEMBER_PRESENT:{rel}", "component_id": cid, "deletion_authorized": False}
        if str(row.get("evidence") or "").strip() not in {"", "CONTRACT_GRAPH_EDGE"}:
            return {"status": "REFUSED", "reason": f"POSITIVE_EVIDENCE_MEMBER_PRESENT:{rel}", "component_id": cid, "deletion_authorized": False}

    prepared: list[tuple[dict[str, Any], pathlib.Path]] = []
    for item in manifest:
        rel = _norm(item.get("path") or "")
        src = _safe_client_path(client, rel)
        if not src.is_file() or src.is_symlink():
            return {"status": "REFUSED", "reason": f"Q1_SOURCE_MISSING_OR_UNSAFE:{rel}", "component_id": cid, "deletion_authorized": False}
        if src.stat().st_size != int(item.get("bytes") or -1) or _sha256(src) != str(item.get("sha256") or ""):
            return {"status": "REFUSED", "reason": f"Q1_SOURCE_CHANGED_REBUILD_PLAN:{rel}", "component_id": cid, "deletion_authorized": False}
        prepared.append((item, src))

    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    tx_id = f"QTN-Q1-{cid}-{stamp}-{os.getpid()}"
    tx_dir = project / "pt_build" / "quarantine_store" / tx_id
    files_dir = tx_dir / "files"
    tx_dir.mkdir(parents=True, exist_ok=False)
    moved: list[dict[str, Any]] = []
    try:
        for item, src in prepared:
            rel = _norm(item.get("path") or "")
            dst = files_dir / pathlib.PurePosixPath(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                raise FileExistsError(f"QUARANTINE_DEST_EXISTS:{dst}")
            shutil.move(str(src), str(dst))
            if not dst.is_file() or _sha256(dst) != str(item.get("sha256") or ""):
                raise IOError(f"QUARANTINE_POST_MOVE_HASH_MISMATCH:{rel}")
            moved.append({
                "path": rel, "source": str(src), "quarantine_path": str(dst),
                "bytes": int(item.get("bytes") or 0), "sha256": str(item.get("sha256") or ""),
                "tier": "Q1_MANUAL_COMPONENT_QUARANTINE", "component_id": cid, "restored": False,
            })
    except Exception as exc:
        rollback_errors: list[str] = []
        for row in reversed(moved):
            src = pathlib.Path(row["source"]); dst = pathlib.Path(row["quarantine_path"])
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and not src.exists():
                    shutil.move(str(dst), str(src))
            except Exception as rb_exc:
                rollback_errors.append(f"{row['path']}:{type(rb_exc).__name__}:{rb_exc}")
        return {"status": "FAIL", "reason": f"Q1_APPLY_FAILED:{type(exc).__name__}:{exc}", "rollback_errors": rollback_errors, "component_id": cid, "deletion_authorized": False}

    tx = {
        "format": TX_FORMAT, "status": "QUARANTINED", "transaction_id": tx_id,
        "created_at_epoch": int(time.time()), "project_root": str(project), "client_root": str(client),
        "plan": str(plan_file), "plan_sha256": _sha256(plan_file),
        "scope": "Q1_COMPONENT", "component_id": cid,
        "review_score": int(comp.get("review_score") or 0), "review_band": str(comp.get("review_band") or ""),
        "manual_authorization": "EXPLICIT_COMPONENT_CONFIRMATION",
        "moved_count": len(moved), "moved_bytes": sum(int(x.get("bytes") or 0) for x in moved),
        "items": moved, "delete_authorized": False, "restore_available": True,
    }
    manifest_file = tx_dir / "transaction.json"
    manifest_file.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pointer = project / "pt_build" / "quarantine_store" / "latest_transaction.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(manifest_file) + "\n", encoding="utf-8")
    tx["transaction"] = str(manifest_file)
    tx["deletion_authorized"] = False
    return tx


def restore_quarantine_transaction(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    *,
    transaction_path: str | pathlib.Path | None = None,
    confirm: str = "",
) -> dict[str, Any]:
    if confirm != RESTORE_CONFIRM:
        return {"status": "REFUSED", "reason": f"CONFIRM_REQUIRED:{RESTORE_CONFIRM}", "deletion_authorized": False}
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    tx_file = pathlib.Path(transaction_path).resolve() if transaction_path else _latest_transaction_path(project)
    if tx_file is None or not tx_file.is_file():
        return {"status": "REFUSED", "reason": "QUARANTINE_TRANSACTION_REQUIRED", "deletion_authorized": False}
    tx = _load_json(tx_file)
    if tx.get("format") != TX_FORMAT:
        return {"status": "REFUSED", "reason": "INVALID_QUARANTINE_TRANSACTION", "deletion_authorized": False}
    if pathlib.Path(str(tx.get("client_root") or "")).resolve() != client:
        return {"status": "REFUSED", "reason": "CLIENT_ROOT_DIFFERS_FROM_TRANSACTION", "deletion_authorized": False}

    prepared: list[tuple[dict[str, Any], pathlib.Path, pathlib.Path]] = []
    for item in tx.get("items", []) or []:
        rel = _norm(item.get("path") or "")
        dst = _safe_client_path(client, rel)
        src = pathlib.Path(str(item.get("quarantine_path") or "")).resolve()
        if not src.is_file() or _sha256(src) != str(item.get("sha256") or ""):
            return {"status": "REFUSED", "reason": f"QUARANTINE_FILE_MISSING_OR_CHANGED:{rel}", "deletion_authorized": False}
        if dst.exists():
            return {"status": "REFUSED", "reason": f"RESTORE_TARGET_EXISTS:{rel}", "deletion_authorized": False}
        prepared.append((item, src, dst))

    restored: list[dict[str, Any]] = []
    try:
        for item, src, dst in prepared:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            if not dst.is_file() or _sha256(dst) != str(item.get("sha256") or ""):
                raise IOError(f"RESTORE_POST_MOVE_HASH_MISMATCH:{item.get('path')}")
            restored.append(item)
    except Exception as exc:
        rollback_errors: list[str] = []
        for item in reversed(restored):
            dst = _safe_client_path(client, _norm(item.get("path") or ""))
            src = pathlib.Path(str(item.get("quarantine_path") or "")).resolve()
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and not src.exists():
                    shutil.move(str(dst), str(src))
            except Exception as rb_exc:
                rollback_errors.append(f"{item.get('path')}:{type(rb_exc).__name__}:{rb_exc}")
        return {"status": "FAIL", "reason": f"RESTORE_FAILED:{type(exc).__name__}:{exc}", "rollback_errors": rollback_errors, "deletion_authorized": False}

    tx["status"] = "RESTORED"
    tx["restored_at_epoch"] = int(time.time())
    tx["restored_count"] = len(restored)
    tx["restore_available"] = False
    for row in tx.get("items", []) or []:
        row["restored"] = True
    tx_file.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tx["transaction"] = str(tx_file)
    tx["deletion_authorized"] = False
    return tx


def quarantine_status(project_root: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    plan_file = _default_plan(project)
    plan = _load_json(plan_file)
    latest = _latest_transaction_path(project)
    tx = _load_json(latest) if latest and latest.is_file() else {}
    return {
        "status": "PASS",
        "plan": str(plan_file) if plan_file.is_file() else "",
        "plan_status": plan.get("status") or "NOT_RUN",
        "q0_count": int(plan.get("q0_count") or 0),
        "q0_bytes": int(plan.get("q0_bytes") or 0),
        "q1_component_count": int(plan.get("q1_component_count") or 0),
        "q1_priority_a_count": int(plan.get("q1_priority_a_count") or 0),
        "q1_priority_b_count": int(plan.get("q1_priority_b_count") or 0),
        "q1_priority_c_count": int(plan.get("q1_priority_c_count") or 0),
        "q1_blocked_component_count": int(plan.get("q1_blocked_component_count") or 0),
        "latest_transaction": str(latest) if latest else "",
        "latest_transaction_status": tx.get("status") or "NONE",
        "latest_moved_count": int(tx.get("moved_count") or 0),
        "latest_scope": tx.get("scope") or ("Q0" if tx else ""),
        "latest_component_id": tx.get("component_id") or "",
        "restore_available": bool(tx.get("restore_available")),
        "deletion_authorized": False,
    }
