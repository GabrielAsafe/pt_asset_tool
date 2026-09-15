from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import struct
import zipfile

from .stage072_corpus import (
    HEADER,
    DFILE_HEADER_SIZE,
    STAGE_HEADER_SIZE,
    STAGE_AREA_PTR_OFFSET,
    STAGE_AREA_PTR_COUNT,
    MAP_SIZE,
    STAGE_VERTEX_SIZE,
    STAGE_FACE_SIZE,
    TEXLINK_SIZE,
    LIGHT_SIZE,
    S_VERTEX_PTR,
    S_FACE_PTR,
    S_TEXLINK_PTR,
    S_LIGHT_PTR,
    S_NVERTEX,
    S_NFACE,
    S_NTEXLINK,
    S_NLIGHT,
    S_AREA_BUFF_PTR,
    S_WAREA_SIZE,
    S_STAGE_MAP_RECT,
    parse_stage072,
)
from .utils import norm_path

AREA_LIST_CAPACITY = 4096


def _i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _fixed_layout(data: bytes) -> dict:
    if len(data) < DFILE_HEADER_SIZE + STAGE_HEADER_SIZE:
        raise ValueError("Stage0.72 file too small")
    if not data.startswith(HEADER):
        raise ValueError("not SMD Stage data Ver 0.72")
    sh = DFILE_HEADER_SIZE
    stage = data[sh:sh + STAGE_HEADER_SIZE]
    nvertex = _i32(stage, S_NVERTEX)
    nface = _i32(stage, S_NFACE)
    ntex = _i32(stage, S_NTEXLINK)
    nlight = _i32(stage, S_NLIGHT)
    if min(nvertex, nface, ntex, nlight) < 0:
        raise ValueError("negative Stage0.72 count")
    mat_blob = _i32(data, 36) - _i32(data, 32)
    if mat_blob < 0:
        raise ValueError("negative material blob")
    material_start = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE
    vertex_base = material_start + mat_blob
    face_base = vertex_base + nvertex * STAGE_VERTEX_SIZE
    texlink_base = face_base + nface * STAGE_FACE_SIZE
    light_base = texlink_base + ntex * TEXLINK_SIZE
    area_base = light_base + nlight * LIGHT_SIZE
    if area_base > len(data):
        raise ValueError("fixed Stage0.72 payload exceeds EOF")
    return {
        "stage_header_start": sh,
        "stage_header_end": sh + STAGE_HEADER_SIZE,
        "material_start": material_start,
        "vertex_base": vertex_base,
        "face_base": face_base,
        "texlink_base": texlink_base,
        "light_base": light_base,
        "area_base": area_base,
        "nvertex": nvertex,
        "nface": nface,
        "ntexlink": ntex,
        "nlight": nlight,
    }


def _decode_area_width(data: bytes, stage: bytes, layout: dict, width: int) -> dict | None:
    if width not in (2, 4):
        raise ValueError(width)
    ptrs = struct.unpack_from(f"<{STAGE_AREA_PTR_COUNT}I", stage, STAGE_AREA_PTR_OFFSET)
    cursor = int(layout["area_base"])
    nface = int(layout["nface"])
    cells: dict[tuple[int, int], tuple[int, ...]] = {}
    slot_count = 0
    try:
        for y in range(MAP_SIZE):
            for x in range(MAP_SIZE):
                if ptrs[x * MAP_SIZE + y] == 0:
                    continue
                if cursor + 4 > len(data):
                    return None
                slen = _i32(data, cursor)
                cursor += 4
                if slen < 1 or cursor + slen * width > len(data):
                    return None
                code = "H" if width == 2 else "I"
                vals = struct.unpack_from(f"<{slen}{code}", data, cursor)
                cursor += slen * width
                if vals[0] != slen - 1:
                    return None
                if any(int(fi) < 0 or int(fi) >= nface for fi in vals[1:]):
                    return None
                cells[(x, y)] = tuple(int(fi) for fi in vals[1:])
                slot_count += slen
    except (ValueError, struct.error, OverflowError):
        return None
    return {
        "width": width,
        "cells": cells,
        "cursor": cursor,
        "serialized_slot_count": slot_count,
        "trailing_bytes": len(data) - cursor,
    }


