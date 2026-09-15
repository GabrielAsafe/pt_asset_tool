from __future__ import annotations

import collections
import json
import os
import pathlib
import re
from typing import Any, Callable

FORMAT = "PT_ASSET_SERVER_ENTITY_BUNDLE_CENSUS_V2"
# Prefer quoted references, but accept the Windows-era unquoted path syntax that
# also appears in real Summit text files.  This scanner is analysis-only; bytes
# are never rewritten here.
_QUOTED_PATH_RE = re.compile(r'''["']([^"'\r\n]+\.(?:ini|inx|smd|smb|zhoon))["']''', re.IGNORECASE)
_UNQUOTED_PATH_RE = re.compile(
    r'''(?i)(?<![A-Za-z0-9_])((?:[A-Za-z0-9_ .()\-]+[\\/])+[A-Za-z0-9_ .()\-]+\.(?:ini|inx|smd|smb|zhoon))'''
)


def _decode_text(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp949", "cp1252"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return data.decode("latin1"), "latin1"


def _norm_ref(raw: str) -> str:
    value = raw.strip().replace("\\", "/").lstrip("./").lstrip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return value


def _ci_child(parent: pathlib.Path, name: str, *, want_dir: bool | None = None) -> pathlib.Path | None:
    direct = parent / name
    if direct.exists() and (want_dir is None or direct.is_dir() == want_dir):
        return direct
    if not parent.is_dir():
        return None
    try:
        hits = [
            p for p in parent.iterdir()
            if p.name.casefold() == name.casefold()
            and (want_dir is None or p.is_dir() == want_dir)
        ]
    except OSError:
        return None
    return hits[0] if len(hits) == 1 else None


def _ci_resolve(root: pathlib.Path, rel: str, *, want_dir: bool | None = None) -> pathlib.Path | None:
    cur = pathlib.Path(root)
    parts = pathlib.PurePosixPath(_norm_ref(rel)).parts
    if not parts:
        return cur if (want_dir is None or cur.is_dir() == want_dir) else None
    for i, part in enumerate(parts):
        cur = _ci_child(cur, part, want_dir=(want_dir if i == len(parts) - 1 else True))
        if cur is None:
            return None
    return cur


def _index_subtree(root: pathlib.Path, subtree: str) -> dict[str, pathlib.Path]:
    base = _ci_resolve(root, subtree, want_dir=True)
    out: dict[str, pathlib.Path] = {}
    if base is None:
        return out
    for walk_base, dirs, files in os.walk(base):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            p = pathlib.Path(walk_base) / name
            rel = p.relative_to(root).as_posix()
            out.setdefault(rel.casefold(), p)
    return out


def _resolve(index: dict[str, pathlib.Path], rel: str) -> pathlib.Path | None:
    return index.get(_norm_ref(rel).casefold())


def _resolve_server_reference(server_root: pathlib.Path, definition_path: pathlib.Path, rel: str) -> pathlib.Path | None:
    """Resolve a server text reference using the runtime-style relative basis.

    References such as ``name\\Foo.zhoon`` are relative to the directory of
    the INF/NPC/OpenItem definition, not to the server root.  A root-relative
    fallback is retained for legacy packs that already spell ``GameServer/...``.
    Resolution is case-insensitive because the original runtime paths are
    Windows-era while the audit host is Linux.
    """
    norm = _norm_ref(rel)
    candidates: list[str] = []
    try:
        parent_rel = definition_path.parent.relative_to(server_root).as_posix()
        candidates.append(f"{parent_rel}/{norm}")
    except ValueError:
        pass
    candidates.append(norm)
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        hit = _ci_resolve(server_root, candidate, want_dir=False)
        if hit is not None:
            return hit
    return None


def _logical_inx(model_ref: str) -> str | None:
    p = pathlib.PurePosixPath(_norm_ref(model_ref))
    if p.suffix.casefold() == ".ini":
        return p.with_suffix(".inx").as_posix()
    if p.suffix.casefold() == ".inx":
        return p.as_posix()
    return None


def _extract_refs(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for rx in (_QUOTED_PATH_RE, _UNQUOTED_PATH_RE):
        for m in rx.finditer(text):
            rel = _norm_ref(m.group(1))
            low = rel.casefold()
            # A fallback regex may include leading directive text separated by
            # spaces.  Trim to the first known logical root when present.
            for marker in ("char/", "name/", "gameserver/"):
                pos = low.find(marker)
                if pos >= 0:
                    rel = rel[pos:]
                    low = rel.casefold()
                    break
            if (low.startswith("char/") or low.startswith("name/") or low.startswith("gameserver/")) and low not in seen:
                seen.add(low)
                out.append(rel)
    return out


def audit_server_entity_bundles(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    client_root: pathlib.Path,
    *,
    sample_limit: int = 40,
    progress_every: int = 250,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    server_root = pathlib.Path(server_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    report_dir = project_root / "pt_build" / "devtest" / "server_bundle_census"
    report_path = report_dir / "result.json"

    server_char = _index_subtree(server_root, "char")
    client_char = _index_subtree(client_root, "char")

    definitions: list[tuple[str, str]] = []
    for rel_dir, ext, kind in (("GameServer/Monster", ".inf", "MONSTER"), ("GameServer/NPC", ".npc", "NPC")):
        base = _ci_resolve(server_root, rel_dir, want_dir=True)
        if base is None:
            continue
        for walk_base, dirs, files in os.walk(base):
            dirs.sort(key=str.casefold)
            files.sort(key=str.casefold)
            for name in files:
                if pathlib.PurePosixPath(name).suffix.casefold() == ext:
                    p = pathlib.Path(walk_base) / name
                    # name/ subtrees contain localization, never entity defs.
                    rel_parts = [part.casefold() for part in p.relative_to(base).parts[:-1]]
                    if "name" in rel_parts:
                        continue
                    definitions.append((kind, p.relative_to(server_root).as_posix()))
    definitions.sort(key=lambda row: (row[0], row[1].casefold()))

    rows: list[dict[str, Any]] = []
    status_counts: collections.Counter[str] = collections.Counter()
    encoding_counts: collections.Counter[str] = collections.Counter()
    reason_counts: collections.Counter[str] = collections.Counter()

    for idx, (kind, rel) in enumerate(definitions, start=1):
        p = _ci_resolve(server_root, rel, want_dir=False) or (server_root / pathlib.PurePosixPath(rel))
        try:
            data = p.read_bytes()
            text, enc = _decode_text(data)
            refs = _extract_refs(text)
            error = None
        except Exception as exc:
            refs = []
            enc = None
            error = f"{type(exc).__name__}:{exc}"

        model_refs = [
            r for r in refs
            if r.casefold().startswith("char/")
            and pathlib.PurePosixPath(r).suffix.casefold() in {".ini", ".inx", ".smd", ".smb"}
        ]
        zhoon_refs = [r for r in refs if pathlib.PurePosixPath(r).suffix.casefold() == ".zhoon"]
        model_ref = model_refs[0] if model_refs else None
        inx_rel = _logical_inx(model_ref) if model_ref else None
        server_inx = _resolve(server_char, inx_rel) if inx_rel else None
        client_inx = _resolve(client_char, inx_rel) if inx_rel else None
        zhoon_resolved = []
        for zr in zhoon_refs:
            zp = _resolve_server_reference(server_root, p, zr)
            special_shared = _norm_ref(zr).casefold() == "name/name.zhoon"
            zhoon_resolved.append({
                "reference": zr,
                "exists_server": zp is not None,
                "path": str(zp) if zp else None,
                "resolution_basis": "DEFINITION_DIRECTORY_THEN_SERVER_ROOT",
                "shared_default_review": special_shared,
            })

        reasons: list[str] = []
        if error:
            reasons.append("DECODE_OR_READ_ERROR")
        if not model_ref:
            reasons.append("NO_LITERAL_MODEL_REFERENCE")
        elif not inx_rel:
            reasons.append("MODEL_REFERENCE_NOT_INI_OR_INX")
        elif not (server_inx or client_inx):
            reasons.append("MODEL_INX_NOT_RESOLVED_CLIENT_OR_SERVER")
        missing_zhoon = [x for x in zhoon_resolved if not x["exists_server"]]
        blocking_zhoon = [x for x in missing_zhoon if not x.get("shared_default_review")]
        shared_default_zhoon = [x for x in missing_zhoon if x.get("shared_default_review")]
        if blocking_zhoon:
            reasons.append("ZHOON_REFERENCE_MISSING")
        if shared_default_zhoon:
            # Hundreds of monster definitions use exactly Name/Name.zhoon. The
            # dependency remains visible, but a single unresolved shared/default
            # reference must not be multiplied into hundreds of visual blockers.
            reasons.append("ZHOON_SHARED_DEFAULT_REVIEW")

        if error:
            status = "READ_FAIL"
        elif not model_ref:
            status = "REVIEW_NO_MODEL_LITERAL"
        elif inx_rel and (server_inx or client_inx) and not blocking_zhoon:
            status = "VISUAL_ENTRY_RESOLVED"
        else:
            status = "BLOCKED_DEPENDENCY"

        status_counts[status] += 1
        if enc:
            encoding_counts[enc] += 1
        for r in reasons:
            reason_counts[r] += 1
        rows.append({
            "kind": kind,
            "definition": rel,
            "encoding": enc,
            "status": status,
            "literal_refs": refs,
            "model_reference": model_ref,
            "logical_inx": inx_rel,
            "server_inx_exists": server_inx is not None,
            "server_inx_path": str(server_inx) if server_inx else None,
            "client_inx_exists": client_inx is not None,
            "client_inx_path": str(client_inx) if client_inx else None,
            "zhoon": zhoon_resolved,
            "reasons": reasons,
            "error": error,
        })
        if progress and progress_every > 0 and (idx == 1 or idx % progress_every == 0 or idx == len(definitions)):
            progress(f"SERVER_BUNDLES {idx}/{len(definitions)} {kind} {rel}")

    unresolved = [r for r in rows if r["status"] != "VISUAL_ENTRY_RESOLVED"]
    result = {
        "format": FORMAT,
        "status": "PASS",
        "audit_completed": True,
        "server_root": str(server_root),
        "client_root": str(client_root),
        "definition_count": len(rows),
        "resolved_visual_entry_count": status_counts.get("VISUAL_ENTRY_RESOLVED", 0),
        "unresolved_count": len(unresolved),
        "status_counts": dict(sorted(status_counts.items())),
        "encoding_counts": dict(sorted(encoding_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "unresolved_sample": unresolved[:sample_limit],
        "rows": rows,
        "scope": {
            "included": ["GameServer/Monster/*.inf", "GameServer/NPC/*.npc", "literal char/name references"],
            "path_resolution": "CASE_INSENSITIVE_WINDOWS_RUNTIME_COMPAT; relative name refs use definition directory",
            "not_yet_claimed": ["drop-code catalog closure", "SPC placement semantics", "INX->SMD/SMB deep parse on server copy", "Name/Name.zhoon shared/default semantic closure"],
            "authoring_certification": False,
        },
        "server_write_authorized": False,
        "client_write_authorized": False,
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
