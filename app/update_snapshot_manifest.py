#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "pt_build"}
EXCLUDED_FILES = {"SNAPSHOT_SHA256SUMS.txt"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _mutable_paths(root: Path) -> set[str]:
    path = root / "SNAPSHOT_MUTABLE_PATHS.txt"
    if not path.is_file():
        return set()
    return {
        line.strip().replace("\\", "/")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def collect_rows(root: Path) -> list[tuple[str, str]]:
    mutable = _mutable_paths(root)
    rows: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if any(part in EXCLUDED_PARTS for part in parts):
            continue
        if path.name.endswith(".pyc") or rel in EXCLUDED_FILES or rel in mutable:
            continue
        rows.append((rel, sha256(path)))
    rows.sort()
    return rows


def read_manifest(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            digest, rel = raw.split(None, 1)
        except ValueError as exc:
            raise ValueError(f"MALFORMED_LINE:{lineno}:{raw}") from exc
        expected[rel.strip().lstrip("*")] = digest.strip()
    return expected


def check_manifest(root: Path, manifest: Path) -> int:
    if not manifest.is_file():
        print(f"SNAPSHOT_MANIFEST_CHECK=FAIL reason=MISSING_MANIFEST path={manifest}")
        return 1
    try:
        expected = read_manifest(manifest)
    except ValueError as exc:
        print(f"SNAPSHOT_MANIFEST_CHECK=FAIL reason={exc}")
        return 1
    actual = dict(collect_rows(root))

    problems = 0
    for rel in sorted(expected.keys() - actual.keys()):
        print(f"SNAPSHOT_MANIFEST_MISSING path={rel} expected={expected[rel]}")
        problems += 1
    for rel in sorted(actual.keys() - expected.keys()):
        print(f"SNAPSHOT_MANIFEST_EXTRA path={rel} actual={actual[rel]}")
        problems += 1
    for rel in sorted(expected.keys() & actual.keys()):
        if expected[rel] != actual[rel]:
            print(
                "SNAPSHOT_MANIFEST_MISMATCH "
                f"path={rel} expected={expected[rel]} actual={actual[rel]}"
            )
            problems += 1
    if problems:
        print(f"SNAPSHOT_MANIFEST_CHECK=FAIL problems={problems}")
        return 1
    print(f"SNAPSHOT_MANIFEST_CHECK=PASS files={len(actual)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate or verify the current static package SHA-256 manifest.")
    ap.add_argument("--current-root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--check", action="store_true", help="Compare the static tree with the existing manifest without changing it.")
    args = ap.parse_args()
    root = args.current_root.resolve()
    out = root / "SNAPSHOT_SHA256SUMS.txt"
    if args.check:
        return check_manifest(root, out)
    rows = collect_rows(root)
    out.write_text("".join(f"{digest}  {rel}\n" for rel, digest in rows), encoding="utf-8")
    print(f"SNAPSHOT_MANIFEST_UPDATED files={len(rows)} path={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