def _choose_area_encoding(data: bytes, stage: bytes, layout: dict) -> dict:
    w = _decode_area_width(data, stage, layout, 2)
    d = _decode_area_width(data, stage, layout, 4)
    candidates = [x for x in (w, d) if x is not None]
    if not candidates:
        raise ValueError("StageArea physical encoding unresolved")
    closes = [x for x in candidates if int(x["trailing_bytes"]) == 0]
    if len(closes) == 1:
        chosen = closes[0]
    elif len(closes) > 1:
        # No shipped file is ambiguous, but refuse to silently choose.
        raise ValueError("StageArea encoding ambiguous: WORD16 and DWORD32 both close")
    else:
        # Runtime ignores EOF after its referenced StageArea core. Shipped
        # opaque-suffix cases are DWORD32; preserve the suffix verbatim.
        dwords = [x for x in candidates if int(x["width"]) == 4]
        if len(dwords) != 1 or int(dwords[0]["trailing_bytes"]) <= 0:
            raise ValueError("StageArea trailing encoding unresolved")
        chosen = dwords[0]
    width = int(chosen["width"])
    chosen = dict(chosen)
    chosen["encoding"] = (
        "WORD16" if width == 2 and int(chosen["trailing_bytes"]) == 0
        else "WORD16_TRAILING_OPAQUE" if width == 2
        else "DWORD32" if int(chosen["trailing_bytes"]) == 0
        else "DWORD32_TRAILING_OPAQUE"
    )
    return chosen


def _geometry_cells(data: bytes, layout: dict) -> dict:
    nv = int(layout["nvertex"])
    nf = int(layout["nface"])
    vb = int(layout["vertex_base"])
    fb = int(layout["face_base"])
    # SourceCode: Vertex fixed-point coordinate >> FLOATNS(8), then
    # getPolyAreas bbox coordinate >> 6. Right-shift is monotonic, so the
    # cell coordinate is exactly raw_fixed >> 14.
    cell_x = [0] * nv
    cell_z = [0] * nv
    raw_x = [0] * nv
    raw_z = [0] * nv
    for vi in range(nv):
        o = vb + vi * STAGE_VERTEX_SIZE
        x = _i32(data, o + 8)
        z = _i32(data, o + 16)
        raw_x[vi] = x
        raw_z[vi] = z
        cell_x[vi] = x >> 14
        cell_z[vi] = z >> 14

    cells: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    max_face_span = 0
    over_capacity_faces: list[dict] = []
    for fi in range(nf):
        o = fb + fi * STAGE_FACE_SIZE
        a, b, c = struct.unpack_from("<3H", data, o + 8)
        if a >= nv or b >= nv or c >= nv:
            raise ValueError(f"face {fi}: vertex outside 0..{nv-1}")
        left = min(cell_x[a], cell_x[b], cell_x[c])
        right = max(cell_x[a], cell_x[b], cell_x[c])
        top = min(cell_z[a], cell_z[b], cell_z[c])
        bottom = max(cell_z[a], cell_z[b], cell_z[c])
        span = (right - left + 1) * (bottom - top + 1)
        max_face_span = max(max_face_span, span)
        if span > AREA_LIST_CAPACITY and len(over_capacity_faces) < 20:
            over_capacity_faces.append({
                "face": fi, "cell_span": span,
                "bounds": [left, top, right, bottom],
            })
        for cx in range(left, right + 1):
            for cz in range(top, bottom + 1):
                # SourceCode aliases the map grid modulo 256.
                cells[(cx & 0xFF, cz & 0xFF)].append(fi)

    rect = (
        (min(raw_x), min(raw_z), max(raw_x), max(raw_z))
        if nv else (0, 0, 0, 0)
    )
    return {
        "cells": {k: tuple(v) for k, v in cells.items()},
        "stage_map_rect": rect,
        "max_face_area_cell_span": max_face_span,
        "faces_exceeding_area_list_capacity": over_capacity_faces,
    }


