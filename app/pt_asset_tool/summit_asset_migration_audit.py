from __future__ import annotations

import csv
import json
import os
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from .cooked_texture_evidence import audit_cooked_texture_evidence, cooked_index
from .effect_runtime_coverage import audit_effect_runtime_coverage
from .source_catalog import SourceTree, iter_source_files, read_source_text, source_rel
from .source_evidence import ASSET_EXTENSIONS, _strip_c_comments, scan_source_evidence

CANONICAL_FORMAT = "PT_SUMMIT_CANONICAL_ASSET_RELATIONS_V1"
MIGRATION_FORMAT = "PT_SUMMIT_ASSET_MIGRATION_GAP_V1"

ASSET_SUFFIXES = {"." + x.casefold().lstrip(".") for x in ASSET_EXTENSIONS}
TEXTURE_SUFFIXES = {".bmp", ".tga", ".png", ".jpg", ".jpeg"}
NATIVE_TEXTURE_SUFFIXES = {".dds"}
CLIENT_PREFIXES = (
    "char/", "effect/", "image/", "field/", "wav/", "weapons/",
    "cselect/", "startimage/", "game/", "res/", "sound/", "ui/",
)
SERVER_PREFIXES = ("gameserver/", "dataserver/", "server/")
CLIENT_WRAPPER_PREFIXES = ("cliente/", "client/")
SERVER_WRAPPER_PREFIXES = ("servidor/",)

STRONG_KEY_TOKENS = (
    "runtime_path", "runtime_paths", "model_file", "model_path", "texture",
    "image", "icon", "effect", "sound", "audio", "music", "media_path",
    "asset", "stage_asset", "stage_file",
)
REVIEW_KEY_TOKENS = (
    "legacy_path", "linked_file", "logical_path", "json_path", "source_path",
    "source_file", "path",
)
UI_FILE_TOKENS = (
    "/ui/", "interface", "messagebox", "questwindow", "window", "dialog",
    "charstatus", "help/", "opening/", "sininterface", "sinmsg", "sinhelp",
)

_C_STRING_RE = re.compile(r'"(?P<body>(?:\\.|[^"\\])*)"')
_ALPHA_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) >= 2 and text[1] == ":":
        text = text[2:].lstrip("/")
    return text.lstrip("./")


