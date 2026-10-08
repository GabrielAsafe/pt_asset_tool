#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from source_api_reference import REFERENCE, ROOT, render_reference


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate or verify the exhaustive maintained first-party Python source API reference.")
    ap.add_argument("--check", action="store_true", help="fail if the committed reference does not match the current source")
    args = ap.parse_args()
    expected = render_reference(ROOT)
    if args.check:
        if not REFERENCE.is_file():
            print(f"SOURCE_API_REFERENCE=FAIL missing={REFERENCE.relative_to(ROOT)}")
            return 1
        actual = REFERENCE.read_text(encoding="utf-8")
        if actual != expected:
            print(f"SOURCE_API_REFERENCE=FAIL stale={REFERENCE.relative_to(ROOT)}")
            return 1
        print("SOURCE_API_REFERENCE=PASS")
        return 0
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(expected, encoding="utf-8")
    print(f"SOURCE_API_REFERENCE=WRITTEN path={REFERENCE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