def _rebuild_serialized_area(geometry: dict, *, width: int, area_buffer_base: int) -> dict:
    if width == 4:
        # Current supplied SourceCode declares DWORD *StageArea. In the first
        # SetupPolyAreas pass it does StageArea[x][y]++ while the field is being
        # abused as a counter. One increment therefore advances the pointer by
        # 4 bytes; casting that pointer to int yields 4*N. The second pass uses
        # that value as a DWORD-slot capacity. Shipped DWORD files reproduce
        # this bug exactly.
        count_factor = 4
        pointer_unit = 4
        capacity_model = "DWORD_POINTER_COUNTER_STEP4"
        code = "I"
    elif width == 2:
        # The one shipped WORD16 map is a physical legacy variant. Its raw
        # pointer gaps and wAreaSize are exactly the equivalent pointer-counter
        # bug with a 2-byte pointer element. We preserve that physical family;
        # we do not convert it to the newer DWORD layout.
        count_factor = 2
        pointer_unit = 2
        capacity_model = "WORD16_LEGACY_POINTER_COUNTER_STEP2"
        code = "H"
    else:
        raise ValueError(width)

    cells = geometry["cells"]
    ptrs = [0] * STAGE_AREA_PTR_COUNT
    capacity_offset = 0
    serialized_slots = 0
    payload = bytearray()
    referenced_faces = 0
    for y in range(MAP_SIZE):
        for x in range(MAP_SIZE):
            face_ids = cells.get((x, y))
            if not face_ids:
                continue
            if not area_buffer_base:
                raise ValueError("active StageArea cells with null lpwAreaBuff serialized base")
            ptrs[x * MAP_SIZE + y] = (
                int(area_buffer_base) + capacity_offset * pointer_unit
            ) & 0xFFFFFFFF
            n = len(face_ids)
            if width == 2 and any(int(fi) > 0xFFFF for fi in face_ids):
                raise ValueError("WORD16 StageArea cannot encode face index > 65535")
            slen = n + 1
            payload += struct.pack("<i", slen)
            payload += struct.pack(f"<{slen}{code}", n, *face_ids)
            serialized_slots += slen
            referenced_faces += n
            capacity_offset += count_factor * n + 1

    return {
        "pointer_bytes": struct.pack(f"<{STAGE_AREA_PTR_COUNT}I", *ptrs),
        "payload_bytes": bytes(payload),
        "wAreaSize": capacity_offset,
        "serialized_slots": serialized_slots,
        "referenced_face_occurrences": referenced_faces,
        "active_cells": len(cells),
        "capacity_model": capacity_model,
        "count_factor": count_factor,
        "pointer_unit_bytes": pointer_unit,
    }