def _json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_tsv(path: pathlib.Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _walk_client(root: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for base, dirs, files in os.walk(root):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            p = pathlib.Path(base) / name
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            out.setdefault(rel.casefold(), rel)
    return out


def _path_side_and_client_rel(raw: str) -> tuple[str, str]:
    rel = _norm(raw)
    low = rel.casefold()
    for prefix in CLIENT_WRAPPER_PREFIXES:
        if low.startswith(prefix):
            return "CLIENT", rel[len(prefix):]
    for prefix in SERVER_WRAPPER_PREFIXES:
        if low.startswith(prefix):
            return "SERVER", rel[len(prefix):]
    if low.startswith(SERVER_PREFIXES):
        return "SERVER", rel
    if low.startswith(CLIENT_PREFIXES):
        return "CLIENT", rel
    # Absolute/embedded legacy paths occasionally carry a useful client root.
    for marker in CLIENT_PREFIXES:
        pos = low.find(marker)
        if pos > 0:
            return "CLIENT", rel[pos:]
    for marker in SERVER_PREFIXES:
        pos = low.find(marker)
        if pos > 0:
            return "SERVER", rel[pos:]
    return "UNKNOWN", rel


def _looks_asset(value: str) -> bool:
    rel = _norm(value)
    if not rel or len(rel) > 1024:
        return False
    suffix = pathlib.PurePosixPath(rel).suffix.casefold()
    if suffix in ASSET_SUFFIXES:
        return True
    low = rel.casefold()
    return low.startswith(CLIENT_PREFIXES + SERVER_PREFIXES + CLIENT_WRAPPER_PREFIXES + SERVER_WRAPPER_PREFIXES)


def _json_pointer(parts: list[str]) -> str:
    return "/" + "/".join(str(x).replace("~", "~0").replace("/", "~1") for x in parts)


def _doc_id(data: Any, rel: str) -> str:
    if isinstance(data, dict):
        for key in ("canonical_id", "resource_id", "item_id", "monster_id", "npc_id", "map_id", "id"):
            value = data.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    return rel


def _strength_for(json_file: pathlib.Path, pointer_parts: list[str], side: str) -> tuple[str, str]:
    name = json_file.name.casefold()
    key = pointer_parts[-1].casefold() if pointer_parts else ""
    pointer = "/".join(x.casefold() for x in pointer_parts)
    if name == "report.json" or "/provenance/" in ("/" + pointer + "/"):
        return "METADATA", "REPORT_OR_PROVENANCE"
    if side != "CLIENT":
        return "REVIEW", "NON_CLIENT_REFERENCE"
    if any(token in key for token in STRONG_KEY_TOKENS) or any(token in pointer for token in STRONG_KEY_TOKENS):
        return "STRONG", "CANONICAL_RUNTIME_FIELD"
    if any(token in key for token in REVIEW_KEY_TOKENS):
        return "REVIEW", "CANONICAL_PATH_EVIDENCE"
    if name == "index.json":
        return "REVIEW", "CANONICAL_INDEX_EVIDENCE"
    return "REVIEW", "CANONICAL_ASSET_STRING"


def _iter_strings(value: Any, parts: list[str] | None = None):
    parts = parts or []
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_strings(child, [*parts, str(key)])
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _iter_strings(child, [*parts, str(idx)])
    elif isinstance(value, str):
        yield parts, value


def audit_canonical_asset_relations(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    source_root: str | pathlib.Path,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    source = pathlib.Path(source_root).resolve()
    canonical = source / "Content" / "canonical"
    out_dir = project / "pt_build" / "summit_asset_migration"
    out_dir.mkdir(parents=True, exist_ok=True)
    client_idx = _walk_client(client)

    relations: list[dict[str, Any]] = []
    strong: dict[str, list[str]] = defaultdict(list)
    review: dict[str, list[str]] = defaultdict(list)
    files_scanned = 0
    json_errors: list[str] = []

    if canonical.is_dir():
        for path in sorted(canonical.rglob("*.json"), key=lambda p: p.as_posix().casefold()):
            files_scanned += 1
            data = _json(path)
            if data is None:
                json_errors.append(path.relative_to(source).as_posix())
                continue
            rel_doc = path.relative_to(source).as_posix()
            owner = _doc_id(data, rel_doc)
            for parts, raw in _iter_strings(data):
                if not _looks_asset(raw):
                    continue
                side, client_rel = _path_side_and_client_rel(raw)
                suffix = pathlib.PurePosixPath(client_rel).suffix.casefold()
                strength, reason = _strength_for(path, parts, side)
                resolved = client_idx.get(client_rel.casefold(), "") if side == "CLIENT" else ""
                row = {
                    "canonical_document": rel_doc,
                    "canonical_id": owner,
                    "json_pointer": _json_pointer(parts),
                    "raw_value": raw,
                    "side": side,
                    "client_path": client_rel if side == "CLIENT" else "",
                    "extension": suffix,
                    "strength": strength,
                    "reason": reason,
                    "client_exists": bool(resolved),
                    "resolved_client_path": resolved,
                }
                relations.append(row)
                if side == "CLIENT" and strength == "STRONG" and client_rel:
                    evidence = f"SUMMIT_CANONICAL:{owner}:{row['json_pointer']}"
                    if evidence not in strong[client_rel.casefold()]:
                        strong[client_rel.casefold()].append(evidence)
                elif side == "CLIENT" and client_rel:
                    evidence = f"SUMMIT_CANONICAL_REVIEW:{owner}:{row['json_pointer']}"
                    if evidence not in review[client_rel.casefold()]:
                        review[client_rel.casefold()].append(evidence)

    relations.sort(key=lambda x: (x["side"], x["client_path"].casefold(), x["canonical_document"], x["json_pointer"]))
    tsv = out_dir / "canonical_asset_relations.tsv"
    _write_tsv(tsv, relations, [
        "canonical_document", "canonical_id", "json_pointer", "raw_value", "side",
        "client_path", "extension", "strength", "reason", "client_exists", "resolved_client_path",
    ])
    roots = [
        {"path": client_idx.get(key, key), "evidence": sorted(values)}
        for key, values in sorted(strong.items())
    ]
    review_roots = [
        {"path": client_idx.get(key, key), "evidence": sorted(values)}
        for key, values in sorted(review.items())
    ]
    counts = Counter(x["strength"] for x in relations)
    sides = Counter(x["side"] for x in relations)
    result = {
        "format": CANONICAL_FORMAT,
        "status": "PASS" if canonical.is_dir() and not json_errors else ("REVIEW_REQUIRED" if canonical.is_dir() else "NOT_PRESENT"),
        "source_root": str(source),
        "canonical_root": str(canonical),
        "client_root": str(client),
        "canonical_present": canonical.is_dir(),
        "json_files_scanned": files_scanned,
        "json_error_count": len(json_errors),
        "json_errors": json_errors,
        "relation_count": len(relations),
        "side_counts": dict(sorted(sides.items())),
        "strength_counts": dict(sorted(counts.items())),
        "strong_client_root_count": len(roots),
        "review_client_path_count": len(review_roots),
        "strong_client_roots": roots,
        "review_client_paths": review_roots,
        "relations_tsv": str(tsv),
        "policy": {
            "canonical_runtime_fields_are_strong_roots": True,
            "canonical_report_and_provenance_are_not_roots": True,
            "server_paths_do_not_become_client_roots": True,
            "unknown_relative_paths_are_review_only": True,
            "deletion_authorized": False,
        },
    }
    report = out_dir / "canonical_asset_relations.json"
    result["report"] = str(report)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _is_ui_source(rel: str) -> bool:
    low = "/" + rel.replace("\\", "/").casefold()
    return any(token in low for token in UI_FILE_TOKENS)


def _human_text_candidate(value: str) -> bool:
    text = value.strip()
    if len(text) < 4 or len(text) > 300:
        return False
    if _looks_asset(text):
        return False
    if text.startswith(("http://", "https://", "SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
        return False
    alpha = sum(1 for ch in text if _ALPHA_RE.match(ch))
    if alpha < 4:
        return False
    if text.isupper() and " " not in text and len(text) < 64:
        return False
    # Identifiers / printf-debug tags are review noise.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:.-]*", text) and " " not in text:
        return False
    return True


def _ui_text_rows(tree: SourceTree) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in iter_source_files(tree.root):
        rel = source_rel(tree.root, path)
        if not _is_ui_source(rel):
            continue
        try:
            raw, _enc = read_source_text(path)
        except Exception:
            continue
        text = _strip_c_comments(raw)
        for match in _C_STRING_RE.finditer(text):
            value = match.group("body")
            try:
                value = bytes(value, "utf-8").decode("unicode_escape")
            except Exception:
                pass
            if not _human_text_candidate(value):
                continue
            rows.append({
                "source_file": rel,
                "source_line": text.count("\n", 0, match.start()) + 1,
                "text": value.replace("\r", "\\r").replace("\n", "\\n"),
                "has_format_token": "%" in value or "{" in value,
                "state": "UI_TEXT_REVIEW",
                "recommended_target": "Content/canonical/text/localization_or_ui_config",
            })
    rows.sort(key=lambda x: (x["source_file"].casefold(), int(x["source_line"]), x["text"]))
    return rows


def _resolve_runtime_alias(path: str, client_idx: dict[str, str]) -> tuple[str, str]:
    rel = _norm(path)
    key = rel.casefold()
    exact = client_idx.get(key)
    if exact:
        return exact, "EXACT"
    pp = pathlib.PurePosixPath(rel)
    if pp.suffix.casefold() == ".ini" and key.startswith("char/"):
        inx = pp.with_suffix(".inx").as_posix()
        if inx.casefold() in client_idx:
            return client_idx[inx.casefold()], "CHAR_INI_TO_INX"
    if pp.suffix.casefold() == ".ase":
        smd = pp.with_suffix(".smd").as_posix()
        if smd.casefold() in client_idx:
            return client_idx[smd.casefold()], "ASE_TO_SMD"
    return rel, "MISSING"


def _scope(source_file: str, path: str) -> str:
    low = (source_file + " " + path).casefold()
    if "effect/" in low or "/effects/" in low or "particle" in low:
        return "EFFECT"
    if "/ui/" in low or "sininterface" in low or "messagebox" in low or "questwindow" in low:
        return "UI"
    if path.casefold().startswith("wav/") or "/audio/" in low:
        return "AUDIO"
    if path.casefold().startswith("char/"):
        return "CHARACTER_MODEL"
    if path.casefold().startswith("field/"):
        return "FIELD"
    return "GENERAL"


def _cook_action(path: str, cook: dict[str, Any] | None) -> tuple[str, str]:
    ext = pathlib.PurePosixPath(path).suffix.casefold()
    cook = cook or {}
    status = str(cook.get("status") or "").casefold()
    if ext in TEXTURE_SUFFIXES:
        if status in {"cooked", "up-to-date"}:
            return "DDS_COOK_OK", status
        if status == "skipped":
            return "DDS_POLICY_SKIPPED_REVIEW", status
        if status == "error":
            return "DDS_COOK_FAILURE", status
        return "DDS_COOK_REQUIRED", status or "not-in-manifest"
    if ext in NATIVE_TEXTURE_SUFFIXES:
        return "COPY_AS_IS_NATIVE_DDS", "native"
    if ext in ASSET_SUFFIXES:
        return "COPY_AS_IS_TO_COOKED_RUNTIME", "non-texture-runtime-asset"
    return "REVIEW_COOK_POLICY", "unknown"


def audit_summit_asset_migration_gap(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    current_tree: SourceTree,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    out_dir = project / "pt_build" / "summit_asset_migration"
    out_dir.mkdir(parents=True, exist_ok=True)
    client_idx = _walk_client(client)

    canonical = audit_canonical_asset_relations(project, client, current_tree.root)
    canonical_strong = {
        _norm(row.get("path") or "").casefold(): row
        for row in canonical.get("strong_client_roots", []) if _norm(row.get("path") or "")
    }
    canonical_review = {
        _norm(row.get("path") or "").casefold(): row
        for row in canonical.get("review_client_paths", []) if _norm(row.get("path") or "")
    }

    source_ev = scan_source_evidence(current_tree)
    effect_runtime = audit_effect_runtime_coverage(project, client, current_tree)
    effect_strong = {
        _norm(row.get("path") or "").casefold(): row
        for row in effect_runtime.get("roots", []) if _norm(row.get("path") or "")
    }
    cooked_report = audit_cooked_texture_evidence(project, client)
    cooked = cooked_index(cooked_report)

    source_rows: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    runtime_roots: dict[str, dict[str, Any]] = {}
    for row in source_ev.get("literal_refs", []):
        raw = _norm(row.get("value") or "")
        if not raw:
            continue
        side, candidate = _path_side_and_client_rel(raw)
        if side == "SERVER":
            continue
        resolved, resolution = _resolve_runtime_alias(candidate, client_idx)
        key = _norm(resolved).casefold()
        covered = key in canonical_strong
        review_covered = key in canonical_review
        exists = key in client_idx or pathlib.Path(client / resolved).is_file()
        scope = _scope(str(row.get("source_file") or ""), resolved)
        effect_loader_root = key in effect_strong
        if covered:
            state = "CANONICAL_COVERED"
            priority = "P4"
        elif review_covered:
            state = "CANONICAL_REVIEW_ONLY"
            priority = "P2"
        elif exists:
            state = "SOURCE_ONLY_PRESENT"
            priority = "P1" if scope in {"EFFECT", "UI", "AUDIO", "CHARACTER_MODEL"} else "P2"
        else:
            state = "SOURCE_ONLY_MISSING"
            priority = "P0" if effect_loader_root or scope == "EFFECT" else "P1"
        if effect_loader_root and state != "CANONICAL_COVERED":
            priority = "P0" if not exists else "P1"
        cook_action, cook_state = _cook_action(resolved, cooked.get(key))
        record = {
            "source_file": row.get("source_file") or "",
            "source_line": row.get("line") or "",
            "raw_literal": raw,
            "client_path": resolved,
            "resolution": resolution,
            "scope": scope,
            "state": state,
            "priority": priority,
            "client_exists": exists,
            "effect_loader_root": effect_loader_root,
            "canonical_strong": covered,
            "canonical_review": review_covered,
            "cook_action": cook_action,
            "cook_state": cook_state,
        }
        source_rows.append(record)
        if state != "CANONICAL_COVERED":
            queue.append(record)
        if exists:
            previous = runtime_roots.get(key)
            if previous is None or str(priority) < str(previous.get("priority")):
                runtime_roots[key] = record

    # Canonical strong roots must also be present and covered by distribution cook/package.
    for key, row in canonical_strong.items():
        path = _norm(row.get("path") or "")
        resolved, resolution = _resolve_runtime_alias(path, client_idx)
        rkey = resolved.casefold()
        exists = rkey in client_idx
        cook_action, cook_state = _cook_action(resolved, cooked.get(rkey))
        if not exists:
            queue.append({
                "source_file": "",
                "source_line": "",
                "raw_literal": path,
                "client_path": resolved,
                "resolution": resolution,
                "scope": _scope("", resolved),
                "state": "CANONICAL_RUNTIME_ASSET_MISSING",
                "priority": "P0",
                "client_exists": False,
                "effect_loader_root": rkey in effect_strong,
                "canonical_strong": True,
                "canonical_review": False,
                "cook_action": cook_action,
                "cook_state": cook_state,
            })
        if exists and rkey not in runtime_roots:
            runtime_roots[rkey] = {
                "client_path": resolved,
                "priority": "P3",
                "scope": _scope("", resolved),
                "state": "CANONICAL_ONLY_RUNTIME_ROOT",
                "cook_action": cook_action,
                "cook_state": cook_state,
                "canonical_strong": True,
            }

    source_rows.sort(key=lambda x: (x["priority"], x["state"], x["source_file"].casefold(), int(x["source_line"] or 0)))
    queue.sort(key=lambda x: (x["priority"], x["state"], x["client_path"].casefold(), x["source_file"].casefold()))

    source_tsv = out_dir / "source_asset_literals.tsv"
    migration_tsv = out_dir / "migration_queue.tsv"
    cols = [
        "priority", "state", "scope", "client_path", "client_exists", "resolution",
        "effect_loader_root", "canonical_strong", "canonical_review", "cook_action", "cook_state",
        "source_file", "source_line", "raw_literal",
    ]
    _write_tsv(source_tsv, source_rows, cols)
    _write_tsv(migration_tsv, queue, cols)

    ui_rows = _ui_text_rows(current_tree)
    ui_tsv = out_dir / "ui_text_candidates.tsv"
    _write_tsv(ui_tsv, ui_rows, ["source_file", "source_line", "text", "has_format_token", "state", "recommended_target"])

    cook_rows = []
    for key, row in sorted(runtime_roots.items()):
        path = _norm(row.get("client_path") or key)
        cook_action, cook_state = _cook_action(path, cooked.get(key))
        cook_rows.append({
            "client_path": path,
            "scope": row.get("scope") or _scope("", path),
            "root_state": row.get("state") or "RUNTIME_ROOT",
            "canonical_strong": bool(row.get("canonical_strong")),
            "cook_action": cook_action,
            "cook_state": cook_state,
            "distribution_required": True,
        })
    cook_tsv = out_dir / "runtime_cook_plan.tsv"
    _write_tsv(cook_tsv, cook_rows, [
        "client_path", "scope", "root_state", "canonical_strong", "cook_action", "cook_state", "distribution_required",
    ])
    cook_json = out_dir / "runtime_cook_plan.json"
    cook_json.write_text(json.dumps({
        "format": "PT_SUMMIT_RUNTIME_COOK_PLAN_V1",
        "status": "PASS",
        "entries": cook_rows,
        "policy": {
            "textures_require_dds_or_explicit_skip_review": True,
            "non_texture_runtime_assets_copy_as_is": True,
            "source_only_roots_remain_distribution_protected_until_migrated": True,
            "missing_runtime_assets_block_release": True,
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_counts = Counter(str(x["state"]) for x in source_rows)
    priority_counts = Counter(str(x["priority"]) for x in queue)
    cook_counts = Counter(str(x["cook_action"]) for x in cook_rows)
    result = {
        "format": MIGRATION_FORMAT,
        "status": "PASS",
        "state": "REVIEW_REQUIRED" if queue else "CANONICAL_COVERAGE_COMPLETE",
        "source_root": str(current_tree.root),
        "client_root": str(client),
        "canonical_report": canonical.get("report"),
        "effect_runtime_report": effect_runtime.get("report"),
        "cooked_texture_report": cooked_report.get("report"),
        "source_asset_literal_count": len(source_rows),
        "source_state_counts": dict(sorted(state_counts.items())),
        "migration_queue_count": len(queue),
        "migration_priority_counts": dict(sorted(priority_counts.items())),
        "ui_text_candidate_count": len(ui_rows),
        "runtime_cook_root_count": len(cook_rows),
        "runtime_cook_action_counts": dict(sorted(cook_counts.items())),
        "source_asset_literals_tsv": str(source_tsv),
        "migration_queue_tsv": str(migration_tsv),
        "ui_text_candidates_tsv": str(ui_tsv),
        "runtime_cook_plan_tsv": str(cook_tsv),
        "runtime_cook_plan_json": str(cook_json),
        "release_blockers": {
            "missing_runtime_assets": sum(1 for x in queue if x["state"] in {"SOURCE_ONLY_MISSING", "CANONICAL_RUNTIME_ASSET_MISSING"}),
            "dds_cook_failures": sum(1 for x in cook_rows if x["cook_action"] == "DDS_COOK_FAILURE"),
        },
        "policy": {
            "source_only_assets_are_protected_not_orphans": True,
            "canonical_strong_paths_are_retention_roots": True,
            "ui_text_is_review_only_not_auto_migrated": True,
            "quarantine_requires_existing_retention_gates": True,
            "deletion_authorized": False,
        },
    }
    report = out_dir / "result.json"
    result["report"] = str(report)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
