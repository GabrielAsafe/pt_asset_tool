from __future__ import annotations

import json
import os
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any

from .source_catalog import SourceTree, iter_source_files, read_source_text, source_rel
from .source_evidence import _strip_c_comments

FORMAT = "PT_EFFECT_RUNTIME_ROOT_COVERAGE_V1"

_FULL_LITERAL_RE = re.compile(
    r'''["'](?P<path>Effect[\\/][^"'\r\n]+?\.(?:ini|ase|smd|smb|part|lua|bmp|tga|dds|png|jpg|jpeg))["']''',
    re.IGNORECASE,
)
_BARE_INI_CALL_RE = re.compile(
    r'''(?P<callee>StartBillRect|StartDestPath|StartBillRectPrimitive)\s*\([^;]{0,1200}?["'](?P<name>[^"'\\/]+\.ini)["']''',
    re.IGNORECASE,
)
_FULL_PATH_CALLEES = (
    "CreateTextureMaterial", "smASE_Read", "smASE_ReadBone", "GetPrivateProfileString",
    "GetPrivateProfileInt", "ImageLoad", "SequenceLoad", "LoadParticle", "LoadScript",
)
_ALLOWED_EFFECT_PREFIXES = (
    "effect/animationdata/", "effect/imagedata/", "effect/objanimationdata/",
    "effect/particle/", "effect/etc/", "effect/assaeffect/",
)


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _client_index(root: pathlib.Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    exact: dict[str, str] = {}
    basename: dict[str, list[str]] = defaultdict(list)
    if not root.is_dir():
        return exact, basename
    for base, dirs, files in os.walk(root):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            p = pathlib.Path(base) / name
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            exact[rel.casefold()] = rel
            if rel.casefold().startswith("effect/"):
                basename[name.casefold()].append(rel)
    return exact, basename


def _statement_context(text: str, offset: int, radius: int = 1400) -> str:
    """Return a bounded C/C++ statement context while preserving multiline calls."""
    floor = max(0, offset - radius)
    ceil = min(len(text), offset + radius)
    start = text.rfind(";", floor, offset) + 1
    semi = text.find(";", offset, ceil)
    end = (semi + 1) if semi >= 0 else ceil
    return text[start:end]


def _resolve_exact_effect_path(raw: str, exact: dict[str, str]) -> tuple[str, str]:
    rel = _norm(raw)
    value = exact.get(rel.casefold())
    if value:
        return value, "EXACT_EFFECT_PATH"
    return rel, "MISSING_EXACT_EFFECT_PATH"


def _resolve_animation_ini(name: str, exact: dict[str, str], basename: dict[str, list[str]]) -> tuple[str, str, list[str]]:
    clean = pathlib.PurePosixPath(_norm(name)).name
    preferred = f"Effect/AnimationData/{clean}"
    if preferred.casefold() in exact:
        return exact[preferred.casefold()], "ANIMATION_DATA_RUNTIME_NAMESPACE", [exact[preferred.casefold()]]
    candidates = [
        p for p in basename.get(clean.casefold(), [])
        if p.casefold().startswith(_ALLOWED_EFFECT_PREFIXES)
    ]
    candidates = sorted(dict.fromkeys(candidates), key=str.casefold)
    if len(candidates) == 1:
        return candidates[0], "UNIQUE_EFFECT_BASENAME", candidates
    if candidates:
        return "", "AMBIGUOUS_EFFECT_BASENAME", candidates
    return "", "MISSING_EFFECT_BASENAME", []


def audit_effect_runtime_coverage(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    current_tree: SourceTree,
) -> dict[str, Any]:
    """Discover current-source runtime effect roots without guessing dead folders.

    Only literals passed through known legacy effect loaders are promoted. Bare
    billboard INI names are resolved through the historical AnimationData
    namespace first. Ambiguous/missing basenames remain review evidence.
    """
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    out_dir = project / "pt_build" / "effect_runtime_coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    exact, basename = _client_index(client)

    roots: dict[str, set[str]] = defaultdict(set)
    review_rows: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    source_files_scanned = 0

    for src in iter_source_files(current_tree.root):
        source_files_scanned += 1
        try:
            raw_text, _enc = read_source_text(src)
            text = _strip_c_comments(raw_text)
        except Exception:
            continue
        rel_src = source_rel(current_tree.root, src)

        # Exact Effect/... literals are strong only when they appear in the
        # neighborhood of a known legacy runtime loader call.
        for match in _FULL_LITERAL_RE.finditer(text):
            context = _statement_context(text, match.start())
            callee = next((x for x in _FULL_PATH_CALLEES if x.casefold() in context.casefold()), "")
            if not callee:
                continue
            path, basis = _resolve_exact_effect_path(match.group("path"), exact)
            row = {
                "source_file": rel_src,
                "source_line": _line(text, match.start()),
                "callee": callee,
                "literal": _norm(match.group("path")),
                "resolved_path": path if basis == "EXACT_EFFECT_PATH" else "",
                "resolution_basis": basis,
                "strength": "STRONG" if basis == "EXACT_EFFECT_PATH" else "REVIEW",
            }
            witnesses.append(row)
            if basis == "EXACT_EFFECT_PATH":
                roots[path.casefold()].add(f"EFFECT_RUNTIME_LOADER:{callee}:{rel_src}:{row['source_line']}")
            else:
                review_rows.append(row)

        # Billboard/path APIs consume a sequence name, not a filesystem path.
        # Resolve that name through Effect/AnimationData first.
        for match in _BARE_INI_CALL_RE.finditer(text):
            resolved, basis, candidates = _resolve_animation_ini(match.group("name"), exact, basename)
            row = {
                "source_file": rel_src,
                "source_line": _line(text, match.start()),
                "callee": match.group("callee"),
                "literal": match.group("name"),
                "resolved_path": resolved,
                "resolution_basis": basis,
                "candidates": candidates,
                "strength": "STRONG" if resolved else "REVIEW",
            }
            witnesses.append(row)
            if resolved:
                roots[resolved.casefold()].add(
                    f"EFFECT_SEQUENCE_RUNTIME:{match.group('callee')}:{rel_src}:{row['source_line']}"
                )
            else:
                review_rows.append(row)

    root_rows = [
        {"path": exact.get(key, key), "evidence": sorted(values)}
        for key, values in sorted(roots.items())
    ]
    resolution_counts = Counter(str(x.get("resolution_basis") or "UNKNOWN") for x in witnesses)
    report = {
        "format": FORMAT,
        "status": "PASS",
        "source_root": str(current_tree.root),
        "client_root": str(client),
        "source_files_scanned": source_files_scanned,
        "witness_count": len(witnesses),
        "strong_root_count": len(root_rows),
        "review_witness_count": len(review_rows),
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "policy": {
            "known_loader_calls_only": True,
            "bare_ini_prefers_effect_animationdata_namespace": True,
            "ambiguous_basename_is_review_not_root": True,
            "source_literal_alone_is_not_root": True,
            "write_authorized": False,
        },
        "roots": root_rows,
        "review": review_rows,
        "witnesses": witnesses,
    }
    report_path = out_dir / "result.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report