def analyze_stage072_stagearea(path: pathlib.Path | str) -> dict:
    p = pathlib.Path(path)
    data = p.read_bytes()
    parsed = parse_stage072(p)
    if parsed.get("full_parse") != "PASS":
        raise ValueError("Stage0.72 physical parser is not PASS")
    layout = _fixed_layout(data)
    stage = data[DFILE_HEADER_SIZE:DFILE_HEADER_SIZE + STAGE_HEADER_SIZE]
    physical = _choose_area_encoding(data, stage, layout)
    geometry = _geometry_cells(data, layout)
    rebuilt = _rebuild_serialized_area(
        geometry,
        width=int(physical["width"]),
        area_buffer_base=_u32(stage, S_AREA_BUFF_PTR),
    )

    physical_cells = physical["cells"]
    computed_cells = geometry["cells"]
    membership_exact = physical_cells == computed_cells
    ptr_start = STAGE_AREA_PTR_OFFSET
    ptr_end = ptr_start + STAGE_AREA_PTR_COUNT * 4
    pointer_exact = stage[ptr_start:ptr_end] == rebuilt["pointer_bytes"]
    warea_exact = _i32(stage, S_WAREA_SIZE) == int(rebuilt["wAreaSize"])
    rect_raw = struct.unpack_from("<4i", stage, S_STAGE_MAP_RECT)
    rect_exact = tuple(rect_raw) == tuple(geometry["stage_map_rect"])
    area_start = int(layout["area_base"])
    area_end = int(physical["cursor"])
    payload_exact = data[area_start:area_end] == rebuilt["payload_bytes"]
    over_capacity = list(geometry["faces_exceeding_area_list_capacity"])

    checks = {
        "physical_parser": parsed.get("full_parse") == "PASS",
        "cell_face_membership_and_order_exact": membership_exact,
        "stagearea_pointer_layout_exact": pointer_exact,
        "wAreaSize_bug_compatible_formula_exact": warea_exact,
        "stage_map_rect_exact": rect_exact,
        "serialized_area_core_byte_exact": payload_exact,
        "area_list_4096_capacity_safe": not over_capacity,
    }
    errors = [k for k, ok in checks.items() if not ok]
    return {
        "format": "PT_STAGE072_STAGEAREA_REBUILD_FILE_V1",
        "path": str(p),
        "sha256": hashlib.sha256(data).hexdigest(),
        "check": "PASS" if not errors else "FAIL",
        "errors": errors,
        "area_encoding": physical["encoding"],
        "capacity_model": rebuilt["capacity_model"],
        "counts": {
            "vertices": int(layout["nvertex"]),
            "faces": int(layout["nface"]),
            "active_area_cells": len(computed_cells),
            "serialized_slots": int(rebuilt["serialized_slots"]),
            "referenced_face_occurrences": int(rebuilt["referenced_face_occurrences"]),
            "wAreaSize_physical": _i32(stage, S_WAREA_SIZE),
            "wAreaSize_rebuilt": int(rebuilt["wAreaSize"]),
        },
        "stage_map_rect_physical": list(rect_raw),
        "stage_map_rect_rebuilt": list(geometry["stage_map_rect"]),
        "max_face_area_cell_span": int(geometry["max_face_area_cell_span"]),
        "area_list_capacity": AREA_LIST_CAPACITY,
        "faces_exceeding_area_list_capacity": over_capacity,
        "area_core_bytes": area_end - area_start,
        "opaque_trailing_bytes": int(physical["trailing_bytes"]),
        "checks": {k: "PASS" if v else "FAIL" for k, v in checks.items()},
        "sourcecode_reconstruction": {
            "fixed_to_world_shift": 8,
            "world_to_area_shift": 6,
            "combined_cell_shift": 14,
            "grid_wrap": "cell & 0xFF",
            "cell_membership": "triangle X/Z bounding-box cells, inclusive",
            "cell_face_order": "ascending source face order",
            "active_cell_serialization_order": "y outer, x inner",
            "serialized_list": "DWORD slen then count+face indices using physical WORD16/DWORD32 width",
            "capacity_model": rebuilt["capacity_model"],
        },
        "client_modified": False,
    }


def _candidate_paths(records: list[dict]) -> list[str]:
    out = []
    seen = set()
    for row in records:
        if str(row.get("kind") or "") != "SMD_STAGE_072":
            continue
        rel = norm_path(row.get("relative_path") or row.get("path") or "")
        if not rel or rel.lower() in seen:
            continue
        seen.add(rel.lower())
        out.append(rel)
    return sorted(out, key=str.lower)


