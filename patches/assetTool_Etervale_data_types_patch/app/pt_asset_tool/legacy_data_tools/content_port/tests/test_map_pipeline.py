#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compile_maps import compile_catalog
from extract_legacy_maps import parse as extract_legacy_maps
from inspect_maps import inspect
from semanticize_maps import semanticize

EXPECTED_SHA256 = {
    "client": "90f928416d844c291c5f47fcf08d012bf7cee78225c2bd0a3f53a4bd697bd7cc",
    "server": "9aad78031a1ee066954de956f151c95887cb867e182c135577c5cc0d2b0ef3c0",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--tmp", type=Path, required=True)
    ap.add_argument("--client-reference", type=Path)
    ap.add_argument("--server-reference", type=Path)
    args = ap.parse_args()
    args.tmp.mkdir(parents=True, exist_ok=True)

    for profile in ("client", "server"):
        source = args.source_root / f"Shared/world/field/field_legacy_{profile}.inl"
        shadow = extract_legacy_maps(source)
        tagged = [
            op for item in shadow["maps"][:53] for op in item.get("operations", [])
            if op.get("condition_cpp") == "defined(WORLDCUP_FIELD)"
        ]
        assert len(tagged) == 11, f"{profile}: expected 11 WORLDCUP_FIELD operations"
        catalog = semanticize(shadow, profile, args.source_root, source)
        assert catalog["map_count"] == 53
        assert catalog["legacy_dynamic_field"] == {"strategy": "append_after_static"}
        assert [m["legacy_field_code"] for m in catalog["maps"]] == list(range(53))
        expected_source = f"Shared/world/field/field_legacy_{profile}.inl"
        provenance_sources = {m["provenance"]["source"] for m in catalog["maps"]}
        assert provenance_sources == {expected_source}, (profile, provenance_sources)
        assert not expected_source.startswith("/"), expected_source
        pack, report = compile_catalog(catalog)
        out = args.tmp / f"maps_{profile}.smap"
        out.write_bytes(pack)
        info = inspect(out)
        assert info["profile"] == profile
        assert info["maps"]["count"] == 53
        assert info["static_field_count"] == 53
        assert info["dynamic_field_code"] == 53
        assert info["feature_mask"] == 1
        assert info["sha256_body_valid"] is True
        digest = hashlib.sha256(pack).hexdigest()
        assert digest == EXPECTED_SHA256[profile], f"{profile}: unexpected SMAP golden hash {digest}"
        reference = getattr(args, f"{profile}_reference")
        if reference:
            assert pack == reference.read_bytes(), f"{profile}: source-derived SMAP differs from reference"
        assert report["features"]["worldcup_field"] == 1

    print("PASS source -> semantic map catalog -> SMAP v1 pipeline")


if __name__ == "__main__":
    main()
