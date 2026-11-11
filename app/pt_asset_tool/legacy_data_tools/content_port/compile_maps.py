#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

MAGIC = b"SMAP"
VERSION = 1
HEADER_SIZE = 128
PROFILE_CODES = {"client": 1, "server": 2}
FEATURE_BITS = {"worldcup_field": 1 << 0}
NULL_STRING_OFFSET = 0xFFFFFFFF

MAP_RECORD = struct.Struct("<28I")
STAGE_OBJECT_RECORD = struct.Struct("<4I")
START_POINT_RECORD = struct.Struct("<2i")
GATE_RECORD = struct.Struct("<4i")
WARP_GATE_RECORD = struct.Struct("<9i")
WARP_OUT_RECORD = struct.Struct("<4i")
AMBIENT_RECORD = struct.Struct("<5i")


class StringTable:
    def __init__(self) -> None:
        self.data = bytearray(b"\0")
        self.offsets: dict[str, int] = {"": 0}

    def intern(self, value: str) -> int:
        if value in self.offsets:
            return self.offsets[value]
        offset = len(self.data)
        self.offsets[value] = offset
        self.data.extend(value.encode("utf-8"))
        self.data.append(0)
        return offset


def _u32(value: int) -> int:
    return int(value) & 0xFFFFFFFF


def _feature_mask(features: dict | None, key: str) -> int:
    mask = 0
    for name in (features or {}).get(key, []):
        try:
            mask |= FEATURE_BITS[name]
        except KeyError as exc:
            raise ValueError(f"unknown map feature: {name}") from exc
    return mask


def _legacy_orphan_limit(map_doc: dict) -> tuple[int, int]:
    present = 0
    value = 0
    for item in map_doc.get("legacy_orphan_warp_properties", []):
        prop = item.get("property")
        if prop != "LimitLevel":
            raise ValueError(f"unsupported orphan warp property: {prop}")
        if present:
            raise ValueError("multiple orphan LimitLevel values are not supported by SMAP v1")
        present = 1
        value = int(item["legacy_value"])
    return present, value


