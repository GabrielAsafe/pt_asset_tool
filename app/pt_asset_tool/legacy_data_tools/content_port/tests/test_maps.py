#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compile_maps import compile_catalog
from inspect_maps import inspect



def assert_content_driven_field_count(doc: dict) -> None:
    expanded = copy.deepcopy(doc)
    extra = copy.deepcopy(expanded["maps"][-1])
    extra["id"] = "map.test_53"
    extra["legacy_field_code"] = 53
    expanded["maps"].append(extra)
    expanded["map_count"] = len(expanded["maps"])
    pack, report = compile_catalog(expanded)
    assert report["maps"] == 54
    assert report["static_field_count"] == 54
    assert report["dynamic_field_code"] == 54

    broken = copy.deepcopy(expanded)
    broken["maps"][-1]["legacy_field_code"] = 54
    try:
        compile_catalog(broken)
    except ValueError as exc:
        assert "contiguous" in str(exc)
    else:
        raise AssertionError("gapped legacy field codes must be rejected")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-catalog", type=Path, required=True)
    ap.add_argument("--server-catalog", type=Path, required=True)
    ap.add_argument("--client-reference", type=Path)
    ap.add_argument("--server-reference", type=Path)
    ap.add_argument("--tmp", type=Path, required=True)
    args = ap.parse_args()
    args.tmp.mkdir(parents=True, exist_ok=True)

    for side in ("client", "server"):
        catalog_path = getattr(args, f"{side}_catalog")
        reference = getattr(args, f"{side}_reference")
        doc = json.loads(catalog_path.read_text(encoding="utf-8"))
        pack, report = compile_catalog(doc)
        out = args.tmp / f"maps_{side}.smap"
        out.write_bytes(pack)
        info = inspect(out)
        assert report["maps"] == 53
        assert report["static_field_count"] == 53
        assert report["dynamic_field_code"] == 53
        assert_content_driven_field_count(doc)
        assert info["sha256_body_valid"] is True
        assert info["profile"] == side
        if reference:
            ref = reference.read_bytes()
            assert pack == ref, f"{side} SMAP is not byte-identical to reference"
            assert hashlib.sha256(pack).digest() == hashlib.sha256(ref).digest()

    print("PASS map compiler/inspector tests")


if __name__ == "__main__":
    main()
