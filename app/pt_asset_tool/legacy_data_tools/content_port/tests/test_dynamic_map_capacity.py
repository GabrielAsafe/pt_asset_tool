#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compile_maps import compile_catalog
from inspect_maps import inspect


def expanded_catalog(source: dict, count: int) -> dict:
    if count < len(source["maps"]):
        raise ValueError("test helper only expands catalogs")
    doc = copy.deepcopy(source)
    while len(doc["maps"]) < count:
        code = len(doc["maps"])
        extra = copy.deepcopy(doc["maps"][-1])
        extra["id"] = f"map.synthetic_{code}"
        extra["legacy_field_code"] = code
        extra["provenance"] = {"profile": doc["profile"], "source": "synthetic-capacity-test", "source_line": code}
        doc["maps"].append(extra)
    doc["map_count"] = len(doc["maps"])
    doc["legacy_dynamic_field"] = {"strategy": "append_after_static"}

    # Acceptance fixture: once field 53 exists as normal static content, an
    # existing warp may target it and field 53 may warp back into the old range.
    if count >= 54:
        field52 = doc["maps"][52]
        field53 = doc["maps"][53]
        if field52.get("warp_gates") and field52["warp_gates"][0].get("out_gates"):
            field52["warp_gates"][0]["out_gates"][0]["target"] = field53["id"]
            field52["warp_gates"][0]["out_gates"][0]["legacy_target_code"] = 53
        if field53.get("warp_gates") and field53["warp_gates"][0].get("out_gates"):
            field53["warp_gates"][0]["out_gates"][0]["target"] = doc["maps"][3]["id"]
            field53["warp_gates"][0]["out_gates"][0]["legacy_target_code"] = 3
    return doc


def assert_count(doc: dict, count: int, tmp: Path, emit_dir: Path | None = None) -> None:
    pack, report = compile_catalog(expanded_catalog(doc, count))
    out_dir = emit_dir if emit_dir is not None and count in (54, 70) else tmp
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"maps_{doc['profile']}_{count}.smap"
    path.write_bytes(pack)
    info = inspect(path)
    assert report["maps"] == count
    assert report["static_field_count"] == count
    assert report["dynamic_field_code"] == count
    assert info["maps"]["count"] == count
    assert info["static_field_count"] == count
    assert info["dynamic_field_code"] == count
    assert info["sha256_body_valid"] is True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-catalog", type=Path, required=True)
    ap.add_argument("--server-catalog", type=Path, required=True)
    ap.add_argument("--tmp", type=Path)
    ap.add_argument("--emit-dir", type=Path, help="keep 54/70-field fixture packs for C++ bridge tests")
    args = ap.parse_args()

    tmp = args.tmp or Path(tempfile.mkdtemp(prefix="summit-map-capacity-"))
    tmp.mkdir(parents=True, exist_ok=True)

    for path in (args.client_catalog, args.server_catalog):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert_count(doc, 54, tmp, args.emit_dir)
        assert_count(doc, 70, tmp, args.emit_dir)
        assert_count(doc, 255, tmp)

        too_many = expanded_catalog(doc, 256)
        try:
            compile_catalog(too_many)
        except ValueError as exc:
            assert "at most 255 static fields" in str(exc)
        else:
            raise AssertionError("256 static fields must be rejected while the custom field is reserved")

        gapped = expanded_catalog(doc, 54)
        gapped["maps"][-1]["legacy_field_code"] = 54
        try:
            compile_catalog(gapped)
        except ValueError as exc:
            assert "contiguous" in str(exc)
        else:
            raise AssertionError("gapped legacy field codes must be rejected")

    print("PASS dynamic map capacity: 54, 70, 255 static fields; 256/gapped rejected")


if __name__ == "__main__":
    main()
