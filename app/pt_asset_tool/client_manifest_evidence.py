from __future__ import annotations

import csv
import datetime as _dt
import json
import pathlib
import struct
from collections import Counter
from typing import Any, Iterable

FORMAT = "PT_ASSET_CLIENT_MANIFEST_EVIDENCE_V1"
MAGIC = 0x3801
RECORD_SIZE = 88
HEADER_SIZE = 8
TRAILER_SIZE = 20
PATH_FIELD_SIZE = 64


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _decode_path(raw: bytes) -> str:
    for enc in ("utf-8", "cp949", "cp1252", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1", errors="replace")


def _filetime_iso(value: int) -> str | None:
    # Windows FILETIME: 100ns ticks since 1601-01-01 UTC.
    if value <= 0:
        return None
    try:
        unix_100ns = value - 116444736000000000
        seconds = unix_100ns / 10_000_000
        dt = _dt.datetime.fromtimestamp(seconds, tz=_dt.timezone.utc)
        if dt.year < 1980 or dt.year > 2200:
            return None
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def parse_fixed_manifest(path: str | pathlib.Path) -> dict[str, Any]:
    p = pathlib.Path(path)
    data = p.read_bytes()
    result: dict[str, Any] = {
        "path": str(p),
        "status": "INVALID",
        "magic": None,
        "record_count": 0,
        "records": [],
        "boundary_count": 0,
        "extension_counts": {},
    }
    if len(data) < HEADER_SIZE:
        result["error"] = "MANIFEST_TOO_SMALL"
        return result
    magic, count = struct.unpack_from("<II", data, 0)
    result["magic"] = magic
    result["record_count"] = count
    expected = HEADER_SIZE + count * RECORD_SIZE
    # The observed format has a 20-byte trailer, but accepting extra trailer
    # bytes keeps the parser evidence-only and resilient to updater revisions.
    if magic != MAGIC:
        result["error"] = f"MAGIC_MISMATCH:{magic:#x}"
        return result
    if count > 10_000_000 or expected > len(data):
        result["error"] = f"LAYOUT_INVALID:size={len(data)} count={count} expected_min={expected}"
        return result

    rows: list[dict[str, Any]] = []
    exts = Counter()
    boundary_count = 0
    for i in range(count):
        off = HEADER_SIZE + i * RECORD_SIZE
        rec = data[off:off + RECORD_SIZE]
        flag = struct.unpack_from("<I", rec, 0)[0]
        path_field = rec[4:68]
        nul = path_field.find(b"\0")
        if nul >= 0:
            raw_path = path_field[:nul]
            terminated = True
        else:
            raw_path = path_field
            terminated = False
        text = _decode_path(raw_path).strip()
        rel = _norm(text)
        size = struct.unpack_from("<I", rec, 68)[0]
        reserved = struct.unpack_from("<I", rec, 72)[0]
        filetime = struct.unpack_from("<Q", rec, 76)[0]
        final_u32 = struct.unpack_from("<I", rec, 84)[0]
        # 63+ bytes is unsafe as exact evidence: the supplied path can have been
        # clipped at the fixed field boundary, as observed for MartialArtist .part.
        boundary = (not terminated) or len(raw_path) >= PATH_FIELD_SIZE - 1
        if boundary:
            boundary_count += 1
        ext = pathlib.PurePosixPath(rel).suffix.casefold() if rel else ""
        exts[ext or "<none>"] += 1
        rows.append({
            "record": i,
            "flag": flag,
            "path": rel,
            "canonical_path": rel.casefold(),
            "path_bytes": len(raw_path),
            "path_terminated": terminated,
            "path_boundary_risk": boundary,
            "evidence_strength": "TRUNCATED_PREFIX_REVIEW" if boundary else "MANIFEST_EXACT",
            "file_size": size,
            "reserved_u32": reserved,
            "filetime_u64": filetime,
            "filetime_iso": _filetime_iso(filetime),
            "final_u32_unknown": final_u32,
        })

    result.update({
        "status": "PASS",
        "records": rows,
        "boundary_count": boundary_count,
        "extension_counts": dict(sorted(exts.items())),
        "trailer_bytes": len(data) - expected,
        "canonical_20_byte_trailer": len(data) - expected == TRAILER_SIZE,
        "policy": {
            "manifest_presence_is_positive_evidence_only": True,
            "manifest_absence_does_not_disprove_runtime_need": True,
            "boundary_paths_are_not_exact_path_evidence": True,
            "final_u32_semantics_claimed": False,
        },
    })
    return result


def audit_client_manifests(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    *,
    filenames: Iterable[str] = ("setfile.lst", "_update.inf"),
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    out_dir = project / "pt_build" / "general_asset_census" / "manifest_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for name in filenames:
        p = client / name
        if not p.is_file():
            reports.append({"name": name, "path": str(p), "status": "NOT_PRESENT", "record_count": 0})
            continue
        try:
            parsed = parse_fixed_manifest(p)
        except Exception as exc:
            parsed = {"name": name, "path": str(p), "status": "ERROR", "error": f"{type(exc).__name__}:{exc}", "record_count": 0, "records": []}
        parsed["name"] = name
        for row in parsed.pop("records", []):
            all_rows.append({"manifest": name, **row})
        reports.append(parsed)

    tsv = out_dir / "manifest_paths.tsv"
    fields = [
        "manifest", "record", "flag", "path", "canonical_path", "path_bytes", "path_terminated",
        "path_boundary_risk", "evidence_strength", "file_size", "reserved_u32", "filetime_u64",
        "filetime_iso", "final_u32_unknown",
    ]
    with tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    exact = {r["canonical_path"] for r in all_rows if r.get("evidence_strength") == "MANIFEST_EXACT" and r.get("canonical_path")}
    boundary = [r for r in all_rows if r.get("path_boundary_risk")]
    result = {
        "format": FORMAT,
        "status": "PASS",
        "client_root": str(client),
        "manifest_count": len(reports),
        "parsed_manifest_count": sum(1 for x in reports if x.get("status") == "PASS"),
        "record_count": len(all_rows),
        "exact_path_count": len(exact),
        "boundary_path_count": len(boundary),
        "manifests": reports,
        "paths_tsv": str(tsv),
        "client_write_authorized": False,
        "server_write_authorized": False,
        "production_authorized": False,
    }
    report = out_dir / "result.json"
    result["report"] = str(report)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
