from __future__ import annotations

import collections
import json
import os
import pathlib
import re
from typing import Any, Callable

from .server_bundle_census import _ci_resolve, _resolve_server_reference

FORMAT = "PT_ASSET_SERVER_ITEM_BUNDLE_CENSUS_V2"
_CODE_PATTERNS = [
    re.compile(r'(?im)^\s*\*?CODE\s+"([^"\r\n]+)"'),
    re.compile(r'(?im)^\s*\*?CODE\s+([^\s#;\r\n]+)'),
]
_ITEM_CODE_RE = re.compile(r'(?i)(?<![A-Za-z0-9])(?:[A-Z]{1,3}\d{2,4}|F0\d{3})(?![A-Za-z0-9])')
_ZHOON_RE = re.compile(r'''["'](name[\\/][^"'\r\n]+\.zhoon)["']''', re.IGNORECASE)


def _decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp949", "cp1252"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return data.decode("latin1"), "latin1"


def _code_from_text(text: str) -> str | None:
    for rx in _CODE_PATTERNS:
        m = rx.search(text)
        if m:
            value = m.group(1).strip()
            return value.upper() if value else None
    return None


def _code_from_filename(path: pathlib.Path) -> str | None:
    """OpenItem identity fallback proved by the final enrichment corpus.

    This establishes server *item definition identity* only.  It is deliberately
    not used to infer a client visual filename; that still requires the server
    code map + client catalogue/DorpItem chain.
    """
    hits = [m.group(0).upper() for m in _ITEM_CODE_RE.finditer(path.stem)]
    return hits[-1] if hits else None


def _zhoon_refs(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _ZHOON_RE.finditer(text):
        rel = m.group(1).replace("\\", "/")
        k = rel.casefold()
        if k not in seen:
            seen.add(k)
            out.append(rel)
    return out


def audit_server_item_bundles(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    sample_limit: int = 50,
    progress_every: int = 250,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    server_root = pathlib.Path(server_root).resolve()
    root = _ci_resolve(server_root, "GameServer/OpenItem", want_dir=True)
    report_dir = project_root / "pt_build" / "devtest" / "server_item_census"
    report_path = report_dir / "result.json"

    files: list[pathlib.Path] = []
    if root is not None:
        for walk_base, dirs, names in os.walk(root):
            # Localization subtree is a dependency, not another OpenItem def.
            dirs[:] = [d for d in dirs if d.casefold() != "name"]
            dirs.sort(key=str.casefold)
            names.sort(key=str.casefold)
            for name in names:
                if pathlib.PurePosixPath(name).suffix.casefold() == ".txt":
                    files.append(pathlib.Path(walk_base) / name)
    files.sort(key=lambda p: p.as_posix().casefold())

    rows: list[dict[str, Any]] = []
    code_to_rows: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    enc_counts: collections.Counter[str] = collections.Counter()
    reason_counts: collections.Counter[str] = collections.Counter()
    identity_basis_counts: collections.Counter[str] = collections.Counter()

    for idx, p in enumerate(files, start=1):
        rel = p.relative_to(server_root).as_posix()
        try:
            text, enc = _decode(p.read_bytes())
            error = None
        except Exception as exc:
            text = ""
            enc = None
            error = f"{type(exc).__name__}:{exc}"

        text_code = _code_from_text(text) if not error else None
        filename_code = _code_from_filename(p) if not error else None
        code = text_code or filename_code
        identity_basis = "EXPLICIT_CODE_TOKEN" if text_code else ("OPENITEM_FILENAME_CODE_V6" if filename_code else None)
        zrefs = _zhoon_refs(text) if not error else []
        zrows = []
        for z in zrefs:
            zp = _resolve_server_reference(server_root, p, z)
            zrows.append({
                "reference": z,
                "exists_server": zp is not None,
                "path": str(zp) if zp else None,
                "resolution_basis": "DEFINITION_DIRECTORY_THEN_SERVER_ROOT",
            })

        reasons: list[str] = []
        if error:
            reasons.append("READ_OR_DECODE_ERROR")
        if not code:
            reasons.append("CODE_NOT_PARSED")
        if zrows and not all(z["exists_server"] for z in zrows):
            reasons.append("ZHOON_REFERENCE_MISSING")
        row = {
            "definition": rel,
            "encoding": enc,
            "code": code,
            "identity_basis": identity_basis,
            "zhoon": zrows,
            "reasons": reasons,
            "error": error,
        }
        rows.append(row)
        if code:
            code_to_rows[code.casefold()].append(row)
        if enc:
            enc_counts[enc] += 1
        if identity_basis:
            identity_basis_counts[identity_basis] += 1
        for r in reasons:
            reason_counts[r] += 1
        if progress and progress_every > 0 and (idx == 1 or idx % progress_every == 0 or idx == len(files)):
            progress(f"SERVER_ITEMS {idx}/{len(files)} {rel}")

    duplicate_codes = {k: [r["definition"] for r in v] for k, v in code_to_rows.items() if len(v) > 1}
    for code, _defs in duplicate_codes.items():
        for row in code_to_rows[code]:
            if "DUPLICATE_CODE" not in row["reasons"]:
                row["reasons"].append("DUPLICATE_CODE")
                reason_counts["DUPLICATE_CODE"] += 1
    for row in rows:
        row["status"] = "IDENTITY_PARSED" if not row["reasons"] else ("READ_FAIL" if row["error"] else "REVIEW")

    review = [r for r in rows if r["status"] != "IDENTITY_PARSED"]
    result = {
        "format": FORMAT,
        "status": "PASS",
        "audit_completed": True,
        "server_root": str(server_root),
        "item_definition_count": len(rows),
        "identity_parsed_count": sum(1 for r in rows if r["status"] == "IDENTITY_PARSED"),
        "review_count": len(review),
        "unique_code_count": len(code_to_rows),
        "duplicate_code_count": len(duplicate_codes),
        "duplicate_codes": dict(list(sorted(duplicate_codes.items()))[:sample_limit]),
        "encoding_counts": dict(sorted(enc_counts.items())),
        "identity_basis_counts": dict(sorted(identity_basis_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "review_sample": review[:sample_limit],
        "rows": rows,
        "scope": {
            "confirmed_here": [
                "OpenItem TXT decode",
                "explicit CODE extraction",
                "OpenItem filename-code identity fallback from final enrichment corpus",
                "literal ZHOON presence relative to definition directory",
                "duplicate CODE detection",
            ],
            "filename_code_is_not_visual_mapping": True,
            "not_yet_claimed": ["server item-code map semantic resolution", "client item catalog resolution", "DorpItem/model/icon closure", "drop/shop reverse references"],
            "authoring_certification": False,
        },
        "server_write_authorized": False,
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
