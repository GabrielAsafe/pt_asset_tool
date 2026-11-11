#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

HEADER = struct.Struct("<4sHH22I32s")
PROFILE_NAMES = {1: "client", 2: "server"}


def inspect(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 128:
        raise ValueError("SMAP is smaller than its fixed header")
    values = HEADER.unpack_from(data, 0)
    magic, version, header_size = values[:3]
    ints = values[3:-1]
    digest = values[-1]
    if magic != b"SMAP":
        raise ValueError("SMAP magic mismatch")
    if version != 1 or header_size != 128:
        raise ValueError(f"unsupported SMAP version/header: {version}/{header_size}")
    (profile, flags,
     map_count, map_offset,
     stage_count, stage_offset,
     start_count, start_offset,
     gate_count, gate_offset,
     warp_count, warp_offset,
     out_count, out_offset,
     ambient_count, ambient_offset,
     string_offset, string_size,
     dynamic_field_code, static_field_count,
     feature_mask, reserved) = ints
    body_hash = hashlib.sha256(data[header_size:]).digest()
    return {
        "format": "SMAP",
        "version": version,
        "header_size": header_size,
        "profile": PROFILE_NAMES.get(profile, f"unknown:{profile}"),
        "flags": flags,
        "maps": {"count": map_count, "offset": map_offset},
        "stage_objects": {"count": stage_count, "offset": stage_offset},
        "start_points": {"count": start_count, "offset": start_offset},
        "gates": {"count": gate_count, "offset": gate_offset},
        "warp_gates": {"count": warp_count, "offset": warp_offset},
        "warp_out_gates": {"count": out_count, "offset": out_offset},
        "ambient": {"count": ambient_count, "offset": ambient_offset},
        "strings": {"offset": string_offset, "bytes": string_size},
        "dynamic_field_code": dynamic_field_code,
        "static_field_count": static_field_count,
        "feature_mask": feature_mask,
        "reserved": reserved,
        "sha256_body": digest.hex(),
        "sha256_body_valid": body_hash == digest,
        "bytes": len(data),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", type=Path)
    args = ap.parse_args()
    print(json.dumps(inspect(args.pack), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
