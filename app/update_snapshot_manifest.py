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


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate the current static package SHA-256 manifest.")
    ap.add_argument("--current-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    root = args.current_root.resolve()
    mutable_path = root / "SNAPSHOT_MUTABLE_PATHS.txt"
    mutable = {
        line.strip().replace("\\", "/")
        for line in mutable_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
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
    out = root / "SNAPSHOT_SHA256SUMS.txt"
    out.write_text("".join(f"{digest}  {rel}\n" for rel, digest in rows), encoding="utf-8")
    print(f"SNAPSHOT_MANIFEST_UPDATED files={len(rows)} path={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