def compile_catalog(doc: dict) -> tuple[bytes, dict]:
    if doc.get("schema") != "summit.map-catalog/v1":
        raise ValueError("input is not summit.map-catalog/v1")
    profile = doc.get("profile")
    if profile not in PROFILE_CODES:
        raise ValueError(f"unsupported profile: {profile!r}")

    maps = doc.get("maps") or []
    if int(doc.get("map_count", len(maps))) != len(maps):
        raise ValueError("map_count does not match maps array")
    if not maps:
        raise ValueError("map catalog is empty")

    strings = StringTable()
    map_records: list[tuple[int, ...]] = []
    stage_objects: list[tuple[int, ...]] = []
    start_points: list[tuple[int, ...]] = []
    gates: list[tuple[int, ...]] = []
    warp_gates: list[tuple[int, ...]] = []
    warp_out_gates: list[tuple[int, ...]] = []
    ambient: list[tuple[int, ...]] = []

    seen_codes: set[int] = set()
    feature_mask = 0

    for map_doc in maps:
        field_code = int(map_doc["legacy_field_code"])
        if field_code in seen_codes:
            raise ValueError(f"duplicate legacy_field_code: {field_code}")
        seen_codes.add(field_code)

        stage_object_start = len(stage_objects)
        for item in map_doc.get("stage_objects", []):
            features = item.get("features") or {}
            require = _feature_mask(features, "require")
            forbid = _feature_mask(features, "forbid")
            feature_mask |= require | forbid
            stage_objects.append((
                strings.intern(str(item["asset"])),
                _u32(item.get("bip_animation", 0)),
                require,
                forbid,
            ))

        start_point_start = len(start_points)
        for item in map_doc.get("start_points", []):
            start_points.append((int(item["x"]), int(item["z"])))

        gate_start = len(gates)
        for item in map_doc.get("gates", []):
            gates.append((
                int(item["legacy_target_code"]), int(item["x"]),
                int(item["z"]), int(item["y"]),
            ))

        warp_gate_start = len(warp_gates)
        for item in map_doc.get("warp_gates", []):
            warp_out_start = len(warp_out_gates)
            out_gates = item.get("out_gates", [])
            for out in out_gates:
                warp_out_gates.append((
                    int(out["legacy_target_code"]), int(out["x"]),
                    int(out["z"]), int(out["y"]),
                ))
            warp_gates.append((
                int(item["x"]), int(item["z"]), int(item["y"]),
                int(item["size"]), int(item["height"]),
                int(item["limit_level"]), int(item["special_effect"]),
                warp_out_start, len(out_gates),
            ))

        ambient_start = len(ambient)
        for item in map_doc.get("ambient", []):
            ambient.append((
                int(item["x"]), int(item["y"]), int(item["z"]),
                int(item["round"]), int(item["sound_code"]),
            ))

        env = map_doc["environment"]
        sky = env["sky"]
        if len(sky) != 3:
            raise ValueError(f"field {field_code} must have exactly three sky codes")
        orphan_present, orphan_limit = _legacy_orphan_limit(map_doc)

        # SMAP v1 keeps the historical deterministic string-intern order:
        # child assets first, then map id, stage path and optional map-image id.
        id_offset = strings.intern(str(map_doc["id"]))
        stage_offset_string = strings.intern(str(map_doc["stage"]))
        map_image = map_doc.get("map_image_id")
        map_image_offset = NULL_STRING_OFFSET if map_image is None else strings.intern(str(map_image))

        map_records.append((
            _u32(field_code),
            id_offset,
            stage_offset_string,
            map_image_offset,
            _u32(env["state"]["legacy_value"]),
            _u32(sky[0]["legacy_value"]),
            _u32(sky[1]["legacy_value"]),
            _u32(sky[2]["legacy_value"]),
            _u32(env["music"]["legacy_value"]),
            _u32(env["event"]["legacy_value"]),
            _u32(map_doc["server"]["routing"]["legacy_value"]),
            _u32(map_doc["limit_level"]),
            _u32(map_doc["field_sight"]),
            _u32(map_doc["center"]["x"]),
            _u32(map_doc["center"]["z"]),
            stage_object_start, len(map_doc.get("stage_objects", [])),
            start_point_start, len(map_doc.get("start_points", [])),
            gate_start, len(map_doc.get("gates", [])),
            warp_gate_start, len(map_doc.get("warp_gates", [])),
            ambient_start, len(map_doc.get("ambient", [])),
            orphan_present, _u32(orphan_limit), 0,
        ))

    def pack_rows(fmt: struct.Struct, rows: list[tuple[int, ...]]) -> bytes:
        return b"".join(fmt.pack(*row) for row in rows)

    map_blob = pack_rows(MAP_RECORD, map_records)
    stage_blob = pack_rows(STAGE_OBJECT_RECORD, stage_objects)
    start_blob = pack_rows(START_POINT_RECORD, start_points)
    gate_blob = pack_rows(GATE_RECORD, gates)
    warp_blob = pack_rows(WARP_GATE_RECORD, warp_gates)
    out_blob = pack_rows(WARP_OUT_RECORD, warp_out_gates)
    ambient_blob = pack_rows(AMBIENT_RECORD, ambient)

    map_offset = HEADER_SIZE
    stage_offset = map_offset + len(map_blob)
    start_offset = stage_offset + len(stage_blob)
    gate_offset = start_offset + len(start_blob)
    warp_offset = gate_offset + len(gate_blob)
    warp_out_offset = warp_offset + len(warp_blob)
    ambient_offset = warp_out_offset + len(out_blob)
    string_offset = ambient_offset + len(ambient_blob)

    body = b"".join((map_blob, stage_blob, start_blob, gate_blob, warp_blob, out_blob, ambient_blob, bytes(strings.data)))
    body_hash = hashlib.sha256(body).digest()

    static_field_count = max(seen_codes) + 1
    expected_codes = set(range(static_field_count))
    if seen_codes != expected_codes:
        raise ValueError("legacy_field_code range must be contiguous from 0")
    if static_field_count > 255:
        raise ValueError("at most 255 static fields are supported while the legacy custom field is enabled")

    dynamic = doc.get("legacy_dynamic_field") or {}
    strategy = dynamic.get("strategy", "append_after_static")
    if strategy != "append_after_static":
        raise ValueError(f"unsupported legacy_dynamic_field strategy: {strategy!r}")
    dynamic_field_code = static_field_count

    header = bytearray(HEADER_SIZE)
    struct.pack_into("<4sHH", header, 0, MAGIC, VERSION, HEADER_SIZE)
    struct.pack_into(
        "<22I", header, 8,
        PROFILE_CODES[profile], 0,
        len(map_records), map_offset,
        len(stage_objects), stage_offset,
        len(start_points), start_offset,
        len(gates), gate_offset,
        len(warp_gates), warp_offset,
        len(warp_out_gates), warp_out_offset,
        len(ambient), ambient_offset,
        string_offset, len(strings.data),
        dynamic_field_code, static_field_count,
        feature_mask, 0,
    )
    header[96:128] = body_hash
    pack = bytes(header) + body

    report = {
        "schema": "summit.compiled-map-report/v1",
        "format": "SMAP",
        "version": VERSION,
        "profile": profile,
        "sha256_body": body_hash.hex(),
        "maps": len(map_records),
        "stage_objects": len(stage_objects),
        "start_points": len(start_points),
        "gates": len(gates),
        "warp_gates": len(warp_gates),
        "warp_out_gates": len(warp_out_gates),
        "ambient": len(ambient),
        "strings_bytes": len(strings.data),
        "bytes": len(pack),
        "features": {name: 1 if feature_mask & bit else 0 for name, bit in FEATURE_BITS.items()},
        "dynamic_field_code": dynamic_field_code,
        "static_field_count": static_field_count,
    }
    return pack, report


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile summit.map-catalog/v1 JSON into SMAP v1")
    ap.add_argument("catalog", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    doc = json.loads(args.catalog.read_text(encoding="utf-8"))
    pack, report = compile_catalog(doc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pack)
    report_path = args.report or args.output.with_suffix(args.output.suffix + ".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