def _write_bundle(bundle: str, resolver, rows: list[dict], representatives: list[str], report_summary: dict) -> str:
    bp = pathlib.Path(bundle).expanduser().resolve()
    bp.parent.mkdir(parents=True, exist_ok=True)
    by_rel = {r["relative_path"].lower(): r for r in rows}
    manifest = {
        "format": "PT_STAGE072_STAGEAREA_REBUILD_REPRESENTATIVES_V1",
        "representatives": representatives,
        "rows": [by_rel[x.lower()] for x in representatives if x.lower() in by_rel],
        "summary": report_summary,
        "client_modified": False,
    }
    with zipfile.ZipFile(bp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("STAGE072_STAGEAREA_REBUILD_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for rel in representatives:
            src = resolver.resolve(rel)
            z.write(src, f"client/{rel}")
    return str(bp)


def audit_stage072_stagearea_rebuild(records: list[dict], resolver, *, bundle: str | None = None) -> dict:
    candidates = _candidate_paths(records)
    rows = []
    scan_errors = []
    for rel in candidates:
        try:
            src = resolver.resolve(rel)
            result = analyze_stage072_stagearea(src)
            rows.append({"relative_path": rel, **result})
        except Exception as exc:
            rows.append({"relative_path": rel, "check": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            scan_errors.append({"relative_path": rel, "error": f"{type(exc).__name__}: {exc}"})

    passed = [r for r in rows if r.get("check") == "PASS"]
    failed = [r for r in rows if r.get("check") != "PASS"]
    enc = collections.Counter(r.get("area_encoding") for r in passed)
    cap = collections.Counter(r.get("capacity_model") for r in passed)
    max_span = max((int(r.get("max_face_area_cell_span") or 0) for r in passed), default=0)
    over = sum(len(r.get("faces_exceeding_area_list_capacity") or []) for r in passed)

    summary = {
        "format": "PT_STAGE072_STAGEAREA_REBUILD_CORPUS_AUDIT_V1",
        "status": "PASS" if len(rows) == len(candidates) and not failed else "FAIL",
        "candidate_files_expected": len(candidates),
        "physical_files_audited": len(rows),
        "reconstruction_pass_files": len(passed),
        "reconstruction_fail_files": len(failed),
        "scan_errors": scan_errors,
        "area_encoding_file_counts": dict(sorted(enc.items())),
        "capacity_model_file_counts": dict(sorted(cap.items())),
        "cell_face_membership_exact_files": sum((r.get("checks") or {}).get("cell_face_membership_and_order_exact") == "PASS" for r in passed),
        "stagearea_pointer_layout_exact_files": sum((r.get("checks") or {}).get("stagearea_pointer_layout_exact") == "PASS" for r in passed),
        "wAreaSize_formula_exact_files": sum((r.get("checks") or {}).get("wAreaSize_bug_compatible_formula_exact") == "PASS" for r in passed),
        "stage_map_rect_exact_files": sum((r.get("checks") or {}).get("stage_map_rect_exact") == "PASS" for r in passed),
        "serialized_area_core_byte_exact_files": sum((r.get("checks") or {}).get("serialized_area_core_byte_exact") == "PASS" for r in passed),
        "max_face_area_cell_span": max_span,
        "area_list_capacity": AREA_LIST_CAPACITY,
        "faces_exceeding_area_list_capacity": over,
        "opaque_trailing_files": sum(int(r.get("opaque_trailing_bytes") or 0) > 0 for r in passed),
        "stagearea_rebuild_complete_candidate": (
            len(candidates) > 0 and len(rows) == len(candidates) and not failed and over == 0
        ),
        "sourcecode_and_physical_findings": {
            "setup_poly_areas": "all face memberships derive from triangle X/Z bounding boxes after fixed>>8 and area>>6, wrapping cell coordinates with &0xFF",
            "DWORD32_capacity_bug": "supplied SourceCode increments DWORD* StageArea cells while using the pointer as a counter; physical DWORD files exactly encode wAreaSize=sum(4*face_count+1) and matching gapped pointer addresses",
            "WORD16_legacy_capacity": "the one physical WORD16 file exactly encodes the legacy equivalent sum(2*face_count+1) with 2-byte pointer steps; preserve this family rather than converting it",
            "StageMapRect": "exact min/max raw fixed-point X/Z vertex bounds",
            "opaque_suffix_policy": "runtime-ignored suffix is outside rebuilt StageArea core and must remain byte-identical in any writer",
        },
    }

    representatives: list[str] = []
    # Mandatory format boundaries and future writer witnesses.
    for r in passed:
        if r.get("area_encoding") == "WORD16" or int(r.get("opaque_trailing_bytes") or 0) > 0:
            representatives.append(r["relative_path"])
    if passed:
        representatives.append(max(passed, key=lambda r: int(r.get("max_face_area_cell_span") or 0))["relative_path"])
        # Small ordinary DWORD witness for quick reruns.
        ordinary = [r for r in passed if r.get("area_encoding") == "DWORD32"]
        if ordinary:
            representatives.append(min(ordinary, key=lambda r: int((r.get("counts") or {}).get("faces") or 0))["relative_path"])
    representatives.extend(r["relative_path"] for r in failed)
    representatives = sorted(dict.fromkeys(representatives), key=str.lower)
    summary["representatives"] = representatives
    if bundle:
        summary["bundle"] = _write_bundle(bundle, resolver, rows, representatives, {k: v for k, v in summary.items() if k != "rows"})
    summary["rows"] = rows
    return summary
