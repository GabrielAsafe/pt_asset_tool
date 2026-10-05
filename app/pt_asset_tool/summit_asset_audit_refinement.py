from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import pathlib
import re
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any, Iterable

FORMAT = "PT_SUMMIT_ASSET_AUDIT_REFINEMENT_V1"

PRINTF_RE = re.compile(
    r"%(?:\d+\$)?[-+#0 'I]*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcspn]"
)
SOURCE_EXT_RE = re.compile(r"(?i)(?:^|[/\\])[^/\\]+\.(?:h|hpp|hh|hxx|c|cc|cpp|cxx|inl|ipp)$")
INCLUDE_RE = re.compile(r"^\s*#\s*include\b")
TEST_RE = re.compile(r"(^|/)tests?(/|$)", re.I)
GLOB_RE = re.compile(r"[*?]")
ASSIGN_LITERAL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*\"[^\"]+\"")

ASSA_TOKENS = ("AssaSearchRes", "SetAssaEffect")
HO_SEQUENCE_TOKENS = (
    "StartBillRect(", "StartBillRectPrimitive(", "StartDestPath(", "StartPath(", "StartPathTri("
)


def _norm(value: str | None) -> str:
    return (value or "").replace("\\", "/").strip().lstrip("/").casefold()


def _runtime_norm(value: str | None) -> str:
    normalized = _norm(value)
    for prefix in ("cliente/", "servidor/"):
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
    return normalized


def _basename(value: str | None) -> str:
    return PurePosixPath(_norm(value)).name


