from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable

from .ui_catalog import infer_semantics

VERSION = "1.0.0"
FORMAT = "PT_ASSET_TREE_COMPARE_V2"
DIFFERENCE_STATUSES = {"ONLY_LEFT", "ONLY_RIGHT", "DIFFERENT_SIZE", "DIFFERENT_SHA256"}


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class FileInfo:
    rel: str
    size: int
    mtime_ns: int
    ext: str
    category: str


def _normalize_exts(values: Iterable[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in values or []:
        for value in str(raw).split(","):
            value = value.strip().lower()
            if not value:
                continue
            if not value.startswith("."):
                value = "." + value
            out.add(value)
    return out


def _matches_filters(
    rel: str,
    *,
    extensions: set[str],
    category: str,
    path_contains: str,
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
) -> tuple[bool, str, str]:
    ext = pathlib.PurePosixPath(rel).suffix.lower()
    inferred_category, _ = infer_semantics(rel, ext)
    if extensions and ext not in extensions:
        return False, ext, inferred_category
    if category and inferred_category.upper() != category:
        return False, ext, inferred_category
    if path_contains and path_contains.casefold() not in rel.casefold():
        return False, ext, inferred_category
    low = rel.casefold()
    if include_globs and not any(fnmatch.fnmatchcase(low, g.casefold()) for g in include_globs):
        return False, ext, inferred_category
    if exclude_globs and any(fnmatch.fnmatchcase(low, g.casefold()) for g in exclude_globs):
        return False, ext, inferred_category
    return True, ext, inferred_category


def _iter_files(
    root: pathlib.Path,
    include_hidden: bool,
    *,
    extensions: set[str],
    category: str,
    path_contains: str,
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
) -> list[FileInfo]:
    out: list[FileInfo] = []
    for base, dirs, files in os.walk(root):
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        bp = pathlib.Path(base)
        for name in files:
            if not include_hidden and name.startswith("."):
                continue
            p = bp / name
            try:
                if not p.is_file():
                    continue
                st = p.stat()
                rel = p.relative_to(root).as_posix()
            except OSError:
                continue
            keep, ext, inferred_category = _matches_filters(
                rel,
                extensions=extensions,
                category=category,
                path_contains=path_contains,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
            )
            if not keep:
                continue
            out.append(FileInfo(rel, int(st.st_size), int(st.st_mtime_ns), ext, inferred_category))
    out.sort(key=lambda x: x.rel.casefold())
    return out


def _index(files: list[FileInfo], case_sensitive: bool) -> tuple[dict[str, FileInfo], dict[str, list[str]]]:
    idx: dict[str, FileInfo] = {}
    collisions: dict[str, list[str]] = {}
    for f in files:
        k = f.rel if case_sensitive else f.rel.casefold()
        if k in idx and idx[k].rel != f.rel:
            collisions.setdefault(k, [idx[k].rel]).append(f.rel)
        else:
            idx[k] = f
    return idx, collisions


def compare_trees(
    left: pathlib.Path,
    right: pathlib.Path,
    *,
    content_hash: bool = False,
    case_sensitive: bool = False,
    include_hidden: bool = False,
    extensions: Iterable[str] | None = None,
    category: str = "",
    path_contains: str = "",
    include_globs: Iterable[str] | None = None,
    exclude_globs: Iterable[str] | None = None,
    differences_only: bool = False,
) -> dict[str, Any]:
    left = left.expanduser().resolve()
    right = right.expanduser().resolve()
    if not left.is_dir():
        raise FileNotFoundError(f"LEFT_ROOT_NOT_DIRECTORY:{left}")
    if not right.is_dir():
        raise FileNotFoundError(f"RIGHT_ROOT_NOT_DIRECTORY:{right}")
    if left == right:
        raise ValueError("TREE_ROOTS_MUST_DIFFER")

    exts = _normalize_exts(extensions)
    cat = str(category or "").strip().upper()
    path_filter = str(path_contains or "").strip()
    inc = tuple(str(x).strip() for x in (include_globs or []) if str(x).strip())
    exc = tuple(str(x).strip() for x in (exclude_globs or []) if str(x).strip())

    lf = _iter_files(
        left, include_hidden,
        extensions=exts, category=cat, path_contains=path_filter,
        include_globs=inc, exclude_globs=exc,
    )
    rf = _iter_files(
        right, include_hidden,
        extensions=exts, category=cat, path_contains=path_filter,
        include_globs=inc, exclude_globs=exc,
    )
    li, lc = _index(lf, case_sensitive)
    ri, rc = _index(rf, case_sensitive)

    keys = sorted(set(li) | set(ri))
    all_rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "ONLY_LEFT": 0,
        "ONLY_RIGHT": 0,
        "SAME_SIZE": 0,
        "DIFFERENT_SIZE": 0,
        "SAME_SHA256": 0,
        "DIFFERENT_SHA256": 0,
    }
    hashed_bytes = 0
    for k in keys:
        a = li.get(k)
        b = ri.get(k)
        basis = a or b
        base = {
            "key": k,
            "extension": basis.ext if basis else "",
            "category": basis.category if basis else "OTHER",
        }
        if a is None:
            status = "ONLY_RIGHT"
            row = {**base, "status": status, "left_path": None, "right_path": b.rel, "left_size": None, "right_size": b.size}
        elif b is None:
            status = "ONLY_LEFT"
            row = {**base, "status": status, "left_path": a.rel, "right_path": None, "left_size": a.size, "right_size": None}
        elif a.size != b.size:
            status = "DIFFERENT_SIZE"
            row = {**base, "status": status, "left_path": a.rel, "right_path": b.rel, "left_size": a.size, "right_size": b.size}
            if content_hash:
                ah = sha256_file(left / a.rel)
                bh = sha256_file(right / b.rel)
                hashed_bytes += a.size + b.size
                row["left_sha256"] = ah
                row["right_sha256"] = bh
        elif content_hash:
            ah = sha256_file(left / a.rel)
            bh = sha256_file(right / b.rel)
            hashed_bytes += a.size + b.size
            status = "SAME_SHA256" if ah == bh else "DIFFERENT_SHA256"
            row = {
                **base,
                "status": status,
                "left_path": a.rel,
                "right_path": b.rel,
                "left_size": a.size,
                "right_size": b.size,
                "left_sha256": ah,
                "right_sha256": bh,
            }
        else:
            status = "SAME_SIZE"
            row = {**base, "status": status, "left_path": a.rel, "right_path": b.rel, "left_size": a.size, "right_size": b.size}
        counts[status] += 1
        all_rows.append(row)

    rows = [r for r in all_rows if r["status"] in DIFFERENCE_STATUSES] if differences_only else all_rows
    common = len(set(li) & set(ri))
    same_content = counts["SAME_SHA256"] if content_hash else None
    different_content = (counts["DIFFERENT_SHA256"] + counts["DIFFERENT_SIZE"]) if content_hash else None
    left_bytes = sum(x.size for x in lf)
    right_bytes = sum(x.size for x in rf)
    return {
        "format": FORMAT,
        "status": "PASS",
        "version": VERSION,
        "left_root": str(left),
        "right_root": str(right),
        "read_only": True,
        "case_sensitive": case_sensitive,
        "content_hash": content_hash,
        "include_hidden": include_hidden,
        "differences_only": differences_only,
        "filters": {
            "extensions": sorted(exts),
            "category": cat or None,
            "path_contains": path_filter or None,
            "include_globs": list(inc),
            "exclude_globs": list(exc),
        },
        "summary": {
            "left_file_count": len(lf),
            "right_file_count": len(rf),
            "left_total_bytes": left_bytes,
            "right_total_bytes": right_bytes,
            "common_path_count": common,
            "only_left_count": counts["ONLY_LEFT"],
            "only_right_count": counts["ONLY_RIGHT"],
            "same_size_unhashed_count": counts["SAME_SIZE"],
            "different_size_count": counts["DIFFERENT_SIZE"],
            "same_sha256_count": counts["SAME_SHA256"],
            "different_sha256_count": counts["DIFFERENT_SHA256"],
            "same_content_count": same_content,
            "different_content_count": different_content,
            "difference_path_count": counts["ONLY_LEFT"] + counts["ONLY_RIGHT"] + counts["DIFFERENT_SIZE"] + counts["DIFFERENT_SHA256"],
            "displayed_row_count": len(rows),
            "left_case_collision_count": len(lc),
            "right_case_collision_count": len(rc),
            "hashed_bytes": hashed_bytes,
        },
        "left_case_collisions": lc,
        "right_case_collisions": rc,
        "rows": rows,
    }


def write_outputs(report: dict[str, Any], output: pathlib.Path) -> dict[str, str]:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fields = ["status", "category", "extension", "left_path", "right_path", "left_size", "right_size", "left_sha256", "right_sha256"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in report["rows"]:
            w.writerow({k: r.get(k, "") for k in fields})
    md = output.with_suffix(".md")
    s = report["summary"]
    filt = report.get("filters", {})
    lines = [
        "# PT Asset Tree Compare", "",
        f"- left: `{report['left_root']}`",
        f"- right: `{report['right_root']}`",
        f"- files after filters: {s['left_file_count']} vs {s['right_file_count']}",
        f"- bytes after filters: {s['left_total_bytes']} vs {s['right_total_bytes']}",
        f"- common paths: {s['common_path_count']}",
        f"- only left: {s['only_left_count']}",
        f"- only right: {s['only_right_count']}",
        f"- different size: {s['different_size_count']}",
        f"- difference paths: {s['difference_path_count']}",
        f"- displayed rows: {s['displayed_row_count']}",
        f"- SHA-256 enabled: {report['content_hash']}",
    ]
    if report["content_hash"]:
        lines += [f"- same SHA-256: {s['same_sha256_count']}", f"- different SHA-256: {s['different_sha256_count']}"]
    if any(v for v in filt.values() if v):
        lines += ["", "## Filters", "", "```json", json.dumps(filt, ensure_ascii=False, indent=2), "```"]
    lines += ["", "## Safety", "Comparison is read-only; no source tree writes are performed."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(output), "csv": str(csv_path), "markdown": str(md)}


def cli_main(argv: list[str] | None = None, *, project_root: pathlib.Path | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pt_asset.py compare trees",
        description="Compare two asset trees by relative path, size and optional SHA-256 with semantic/path filters",
    )
    ap.add_argument("--left", required=True)
    ap.add_argument("--right", required=True)
    ap.add_argument("--output", default="pt_build/tree_compare_v0120.json")
    ap.add_argument("--hash", dest="content_hash", action="store_true", help="SHA-256 common files to detect same-size byte differences")
    ap.add_argument("--case-sensitive", action="store_true")
    ap.add_argument("--include-hidden", action="store_true")
    ap.add_argument("--ext", action="append", default=[], help="Limit extensions; repeat or comma-separate, e.g. --ext smd --ext inx,inf")
    ap.add_argument("--category", default="", help="Limit inferred semantic category, e.g. CHARACTER, MONSTER, NPC, UI, ITEM, MAP, EFFECT")
    ap.add_argument("--path-contains", default="", help="Case-insensitive substring filter on relative path")
    ap.add_argument("--include-glob", action="append", default=[], help="Include relative paths matching glob; repeatable")
    ap.add_argument("--exclude-glob", action="append", default=[], help="Exclude relative paths matching glob; repeatable")
    ap.add_argument("--differences-only", action="store_true", help="Write only differing rows while preserving full summary counts")
    a = ap.parse_args(argv)
    root = (project_root or pathlib.Path.cwd()).resolve()
    out = pathlib.Path(a.output).expanduser()
    if not out.is_absolute():
        out = (root / out).resolve()
    else:
        out = out.resolve()
    left_root = pathlib.Path(a.left).expanduser().resolve()
    right_root = pathlib.Path(a.right).expanduser().resolve()
    for source_root in (left_root, right_root):
        if out == source_root or source_root in out.parents:
            fail = {"format": FORMAT, "status": "FAIL", "version": VERSION, "error": f"ValueError:OUTPUT_INSIDE_SOURCE_TREE:{out}:{source_root}", "read_only": True}
            print(json.dumps(fail, ensure_ascii=False, indent=2))
            return 2
    try:
        report = compare_trees(
            left_root,
            right_root,
            content_hash=a.content_hash,
            case_sensitive=a.case_sensitive,
            include_hidden=a.include_hidden,
            extensions=a.ext,
            category=a.category,
            path_contains=a.path_contains,
            include_globs=a.include_glob,
            exclude_globs=a.exclude_glob,
            differences_only=a.differences_only,
        )
        outputs = write_outputs(report, out)
        compact = {k: report[k] for k in ("format", "status", "version", "left_root", "right_root", "read_only", "case_sensitive", "content_hash", "differences_only", "filters")}
        compact["summary"] = report["summary"]
        compact["outputs"] = outputs
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        s = report["summary"]
        print(
            f"tree_compare=PASS left={s['left_file_count']} right={s['right_file_count']} "
            f"common={s['common_path_count']} only_left={s['only_left_count']} only_right={s['only_right_count']} "
            f"diff_size={s['different_size_count']} diff_sha={s['different_sha256_count']} displayed={s['displayed_row_count']} read_only=true"
        )
        return 0
    except Exception as exc:
        fail = {"format": FORMAT, "status": "FAIL", "version": VERSION, "error": f"{type(exc).__name__}:{exc}", "read_only": True}
        # Error reports are only written after source-tree output guards pass.
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(fail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(fail, ensure_ascii=False, indent=2))
        return 2