def _read_tsv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _write_tsv(path: pathlib.Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _load_source_lines(source_root: pathlib.Path | None, rel: str, cache: dict[str, list[str]]) -> list[str]:
    if source_root is None or not rel:
        return []
    if rel not in cache:
        path = source_root / rel
        try:
            cache[rel] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            cache[rel] = []
    return cache[rel]


def _source_context(
    source_root: pathlib.Path | None,
    rel: str,
    line_no: str,
    cache: dict[str, list[str]],
    *,
    radius: int = 2,
) -> tuple[str, str, list[str]]:
    lines = _load_source_lines(source_root, rel, cache)
    try:
        index = int(line_no) - 1
    except (TypeError, ValueError):
        return "", "", lines
    if not (0 <= index < len(lines)):
        return "", "", lines
    lo = max(0, index - radius)
    hi = min(len(lines), index + radius + 1)
    return lines[index], "\n".join(lines[lo:hi]), lines


def _json_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _json_string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_string_values(child)


def build_canonical_owner_index(canonical_root: pathlib.Path | None) -> dict[str, list[str]]:
    """Index exact string-valued canonical references by normalized path.

    Exact ownership is evidence only. It never proves that a physical runtime
    file exists and therefore never clears a missing-runtime state by itself.
    """
    owners: dict[str, set[str]] = defaultdict(set)
    if canonical_root is None or not canonical_root.is_dir():
        return {}
    for path in sorted(canonical_root.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        rel = path.relative_to(canonical_root).as_posix()
        for value in _json_string_values(data):
            normalized = _norm(value)
            if normalized:
                owners[normalized].add(rel)
    return {key: sorted(values) for key, values in owners.items()}


def build_canonical_text_runtime_index(canonical_root: pathlib.Path | None) -> dict[str, list[dict[str, Any]]]:
    """Index canonical text resources by exact runtime alias.

    Payload integrity is checked against legacy_size/legacy_sha256 when present.
    The resulting evidence means the legacy bytes are reconstructable/packable;
    it does not prove that text_resources.sres is deployed in a target client.
    """
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if canonical_root is None:
        return {}
    root = canonical_root / "text" / "resources"
    if not root.is_dir():
        return {}
    for path in sorted(root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or doc.get("schema") != "summit.canonical-text-resource/v1":
            continue
        compat = doc.get("compatibility") if isinstance(doc.get("compatibility"), dict) else {}
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        payload_b64 = str(compat.get("legacy_payload_base64") or "")
        payload_valid = False
        payload_size = 0
        payload_sha = ""
        if payload_b64:
            try:
                raw = base64.b64decode(payload_b64, validate=True)
                payload_size = len(raw)
                payload_sha = hashlib.sha256(raw).hexdigest()
                expected_size = source.get("legacy_size")
                expected_sha = str(source.get("legacy_sha256") or "").casefold()
                payload_valid = (
                    (expected_size in (None, "") or int(expected_size) == payload_size)
                    and (not expected_sha or expected_sha == payload_sha)
                )
            except (ValueError, TypeError, base64.binascii.Error):
                payload_valid = False
        evidence = {
            "owner_file": path.relative_to(canonical_root).as_posix(),
            "id": str(doc.get("id") or ""),
            "kind": str(doc.get("kind") or ""),
            "payload_valid": payload_valid,
            "payload_size": payload_size,
            "payload_sha256": payload_sha,
        }
        for runtime_path in doc.get("runtime_paths") or []:
            if isinstance(runtime_path, str) and runtime_path.strip():
                result[_runtime_norm(runtime_path)].append(evidence)
    return dict(result)


def build_model_config_index(canonical_root: pathlib.Path | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if canonical_root is None:
        return result
    root = canonical_root / "model_configs" / "models"
    if not root.is_dir():
        return result
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or doc.get("schema") != "summit.model-config/v1":
            continue
        logical = _runtime_norm(str(doc.get("logical_config") or ""))
        if not logical:
            continue
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        presence = doc.get("inventory_presence") if isinstance(doc.get("inventory_presence"), dict) else {}
        result[logical] = {
            "owner_file": path.relative_to(canonical_root).as_posix(),
            "id": str(doc.get("id") or ""),
            "source_status": str(source.get("status") or ""),
            "legacy_cache": _runtime_norm(str(doc.get("legacy_cache") or "")),
            "client_present": bool((presence.get("client") or {}).get("present")) if isinstance(presence.get("client"), dict) else False,
            "server_present": bool((presence.get("server") or {}).get("present")) if isinstance(presence.get("server"), dict) else False,
            "client_path": str((presence.get("client") or {}).get("path") or "") if isinstance(presence.get("client"), dict) else "",
            "server_path": str((presence.get("server") or {}).get("path") or "") if isinstance(presence.get("server"), dict) else "",
        }
    return result


def detect_text_pack_contract(source_root: pathlib.Path | None) -> dict[str, Any]:
    if source_root is None:
        return {"proven": False, "reason": "SOURCE_ROOT_NOT_PROVIDED"}
    runtime = source_root / "Shared/content/v1/text_resource/content/TextResourceRuntime.h"
    compiled = source_root / "Shared/content/v1/text_resource/content/CompiledTextResourceSource.h"
    compiler = source_root / "tools/content_port/compile_text_resources.py"
    quarantine = source_root / "tools/content_port/quarantine_legacy_runtime_content.py"

    def text(path: pathlib.Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    runtime_text = text(runtime)
    compiled_text = text(compiled)
    compiler_text = text(compiler)
    quarantine_text = text(quarantine)
    checks = {
        "runtime_pack_path": 'ResolveRuntimePackPath("text_resources.sres")' in runtime_text,
        "strict_mode": "TextResourceStrictMode(){ return true; }" in runtime_text.replace("\r", ""),
        "runtime_loads_pack_payload": "s->Load(path,bytes" in runtime_text.replace(" ", ""),
        "compiled_pack_magic": 'memcmp(p,"SRES",4)' in compiled_text.replace(" ", ""),
        "compiler_consumes_legacy_payload": "legacy_payload_base64" in compiler_text and "base64.b64decode" in compiler_text,
        "legacy_quarantine_requires_pack": "text_resources.sres" in quarantine_text and "validate_pack_presence" in quarantine_text,
    }
    return {
        "proven": all(checks.values()),
        "checks": checks,
        "runtime_header": str(runtime),
        "compiler": str(compiler),
        "quarantine_tool": str(quarantine),
    }


def _known_loader_class(raw_literal: str, line: str, context: str, state: str) -> str:
    if state != "SOURCE_ONLY_MISSING" or "/" in _norm(raw_literal):
        return ""
    probe = f"{line}\n{context}"
    if any(token in probe for token in ASSA_TOKENS):
        return "ASSA_RESOURCE_CATALOG_ALIAS"
    if any(token in probe for token in HO_SEQUENCE_TOKENS):
        return "HO_ANIMATION_SEQUENCE_ALIAS"
    if "primitiveMove->Start(" in probe:
        return "HO_ANIMATION_SEQUENCE_ALIAS_INDIRECT"
    return ""


def _obvious_scope(source_file: str, original_scope: str) -> tuple[str, str]:
    path = "/" + source_file.replace("\\", "/").casefold().strip("/") + "/"
    if "/systems/audio/" in path or "/shared/audio/" in path:
        return "AUDIO", "SOURCE_PATH_AUDIO_DOMAIN"
    return original_scope, ""


def _mirror_identity(source_file: str) -> tuple[str, str] | None:
    path = source_file.replace("\\", "/")
    lower = path.casefold()
    if lower.startswith("srcgame/src/"):
        rest = path[len("SrcGame/src/"):]
        rest = rest.replace("systems/localization/legacy_catalog/", "systems/localization/CATALOG/")
        return rest.casefold(), "CLIENT"
    if lower.startswith("srcserver/src/"):
        rest = path[len("SrcServer/src/"):]
        rest = rest.replace("systems/localization/locales/", "systems/localization/CATALOG/")
        return rest.casefold(), "SERVER"
    if lower.endswith("_legacy_client.inl"):
        return re.sub(r"_legacy_client\.inl$", "_legacy_role.inl", lower), "CLIENT"
    if lower.endswith("_legacy_server.inl"):
        return re.sub(r"_legacy_server\.inl$", "_legacy_role.inl", lower), "SERVER"
    return None


def _mirror_duplicate_flags(rows: list[dict[str, str]], evidence_key) -> list[bool]:
    groups: dict[tuple[Any, ...], list[tuple[int, str, str]]] = defaultdict(list)
    for index, row in enumerate(rows):
        mirror = _mirror_identity(row.get("source_file", ""))
        if mirror is None:
            continue
        identity, role = mirror
        groups[(identity, *evidence_key(row))].append((index, role, row.get("source_file", "")))
    duplicate = [False] * len(rows)
    for items in groups.values():
        roles = {role for _, role, _ in items}
        files = {source_file for _, _, source_file in items}
        if len(files) < 2 or not {"CLIENT", "SERVER"}.issubset(roles):
            continue
        # Preserve every occurrence in the client source and suppress only the
        # equivalent server mirror evidence. We are deduplicating evidence,
        # not deleting source occurrences.
        for index, role, _ in items:
            if role == "SERVER":
                duplicate[index] = True
    return duplicate


def _technical_generated_output(line: str, all_lines: list[str]) -> bool:
    match = ASSIGN_LITERAL_RE.search(line)
    if not match:
        return False
    identifier = match.group(1)
    if not re.search(r"(?:error|log|trace|debug).*file|file.*(?:error|log|trace|debug)", identifier, re.I):
        return False
    probe = "\n".join(all_lines)
    write_patterns = (
        f'fopen({identifier}, "wt")', f'fopen({identifier},"wt")',
        f'fopen({identifier}, "at")', f'fopen({identifier},"at")',
        f"DeleteFile({identifier})", f"DeleteFileA({identifier})",
    )
    return any(pattern in probe for pattern in write_patterns)


def _text_semantic_class(source_file: str, refined_class: str, line: str) -> str:
    if refined_class.startswith("FALSE_POSITIVE_"):
        return "FALSE_POSITIVE"
    if refined_class == "TEST_FIXTURE_NON_RUNTIME":
        return "TEST_FIXTURE"
    path = "/" + source_file.replace("\\", "/").casefold().strip("/") + "/"
    if "/localization/" in path:
        return "LOCALIZATION_TEXT"
    if "/systems/ui/messages/" in path or source_file.casefold().endswith("/sinmsg.cpp"):
        return "RUNTIME_MESSAGE"
    if "/systems/ui/" in path or "/ui/" in path:
        return "UI_LABEL"
    if any(token in line for token in ("OutputDebugString", "printf(", "fprintf(", "TRACE(", "Log")):
        return "DEBUG_OR_LOG"
    return "REVIEW"


def refine_migration_rows(
    rows: list[dict[str, str]],
    *,
    source_root: pathlib.Path | None = None,
    canonical_owner_index: dict[str, list[str]] | None = None,
    canonical_text_runtime_index: dict[str, list[dict[str, Any]]] | None = None,
    model_config_index: dict[str, dict[str, Any]] | None = None,
    text_pack_contract: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    owner_index = canonical_owner_index or {}
    text_runtime_index = canonical_text_runtime_index or {}
    model_index = model_config_index or {}
    pack_contract = text_pack_contract or {"proven": False}
    source_cache: dict[str, list[str]] = {}

    present_by_basename: dict[str, set[str]] = defaultdict(set)
    explicit_paths_by_basename: dict[str, set[str]] = defaultdict(set)
    non_oracle_keys: set[tuple[str, str, str, str]] = set()
    for row in rows:
        path = _norm(row.get("client_path"))
        if path and "/" in path:
            explicit_paths_by_basename[_basename(path)].add(path)
        if row.get("state") == "SOURCE_ONLY_PRESENT" and path:
            present_by_basename[_basename(path)].add(path)
        source_file = row.get("source_file", "")
        refined_scope, _ = _obvious_scope(source_file, row.get("scope", ""))
        if not source_file.startswith("Shared/legacy_oracle/"):
            non_oracle_keys.add((
                row.get("state", ""), refined_scope, path, _norm(row.get("raw_literal"))
            ))

    mirror_flags = _mirror_duplicate_flags(
        rows,
        lambda row: (
            row.get("state", ""),
            _obvious_scope(row.get("source_file", ""), row.get("scope", ""))[0],
            _norm(row.get("client_path")),
            _norm(row.get("raw_literal")),
        ),
    )

    result: list[dict[str, str]] = []
    initial_loader_by_literal: dict[str, set[str]] = defaultdict(set)
    for index, row in enumerate(rows):
        out = dict(row)
        path = _norm(row.get("client_path"))
        runtime_path = _runtime_norm(row.get("client_path"))
        literal = _norm(row.get("raw_literal"))
        source_file = row.get("source_file", "")
        line, context, all_lines = _source_context(source_root, source_file, row.get("source_line", ""), source_cache)
        refined_scope, scope_reason = _obvious_scope(source_file, row.get("scope", ""))
        key = (row.get("state", ""), refined_scope, path, literal)
        oracle_duplicate = source_file.startswith("Shared/legacy_oracle/") and key in non_oracle_keys
        mirror_duplicate = mirror_flags[index]
        printf_template = row.get("state") == "SOURCE_ONLY_MISSING" and bool(PRINTF_RE.search(row.get("raw_literal", "")))
        glob_template = row.get("state") == "SOURCE_ONLY_MISSING" and bool(GLOB_RE.search(row.get("raw_literal", "")))
        loader_class = _known_loader_class(row.get("raw_literal", ""), line, context, row.get("state", ""))
        generated_output = row.get("state") == "SOURCE_ONLY_MISSING" and _technical_generated_output(line, all_lines)
        technical_log = (
            row.get("state") == "SOURCE_ONLY_MISSING"
            and literal.startswith("logs/")
            and any(token in context for token in ("fopen", "fprintf", "CreateFile"))
        )
        test_or_tool = source_file.startswith("tools/") or bool(TEST_RE.search(source_file))
        present_candidates = sorted(present_by_basename.get(_basename(path), set())) if path else []
        explicit_candidates = sorted(explicit_paths_by_basename.get(_basename(path), set())) if path and "/" not in path else []

        if printf_template:
            semantic_class = "DYNAMIC_PRINTF_TEMPLATE"
        elif glob_template:
            semantic_class = "DYNAMIC_GLOB_PATTERN"
        elif generated_output:
            semantic_class = "GENERATED_DIAGNOSTIC_OUTPUT"
        elif technical_log:
            semantic_class = "TECHNICAL_LOG_NOT_RUNTIME_ASSET"
        elif loader_class:
            semantic_class = loader_class
        elif test_or_tool:
            semantic_class = "TEST_OR_TOOL_EVIDENCE"
        else:
            semantic_class = row.get("state", "")

        if loader_class and literal:
            initial_loader_by_literal[literal].add(loader_class)

        owners = owner_index.get(path, [])
        runtime_docs = text_runtime_index.get(runtime_path, [])
        valid_runtime_docs = [doc for doc in runtime_docs if doc.get("payload_valid")]
        model = model_index.get(runtime_path)
        if valid_runtime_docs:
            if pack_contract.get("proven"):
                canonical_runtime_class = "SRES_PACK_BACKED_LEGACY_PATH"
                release_requirement = "VERIFY_TEXT_RESOURCES_SRES_DEPLOYED"
            else:
                canonical_runtime_class = "CANONICAL_TEXT_PAYLOAD_AVAILABLE_RUNTIME_CONTRACT_UNPROVEN"
                release_requirement = "PROVE_TEXT_RUNTIME_PACK_CONTRACT_AND_DEPLOYMENT"
        elif model:
            if model.get("source_status") == "resolved":
                canonical_runtime_class = "MODEL_CONFIG_CATALOG_SOURCE_RESOLVED"
                release_requirement = "VERIFY_MODEL_CONFIG_RUNTIME_RECOVERY_OR_CACHE"
            else:
                canonical_runtime_class = "MODEL_CONFIG_SOURCE_UNRESOLVED"
                release_requirement = "RECOVER_PHYSICAL_MODEL_CONFIG_OR_LEGACY_CACHE"
        else:
            canonical_runtime_class = ""
            release_requirement = ""

        out.update({
            "normalized_client_path": path,
            "normalized_literal": literal,
            "refined_scope": refined_scope,
            "scope_refinement_reason": scope_reason,
            "source_context_line": line.strip(),
            "source_context_window": context.replace("\t", " ").replace("\n", " ").strip(),
            "oracle_duplicate_evidence": str(oracle_duplicate),
            "mirror_duplicate_evidence": str(mirror_duplicate),
            "dynamic_template": str(printf_template or glob_template),
            "loader_resolution_hint": loader_class,
            "basename_present_candidate_count": str(len(present_candidates)),
            "basename_present_candidates": ";".join(present_candidates),
            "explicit_path_candidate_count": str(len(explicit_candidates)),
            "explicit_path_candidates": ";".join(explicit_candidates),
            "semantic_review_class": semantic_class,
            "actionable_primary_evidence": str(not oracle_duplicate and not mirror_duplicate),
            "canonical_owner_count": str(len(owners)),
            "canonical_owner_files": ";".join(owners),
            "canonical_text_runtime_owner_count": str(len(runtime_docs)),
            "canonical_text_payload_valid": str(bool(valid_runtime_docs)),
            "canonical_text_runtime_owners": ";".join(sorted({str(doc.get("owner_file") or "") for doc in runtime_docs})),
            "canonical_runtime_class": canonical_runtime_class,
            "release_requirement": release_requirement,
            "model_config_owner": str(model.get("owner_file") or "") if model else "",
            "model_config_source_status": str(model.get("source_status") or "") if model else "",
            "model_config_legacy_cache": str(model.get("legacy_cache") or "") if model else "",
        })
        result.append(out)

    # Second pass: a bare basename can be proven to be an alias/lookup key when
    # the same literal has direct loader evidence elsewhere, or when the source
    # also contains explicit rooted paths with the same basename. This changes
    # the review class only; it never marks the underlying physical candidate as present.
    for out in result:
        if out.get("state") != "SOURCE_ONLY_MISSING" or out.get("semantic_review_class") != "SOURCE_ONLY_MISSING":
            continue
        literal = out.get("normalized_literal", "")
        path = out.get("normalized_client_path", "")
        if "/" in literal or not literal:
            continue
        inherited = sorted(initial_loader_by_literal.get(literal, set()))
        if inherited:
            out["semantic_review_class"] = "LOADER_ALIAS_CROSS_REFERENCE"
            out["loader_resolution_hint"] = ";".join(inherited)
        elif out.get("explicit_path_candidate_count") not in ("", "0"):
            out["semantic_review_class"] = "SOURCE_ALIAS_TO_EXPLICIT_PATH"

    return result


def refine_ui_rows(
    rows: list[dict[str, str]],
    *,
    source_root: pathlib.Path | None = None,
) -> list[dict[str, str]]:
    source_cache: dict[str, list[str]] = {}
    non_oracle_texts = {
        row.get("text", "")
        for row in rows
        if not row.get("source_file", "").startswith("Shared/legacy_oracle/")
    }
    mirror_flags = _mirror_duplicate_flags(rows, lambda row: (row.get("text", ""),))
    result: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        out = dict(row)
        source_file = row.get("source_file", "")
        text = row.get("text", "").replace("\x00", "").strip()
        line, context, _ = _source_context(source_root, source_file, row.get("source_line", ""), source_cache)
        oracle_duplicate = source_file.startswith("Shared/legacy_oracle/") and row.get("text", "") in non_oracle_texts
        mirror_duplicate = mirror_flags[index]
        include = bool(INCLUDE_RE.search(line))
        source_path = bool(SOURCE_EXT_RE.search(text))
        test_fixture = bool(TEST_RE.search(source_file))

        if include:
            refined_class = "FALSE_POSITIVE_SOURCE_INCLUDE"
        elif source_path:
            refined_class = "FALSE_POSITIVE_SOURCE_CODE_PATH"
        elif test_fixture:
            refined_class = "TEST_FIXTURE_NON_RUNTIME"
        else:
            refined_class = "REVIEW"
        semantic_class = _text_semantic_class(source_file, refined_class, line)

        out.update({
            "source_context_line": line.strip(),
            "source_context_window": context.replace("\t", " ").replace("\n", " ").strip(),
            "oracle_duplicate_evidence": str(oracle_duplicate),
            "mirror_duplicate_evidence": str(mirror_duplicate),
            "refined_class": refined_class,
            "semantic_text_class": semantic_class,
            "actionable_primary_evidence": str(
                not oracle_duplicate and not mirror_duplicate and refined_class == "REVIEW"
            ),
        })
        result.append(out)
    return result


def _count(rows: list[dict[str, str]], key: str, value: str) -> int:
    return sum(1 for row in rows if row.get(key) == value)


def audit_summit_asset_refinement(
    baseline_dir: str | pathlib.Path,
    *,
    source_root: str | pathlib.Path | None = None,
    canonical_root: str | pathlib.Path | None = None,
    output_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    baseline = pathlib.Path(baseline_dir).resolve()
    source = pathlib.Path(source_root).resolve() if source_root else None
    canonical = pathlib.Path(canonical_root).resolve() if canonical_root else None
    output = pathlib.Path(output_dir).resolve() if output_dir else baseline / "refined"

    migration_path = baseline / "migration_queue.tsv"
    ui_path = baseline / "ui_text_candidates.tsv"
    if not migration_path.is_file():
        raise FileNotFoundError(f"MIGRATION_QUEUE_NOT_FOUND:{migration_path}")
    if not ui_path.is_file():
        raise FileNotFoundError(f"UI_TEXT_CANDIDATES_NOT_FOUND:{ui_path}")
    if source is not None and not source.is_dir():
        raise FileNotFoundError(f"SOURCE_ROOT_NOT_FOUND:{source}")
    if canonical is not None and not canonical.is_dir():
        raise FileNotFoundError(f"CANONICAL_ROOT_NOT_FOUND:{canonical}")

    migration = _read_tsv(migration_path)
    ui = _read_tsv(ui_path)
    owners = build_canonical_owner_index(canonical)
    text_runtime = build_canonical_text_runtime_index(canonical)
    model_configs = build_model_config_index(canonical)
    pack_contract = detect_text_pack_contract(source)
    refined_migration = refine_migration_rows(
        migration,
        source_root=source,
        canonical_owner_index=owners,
        canonical_text_runtime_index=text_runtime,
        model_config_index=model_configs,
        text_pack_contract=pack_contract,
    )
    refined_ui = refine_ui_rows(ui, source_root=source)

    output.mkdir(parents=True, exist_ok=True)
    migration_fields = list(migration[0].keys()) if migration else []
    migration_fields += [
        "normalized_client_path", "normalized_literal", "refined_scope", "scope_refinement_reason",
        "source_context_line", "source_context_window", "oracle_duplicate_evidence", "mirror_duplicate_evidence",
        "dynamic_template", "loader_resolution_hint", "basename_present_candidate_count", "basename_present_candidates",
        "explicit_path_candidate_count", "explicit_path_candidates", "semantic_review_class", "actionable_primary_evidence",
        "canonical_owner_count", "canonical_owner_files", "canonical_text_runtime_owner_count",
        "canonical_text_payload_valid", "canonical_text_runtime_owners", "canonical_runtime_class", "release_requirement",
        "model_config_owner", "model_config_source_status", "model_config_legacy_cache",
    ]
    ui_fields = list(ui[0].keys()) if ui else []
    ui_fields += [
        "source_context_line", "source_context_window", "oracle_duplicate_evidence", "mirror_duplicate_evidence",
        "refined_class", "semantic_text_class", "actionable_primary_evidence",
    ]
    _write_tsv(output / "migration_queue_refined.tsv", refined_migration, migration_fields)
    _write_tsv(output / "ui_text_candidates_refined.tsv", refined_ui, ui_fields)

    canonical_missing = [row for row in refined_migration if row.get("state") == "CANONICAL_RUNTIME_ASSET_MISSING"]
    canonical_fields = migration_fields + ["extension", "path_family"]
    canonical_review: list[dict[str, str]] = []
    for row in canonical_missing:
        item = dict(row)
        path = _norm(item.get("client_path"))
        parts = path.split("/") if path else []
        item["extension"] = PurePosixPath(path).suffix
        item["path_family"] = "/".join(parts[:3]) if len(parts) >= 3 else "/".join(parts)
        canonical_review.append(item)
    _write_tsv(output / "canonical_missing_review.tsv", canonical_review, canonical_fields)

    primary_migration = [row for row in refined_migration if row.get("actionable_primary_evidence") == "True"]
    primary_ui = [row for row in refined_ui if row.get("actionable_primary_evidence") == "True"]
    unresolved_p0_source_missing = [
        row for row in primary_migration
        if row.get("priority") == "P0"
        and row.get("state") == "SOURCE_ONLY_MISSING"
        and row.get("semantic_review_class") == "SOURCE_ONLY_MISSING"
    ]
    canonical_without_owner = [row for row in canonical_missing if row.get("canonical_owner_count") == "0"]
    pack_backed = [row for row in canonical_missing if row.get("canonical_runtime_class") == "SRES_PACK_BACKED_LEGACY_PATH"]
    model_unresolved = [row for row in canonical_missing if row.get("canonical_runtime_class") == "MODEL_CONFIG_SOURCE_UNRESOLVED"]
    physical_unresolved = [row for row in canonical_missing if row.get("canonical_runtime_class") != "SRES_PACK_BACKED_LEGACY_PATH"]

    _write_tsv(output / "p0_source_missing_unresolved.tsv", unresolved_p0_source_missing, migration_fields)
    _write_tsv(output / "canonical_physical_missing.tsv", physical_unresolved, canonical_fields)
    _write_tsv(output / "ui_review_primary.tsv", primary_ui, ui_fields)

    report: dict[str, Any] = {
        "format": FORMAT,
        "status": "PASS",
        "state": "REVIEW_REQUIRED",
        "baseline_dir": str(baseline),
        "source_root": str(source) if source else "",
        "canonical_root": str(canonical) if canonical else "",
        "baseline": {
            "migration_queue": len(migration),
            "P0": _count(migration, "priority", "P0"),
            "P1": _count(migration, "priority", "P1"),
            "P2": _count(migration, "priority", "P2"),
            "SOURCE_ONLY_MISSING": _count(migration, "state", "SOURCE_ONLY_MISSING"),
            "SOURCE_ONLY_PRESENT": _count(migration, "state", "SOURCE_ONLY_PRESENT"),
            "CANONICAL_RUNTIME_ASSET_MISSING": len(canonical_missing),
            "ui_text_candidates": len(ui),
        },
        "refinement": {
            "oracle_duplicate_rows": _count(refined_migration, "oracle_duplicate_evidence", "True"),
            "mirror_duplicate_rows": _count(refined_migration, "mirror_duplicate_evidence", "True"),
            "dynamic_printf_template_rows": _count(refined_migration, "semantic_review_class", "DYNAMIC_PRINTF_TEMPLATE"),
            "dynamic_glob_rows": _count(refined_migration, "semantic_review_class", "DYNAMIC_GLOB_PATTERN"),
            "assa_resource_alias_rows": _count(refined_migration, "semantic_review_class", "ASSA_RESOURCE_CATALOG_ALIAS"),
            "ho_sequence_alias_rows": sum(
                row.get("semantic_review_class") in {"HO_ANIMATION_SEQUENCE_ALIAS", "HO_ANIMATION_SEQUENCE_ALIAS_INDIRECT"}
                for row in refined_migration
            ),
            "loader_alias_cross_reference_rows": _count(refined_migration, "semantic_review_class", "LOADER_ALIAS_CROSS_REFERENCE"),
            "source_alias_to_explicit_path_rows": _count(refined_migration, "semantic_review_class", "SOURCE_ALIAS_TO_EXPLICIT_PATH"),
            "generated_diagnostic_output_rows": _count(refined_migration, "semantic_review_class", "GENERATED_DIAGNOSTIC_OUTPUT"),
            "technical_log_rows": _count(refined_migration, "semantic_review_class", "TECHNICAL_LOG_NOT_RUNTIME_ASSET"),
            "scope_corrected_to_audio_rows": sum(row.get("scope_refinement_reason") == "SOURCE_PATH_AUDIO_DOMAIN" for row in refined_migration),
            "ui_source_include_false_positive_rows": _count(refined_ui, "refined_class", "FALSE_POSITIVE_SOURCE_INCLUDE"),
            "ui_source_code_path_false_positive_rows": _count(refined_ui, "refined_class", "FALSE_POSITIVE_SOURCE_CODE_PATH"),
            "ui_test_fixture_rows": _count(refined_ui, "refined_class", "TEST_FIXTURE_NON_RUNTIME"),
            "ui_oracle_duplicate_rows": _count(refined_ui, "oracle_duplicate_evidence", "True"),
            "ui_mirror_duplicate_rows": _count(refined_ui, "mirror_duplicate_evidence", "True"),
            "ui_localization_text_rows": _count(refined_ui, "semantic_text_class", "LOCALIZATION_TEXT"),
            "ui_runtime_message_rows": _count(refined_ui, "semantic_text_class", "RUNTIME_MESSAGE"),
            "ui_label_rows": _count(refined_ui, "semantic_text_class", "UI_LABEL"),
            "canonical_missing_with_exact_owner": len(canonical_missing) - len(canonical_without_owner),
            "canonical_missing_without_exact_owner": len(canonical_without_owner),
            "canonical_missing_sres_pack_backed": len(pack_backed),
            "canonical_missing_model_config_unresolved": len(model_unresolved),
            "canonical_missing_physical_unresolved_after_pack_contract": len(physical_unresolved),
        },
        "actionable_views": {
            "migration_primary_rows_after_oracle_and_mirror_suppression": len(primary_migration),
            "P0_SOURCE_ONLY_MISSING_still_unresolved_rows": len(unresolved_p0_source_missing),
            "P0_SOURCE_ONLY_MISSING_still_unresolved_unique_paths": len({row.get("normalized_client_path", "") for row in unresolved_p0_source_missing}),
            "ui_review_primary_rows_after_safe_filters_and_mirror_suppression": len(primary_ui),
            "canonical_physical_missing_requiring_recovery": len(physical_unresolved),
            "canonical_pack_backed_paths_requiring_pack_deployment_validation": len(pack_backed),
        },
        "text_resource_pack_contract": pack_contract,
        "policy": {
            "raw_rows_preserved": True,
            "deletion_authorized": False,
            "source_only_protected": True,
            "canonical_missing_not_downgraded": True,
            "canonical_owner_is_reference_evidence_not_physical_presence": True,
            "sres_pack_backed_class_requires_deployment_validation": True,
            "loader_aliases_require_physical_resolution_before_release_clearance": True,
            "oracle_duplicates_are_suppressed_only_when_exact_non_oracle_evidence_exists": True,
            "mirror_duplicates_are_suppressed_only_for_exact_client_server_evidence_pairs": True,
        },
        "outputs": {
            "migration_queue_refined": str(output / "migration_queue_refined.tsv"),
            "ui_text_candidates_refined": str(output / "ui_text_candidates_refined.tsv"),
            "canonical_missing_review": str(output / "canonical_missing_review.tsv"),
            "canonical_physical_missing": str(output / "canonical_physical_missing.tsv"),
            "p0_source_missing_unresolved": str(output / "p0_source_missing_unresolved.tsv"),
            "ui_review_primary": str(output / "ui_review_primary.tsv"),
            "result": str(output / "result.json"),
        },
    }
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refine SUMMIT asset migration/UI audit evidence without deleting baseline rows.")
    parser.add_argument("--baseline-dir", required=True)
    parser.add_argument("--source-root")
    parser.add_argument("--canonical-root")
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    result = audit_summit_asset_refinement(
        args.baseline_dir,
        source_root=args.source_root,
        canonical_root=args.canonical_root,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
