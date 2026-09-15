from __future__ import annotations

import hashlib
import json
import math
import pathlib
import struct

from .stage072_area import (
    AREA_LIST_CAPACITY,
    _choose_area_encoding,
    _fixed_layout,
    _geometry_cells,
    _rebuild_serialized_area,
    analyze_stage072_stagearea,
)
from .stage072_corpus import (
    DFILE_HEADER_SIZE,
    STAGE_HEADER_SIZE,
    STAGE_AREA_PTR_OFFSET,
    STAGE_AREA_PTR_COUNT,
    STAGE_VERTEX_SIZE,
    STAGE_FACE_SIZE,
    S_AREA_BUFF_PTR,
    S_WAREA_SIZE,
    S_STAGE_MAP_RECT,
    parse_stage072,
)
from .stage072_normals import (
    CURRENT_MODEL,
    LEGACY_RECIP_MODEL,
    analyze_stage072_normals,
)

TOOL = "PT_STAGE072_GEOMETRY_PROVENANCE_BRIDGE_V3"
LEGACY_UNRESOLVED_MODEL = "LEGACY_FLOAT_EVALUATION_VARIANT_UNRESOLVED_1LSB"
SUPPORTED_SOURCE_NORMAL_MODELS = {
    CURRENT_MODEL,
    LEGACY_RECIP_MODEL,
    LEGACY_UNRESOLVED_MODEL,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def _u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _source_setnormal(p0, p1, p2) -> tuple[int, int, int]:
    """Supplied current SourceCode SetNormal evaluation.

    This is the physically-proven current family and the authorized generation
    rule for faces whose geometry is intentionally changed. Historical normals
    on untouched legacy faces are preserved byte-identically rather than being
    normalized into a newer provenance family.
    """
    # Keep arithmetic explicit to mirror the C source without vector helpers.
    ax, ay, az = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    bx, by, bz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
    vals = (ax, ay, az, bx, by, bz)
    if any(q < -(2**31) or q > 2**31 - 1 for q in vals):
        raise ValueError("SetNormal int32 edge subtraction overflow is not authorized")
    pairs = ((ay, bz, az, by), (az, bx, ax, bz), (ax, by, ay, bx))
    cross = []
    for a, b, c, d0 in pairs:
        p_ab = a * b
        p_cd = c * d0
        if not -(2**31) <= p_ab <= 2**31 - 1 or not -(2**31) <= p_cd <= 2**31 - 1:
            raise ValueError("SetNormal int32 multiply overflow is not authorized")
        q = p_ab - p_cd
        if not -(2**31) <= q <= 2**31 - 1:
            raise ValueError("SetNormal int32 cross subtraction overflow is not authorized")
        cross.append(q)
    cx, cy, cz = cross
    if cx == 0 and cy == 0 and cz == 0:
        raise ValueError("geometry edit creates/uses degenerate face; SetNormal divide-by-zero is not authorized")
    i, j, k = _f32(cx), _f32(cy), _f32(cz)
    sq = _f32(_f32(i * i) + _f32(j * j))
    sq = _f32(sq + _f32(k * k))
    d = _f32(math.sqrt(float(sq)))
    if not math.isfinite(d) or d == 0.0:
        raise ValueError("non-finite/zero SetNormal length")
    out = []
    for q in (i, j, k):
        v = _f32(q / d)
        v = _f32(v * _f32(32767.0))
        out.append(int(v))
    return tuple(out)


def _points_shifted(data: bytes | bytearray, layout: dict) -> list[tuple[int, int, int]]:
    out = []
    for vi in range(int(layout["nvertex"])):
        o = int(layout["vertex_base"]) + vi * STAGE_VERTEX_SIZE
        x, y, z = struct.unpack_from("<iii", data, o + 8)
        out.append((x >> 8, y >> 8, z >> 8))
    return out


def _incident_faces(data: bytes | bytearray, layout: dict, vertex_index: int) -> list[int]:
    out = []
    for fi in range(int(layout["nface"])):
        o = int(layout["face_base"]) + fi * STAGE_FACE_SIZE
        verts = struct.unpack_from("<3H", data, o + 8)
        if vertex_index in verts:
            out.append(fi)
    return out


def _source_normal_guard(path: pathlib.Path | str) -> dict:
    audit = analyze_stage072_normals(path)
    if audit.get("check") != "PASS":
        raise RuntimeError("Stage0.72 normal audit is not PASS")
    family = audit.get("classification")
    if family not in SUPPORTED_SOURCE_NORMAL_MODELS:
        raise RuntimeError(
            "Stage0.72 geometry writer refuses an unproven source normal family; "
            f"got {family}"
        )
    return audit


def _physical_area(data: bytes, layout: dict) -> dict:
    stage = data[DFILE_HEADER_SIZE:DFILE_HEADER_SIZE + STAGE_HEADER_SIZE]
    return _choose_area_encoding(data, stage, layout)


def select_stage072_geometry_witness(path: pathlib.Path | str, *, delta_world: float = 64.0) -> dict:
    p = pathlib.Path(path)
    if not math.isfinite(delta_world) or not (1.0 <= abs(float(delta_world)) <= 256.0):
        raise ValueError("delta_world magnitude must be between 1 and 256")
    delta_raw_f = float(delta_world) * 256.0
    delta_raw = int(round(delta_raw_f))
    if abs(delta_raw_f - delta_raw) > 1e-9 or delta_raw == 0:
        raise ValueError("delta_world must map to an exact 1/256 fixed-point increment")

    data = p.read_bytes()
    parsed = parse_stage072(p, include_payload=True)
    if parsed.get("full_parse") != "PASS":
        raise RuntimeError("Stage0.72 source parser is not PASS")
    normal_audit = _source_normal_guard(p)
    layout = _fixed_layout(data)
    physical = _physical_area(data, layout)
    original_geom = _geometry_cells(data, layout)

    degree = [0] * int(layout["nvertex"])
    for fi in range(int(layout["nface"])):
        o = int(layout["face_base"]) + fi * STAGE_FACE_SIZE
        for vi in struct.unpack_from("<3H", data, o + 8):
            degree[int(vi)] += 1

    candidates = sorted(range(len(degree)), key=lambda vi: (degree[vi] if degree[vi] else 10**9, vi))
    for vi in candidates:
        if degree[vi] <= 0:
            continue
        vo = int(layout["vertex_base"]) + vi * STAGE_VERTEX_SIZE
        before = list(struct.unpack_from("<iii", data, vo + 8))
        nx = before[0] + delta_raw
        if not -(2**31) <= nx < 2**31:
            continue
        trial = bytearray(data)
        struct.pack_into("<i", trial, vo + 8, nx)
        after = [nx, before[1], before[2]]
        if (before[0] >> 8) == (after[0] >> 8):
            continue
        incident = _incident_faces(trial, layout, vi)
        points = _points_shifted(trial, layout)
        try:
            for fi in incident:
                fo = int(layout["face_base"]) + fi * STAGE_FACE_SIZE
                a, b, c = struct.unpack_from("<3H", trial, fo + 8)
                _source_setnormal(points[a], points[b], points[c])
        except ValueError:
            continue
        geom = _geometry_cells(trial, layout)
        if geom["cells"] == original_geom["cells"]:
            continue
        if geom["faces_exceeding_area_list_capacity"]:
            continue
        try:
            _rebuild_serialized_area(
                geom,
                width=int(physical["width"]),
                area_buffer_base=_u32(data, DFILE_HEADER_SIZE + S_AREA_BUFF_PTR),
            )
        except ValueError:
            continue
        return {
            "vertex_index": vi,
            "component": "x",
            "delta_world": float(delta_world),
            "delta_raw": delta_raw,
            "before_raw": before,
            "after_raw": after,
            "before_world": [q / 256.0 for q in before],
            "after_world": [q / 256.0 for q in after],
            "incident_faces": incident,
            "incident_face_count": len(incident),
            "stagearea_changed": True,
            "stage_map_rect_before": list(original_geom["stage_map_rect"]),
            "stage_map_rect_after": list(geom["stage_map_rect"]),
            "active_cells_before": len(original_geom["cells"]),
            "active_cells_after": len(geom["cells"]),
            "max_face_area_cell_span_after": int(geom["max_face_area_cell_span"]),
            "source_normal_family": normal_audit.get("classification"),
            "changed_face_normal_model": CURRENT_MODEL,
            "area_encoding": physical.get("encoding"),
            "area_width": int(physical["width"]),
            "opaque_trailing_bytes": int(physical["trailing_bytes"]),
        }
    raise RuntimeError("no safe Stage0.72 geometry witness found that changes StageArea")


def _validate_changed_face_normals(
    source_data: bytes,
    output_data: bytes,
    source_layout: dict,
    output_layout: dict,
    incident: set[int],
) -> tuple[bool, list[dict]]:
    points = _points_shifted(output_data, output_layout)
    failures = []
    for fi in sorted(incident):
        so = int(source_layout["face_base"]) + fi * STAGE_FACE_SIZE
        oo = int(output_layout["face_base"]) + fi * STAGE_FACE_SIZE
        a, b, c = struct.unpack_from("<3H", output_data, oo + 8)
        expected = _source_setnormal(points[a], points[b], points[c])
        actual4 = struct.unpack_from("<4h", output_data, oo + 20)
        source4 = struct.unpack_from("<4h", source_data, so + 20)
        if tuple(actual4[:3]) != tuple(expected) or actual4[3] != source4[3]:
            failures.append({
                "face": fi,
                "expected_current_setnormal": list(expected),
                "actual": list(actual4[:3]),
                "source_vectnormal3": int(source4[3]),
                "output_vectnormal3": int(actual4[3]),
            })
            if len(failures) >= 20:
                break
    return (not failures, failures)


def strict_write_stage072_geometry_witness(
    source: pathlib.Path | str,
    output: pathlib.Path | str,
    witness_report: pathlib.Path | str,
    *,
    expected_source_sha256: str | None = None,
    report_path: pathlib.Path | str | None = None,
) -> dict:
    source = pathlib.Path(source)
    output = pathlib.Path(output)
    data = source.read_bytes()
    source_sha = _sha(data)
    if expected_source_sha256 and source_sha.lower() != str(expected_source_sha256).lower():
        raise RuntimeError(f"source sha256 drift: expected={expected_source_sha256} actual={source_sha}")
    parsed = parse_stage072(source, include_payload=True)
    if parsed.get("full_parse") != "PASS":
        raise RuntimeError("Stage0.72 source parser is not PASS")
    normal_audit = _source_normal_guard(source)

    witness = json.loads(pathlib.Path(witness_report).read_text(encoding="utf-8"))
    if str(witness.get("source_sha256") or "").lower() != source_sha.lower():
        raise RuntimeError("witness source_sha256 does not match source")
    edits = list(witness.get("geometry_edits") or [])
    if not edits:
        raise RuntimeError("geometry writer V3 requires at least one witness vertex edit")

    layout = _fixed_layout(data)
    physical = _physical_area(data, layout)
    out = bytearray(data)
    seen: set[int] = set()
    normalized_edits = []
    incident: set[int] = set()
    for raw_edit in edits:
        edit = dict(raw_edit)
        vi = int(edit["vertex_index"])
        if vi in seen:
            raise RuntimeError(f"geometry writer V3 duplicate witness vertex index: {vi}")
        seen.add(vi)
        if not 0 <= vi < int(layout["nvertex"]):
            raise ValueError(f"witness vertex index out of range: {vi}")
        vo = int(layout["vertex_base"]) + vi * STAGE_VERTEX_SIZE
        source_raw = list(struct.unpack_from("<iii", data, vo + 8))
        before_raw = [int(x) for x in edit["before_raw"]]
        after_raw = [int(x) for x in edit["after_raw"]]
        if len(before_raw) != 3 or len(after_raw) != 3:
            raise RuntimeError("geometry writer V3 expects xyz fixed-point triples")
        if source_raw != before_raw:
            raise RuntimeError(f"witness/source vertex mismatch vi={vi}: source={source_raw} witness={before_raw}")
        changed = [i for i in range(3) if after_raw[i] != before_raw[i]]
        if not changed:
            raise RuntimeError(f"geometry writer V3 witness has no effective edit: vi={vi}")
        if any(not -(2**31) <= int(q) < 2**31 for q in after_raw):
            raise ValueError("edited fixed-point coordinate outside int32")
        struct.pack_into("<iii", out, vo + 8, *after_raw)
        inc = _incident_faces(out, layout, vi)
        declared = edit.get("incident_faces")
        if declared is not None and sorted(int(x) for x in declared) != inc:
            raise RuntimeError(f"witness incident-face set mismatch vi={vi}")
        incident.update(inc)
        normalized_edits.append({
            "vertex_index": vi,
            "before_raw": before_raw,
            "after_raw": after_raw,
            "before_world": [q/256.0 for q in before_raw],
            "after_world": [q/256.0 for q in after_raw],
            "changed_components": changed,
            "incident_faces": inc,
            "delta_raw": [after_raw[i]-before_raw[i] for i in range(3)],
            "delta_world": [(after_raw[i]-before_raw[i])/256.0 for i in range(3)],
        })

    points = _points_shifted(out, layout)
    normal_changes = []
    for fi in sorted(incident):
        fo = int(layout["face_base"]) + fi * STAGE_FACE_SIZE
        a, b, c = struct.unpack_from("<3H", out, fo + 8)
        normal = _source_setnormal(points[a], points[b], points[c])
        before4 = struct.unpack_from("<4h", data, fo + 20)
        struct.pack_into("<3h", out, fo + 20, *normal)
        after4 = struct.unpack_from("<4h", out, fo + 20)
        if after4[3] != before4[3]:
            raise AssertionError("VectNormal[3] must remain byte-identical")
        normal_changes.append({
            "face_index": fi, "before": list(before4[:3]), "after": list(after4[:3]),
            "vectnormal3_preserved": int(after4[3]),
        })

    stage_start = DFILE_HEADER_SIZE
    stage = bytes(out[stage_start:stage_start + STAGE_HEADER_SIZE])
    geometry = _geometry_cells(out, layout)
    if geometry["faces_exceeding_area_list_capacity"]:
        raise RuntimeError("edited geometry exceeds AreaList[4096] face-cell capacity")
    rebuilt_area = _rebuild_serialized_area(
        geometry, width=int(physical["width"]),
        area_buffer_base=_u32(stage, S_AREA_BUFF_PTR),
    )
    ptr_abs = stage_start + STAGE_AREA_PTR_OFFSET
    out[ptr_abs:ptr_abs + STAGE_AREA_PTR_COUNT * 4] = rebuilt_area["pointer_bytes"]
    struct.pack_into("<i", out, stage_start + S_WAREA_SIZE, int(rebuilt_area["wAreaSize"]))
    struct.pack_into("<4i", out, stage_start + S_STAGE_MAP_RECT, *geometry["stage_map_rect"])

    area_base = int(layout["area_base"])
    opaque_suffix = data[int(physical["cursor"]):]
    final = bytes(out[:area_base]) + rebuilt_area["payload_bytes"] + opaque_suffix
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(final)

    rebuilt = parse_stage072(output, include_payload=True)
    if rebuilt.get("full_parse") != "PASS":
        raise RuntimeError("rebuilt geometry Stage0.72 parser is not PASS")
    area_check = analyze_stage072_stagearea(output)
    if area_check.get("check") != "PASS":
        raise RuntimeError("rebuilt geometry StageArea proof is not PASS")
    out_layout = _fixed_layout(final)
    ok_normals, normal_failures = _validate_changed_face_normals(data, final, layout, out_layout, incident)
    if not ok_normals:
        raise RuntimeError(f"changed-face current SetNormal proof failed: {normal_failures[:3]}")

    whole_output_normal = analyze_stage072_normals(output)
    if normal_audit.get("classification") == CURRENT_MODEL:
        if whole_output_normal.get("classification") != CURRENT_MODEL or whole_output_normal.get("check") != "PASS":
            raise RuntimeError("current-family output left current exact normal family")
        output_normal_policy = "CURRENT_EXACT_WHOLE_FILE"
    else:
        output_normal_policy = "LEGACY_UNTOUCHED_CURRENT_SETNORMAL_CHANGED_FACES"

    result = {
        "tool": TOOL, "source": str(source), "output": str(output),
        "source_sha256": source_sha, "output_sha256": _sha(final),
        "source_normal_family": normal_audit.get("classification"),
        "changed_face_normal_model": CURRENT_MODEL, "output_normal_policy": output_normal_policy,
        "output_whole_file_normal_classification": whole_output_normal.get("classification"),
        "vertex_edits": normalized_edits, "vertex_edit_count": len(normalized_edits),
        "incident_faces": sorted(incident), "normal_changes": normal_changes,
        "normal_change_face_count": len(normal_changes),
        "stagearea": {
            "source_encoding": physical["encoding"], "width": int(physical["width"]),
            "capacity_model": rebuilt_area["capacity_model"], "active_cells": int(rebuilt_area["active_cells"]),
            "wAreaSize": int(rebuilt_area["wAreaSize"]), "payload_bytes": len(rebuilt_area["payload_bytes"]),
            "opaque_trailing_bytes_preserved": len(opaque_suffix),
            "stage_map_rect": list(geometry["stage_map_rect"]),
            "max_face_area_cell_span": int(geometry["max_face_area_cell_span"]),
        },
        "source_parse": parsed.get("full_parse"), "rebuilt_parse": rebuilt.get("full_parse"),
        "stagearea_output_check": area_check.get("check"), "changed_face_normal_check": "PASS",
        "client_modified": False, "check": "PASS",
    }
    if report_path:
        rp = pathlib.Path(report_path); rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def compare_stage072_geometry_roundtrip(
    source: pathlib.Path | str,
    output: pathlib.Path | str,
    witness_report: pathlib.Path | str,
    *,
    report_path: pathlib.Path | str | None = None,
) -> dict:
    source = pathlib.Path(source)
    output = pathlib.Path(output)
    sb = source.read_bytes()
    ob = output.read_bytes()
    s = parse_stage072(source, include_payload=True)
    o = parse_stage072(output, include_payload=True)
    source_normal_audit = _source_normal_guard(source)
    witness = json.loads(pathlib.Path(witness_report).read_text(encoding="utf-8"))
    errors = []
    if s.get("full_parse") != "PASS": errors.append("SOURCE_PARSE")
    if o.get("full_parse") != "PASS": errors.append("OUTPUT_PARSE")
    edits = list(witness.get("geometry_edits") or [])
    if not edits: errors.append("WITNESS_EDIT_COUNT")
    edits_by_vi = {int(e.get("vertex_index", -1)): dict(e) for e in edits}
    if len(edits_by_vi) != len(edits): errors.append("WITNESS_DUPLICATE_VERTEX")
    edited_vertices = set(edits_by_vi)
    for vi, edit in edits_by_vi.items():
        if not 0 <= vi < int(s.get("counts", {}).get("vertices") or 0): errors.append("WITNESS_VERTEX_RANGE")

    ls = _fixed_layout(sb)
    lo = _fixed_layout(ob)
    for vi, edit in edits_by_vi.items():
        if not 0 <= vi < int(ls["nvertex"]):
            continue
        so = int(ls["vertex_base"]) + vi * STAGE_VERTEX_SIZE + 8
        oo = int(lo["vertex_base"]) + vi * STAGE_VERTEX_SIZE + 8
        source_xyz = list(struct.unpack_from("<iii", sb, so))
        output_xyz = list(struct.unpack_from("<iii", ob, oo))
        if source_xyz != [int(x) for x in edit.get("before_raw") or []]:
            errors.append(f"WITNESS_SOURCE_VERTEX:{vi}")
        if output_xyz != [int(x) for x in edit.get("after_raw") or []]:
            errors.append(f"WITNESS_OUTPUT_VERTEX:{vi}")
    for k in ("nvertex", "nface", "ntexlink", "nlight", "material_start", "vertex_base", "face_base", "texlink_base", "light_base", "area_base"):
        if int(ls[k]) != int(lo[k]): errors.append(f"LAYOUT_{k}")

    if sb[:DFILE_HEADER_SIZE] != ob[:DFILE_HEADER_SIZE]: errors.append("DFILE_HEADER")
    ms = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE
    if sb[ms:int(ls["vertex_base"])] != ob[ms:int(lo["vertex_base"])]: errors.append("MATERIALS")

    shs = bytearray(sb[DFILE_HEADER_SIZE:DFILE_HEADER_SIZE + STAGE_HEADER_SIZE])
    sho = bytearray(ob[DFILE_HEADER_SIZE:DFILE_HEADER_SIZE + STAGE_HEADER_SIZE])
    allowed_header = set(range(STAGE_AREA_PTR_OFFSET, STAGE_AREA_PTR_OFFSET + STAGE_AREA_PTR_COUNT * 4))
    allowed_header.update(range(S_WAREA_SIZE, S_WAREA_SIZE + 4))
    allowed_header.update(range(S_STAGE_MAP_RECT, S_STAGE_MAP_RECT + 16))
    header_unexpected = [i for i, (a,b) in enumerate(zip(shs, sho)) if a != b and i not in allowed_header]
    if header_unexpected: errors.append("STAGE_HEADER_UNEXPECTED")

    vertex_unexpected = []
    for vj in range(int(ls["nvertex"])):
        a0 = int(ls["vertex_base"]) + vj * STAGE_VERTEX_SIZE
        b0 = int(lo["vertex_base"]) + vj * STAGE_VERTEX_SIZE
        for j in range(STAGE_VERTEX_SIZE):
            if sb[a0+j] == ob[b0+j]:
                continue
            if not (vj in edited_vertices and 8 <= j < 20):
                vertex_unexpected.append((vj,j))
                if len(vertex_unexpected) >= 20: break
        if len(vertex_unexpected) >= 20: break
    if vertex_unexpected: errors.append("VERTEX_UNEXPECTED")

    incident = set()
    for edit in edits:
        incident.update(int(x) for x in edit.get("incident_faces") or [])
    face_unexpected = []
    vectnormal3_exact = True
    untouched_normal4_exact = True
    for fi in range(int(ls["nface"])):
        a0 = int(ls["face_base"]) + fi * STAGE_FACE_SIZE
        b0 = int(lo["face_base"]) + fi * STAGE_FACE_SIZE
        if sb[a0+26:a0+28] != ob[b0+26:b0+28]:
            vectnormal3_exact = False
        if fi not in incident and sb[a0+20:a0+28] != ob[b0+20:b0+28]:
            untouched_normal4_exact = False
        for j in range(STAGE_FACE_SIZE):
            if sb[a0+j] == ob[b0+j]:
                continue
            if not (fi in incident and 20 <= j < 26):
                face_unexpected.append((fi,j))
                if len(face_unexpected) >= 20: break
        if len(face_unexpected) >= 20: break
    if face_unexpected: errors.append("FACE_UNEXPECTED")
    if not vectnormal3_exact: errors.append("VECTNORMAL3")
    if not untouched_normal4_exact: errors.append("UNTOUCHED_NORMAL_PROVENANCE")

    changed_normals_exact, changed_normal_failures = _validate_changed_face_normals(sb, ob, ls, lo, incident)
    if not changed_normals_exact: errors.append("CHANGED_FACE_SETNORMAL")

    tex_exact = sb[int(ls["texlink_base"]):int(ls["light_base"])] == ob[int(lo["texlink_base"]):int(lo["light_base"])]
    lights_exact = sb[int(ls["light_base"]):int(ls["area_base"])] == ob[int(lo["light_base"]):int(lo["area_base"])]
    if not tex_exact: errors.append("TEXLINKS")
    if not lights_exact: errors.append("LIGHTS")

    source_area = analyze_stage072_stagearea(source)
    area_check = analyze_stage072_stagearea(output)
    if area_check.get("check") != "PASS": errors.append("STAGEAREA_REBUILD")
    sp = _physical_area(sb, ls)
    op = _physical_area(ob, lo)
    if int(sp["width"]) != int(op["width"]): errors.append("AREA_WIDTH_CHANGED")
    source_suffix = sb[int(sp["cursor"]):]
    output_suffix = ob[int(op["cursor"]):]
    opaque_exact = source_suffix == output_suffix
    if not opaque_exact: errors.append("OPAQUE_SUFFIX")
    stagearea_core_changed = sb[int(ls["area_base"]):int(sp["cursor"])] != ob[int(lo["area_base"]):int(op["cursor"])]
    pointer_header_changed = shs[STAGE_AREA_PTR_OFFSET:STAGE_AREA_PTR_OFFSET + STAGE_AREA_PTR_COUNT*4] != sho[STAGE_AREA_PTR_OFFSET:STAGE_AREA_PTR_OFFSET + STAGE_AREA_PTR_COUNT*4]
    stagearea_changed = stagearea_core_changed or pointer_header_changed

    if s.get("counts", {}).get("materials") != o.get("counts", {}).get("materials"): errors.append("MATERIAL_COUNT")
    if s.get("materials") != o.get("materials"): errors.append("MATERIAL_SEMANTICS")
    if s.get("texlink_depth_face_counts") != o.get("texlink_depth_face_counts"): errors.append("TEXLINK_DEPTHS")
    if s.get("max_texlink_depth") != o.get("max_texlink_depth"): errors.append("MAX_DEPTH")
    if s.get("lighting") != o.get("lighting"): errors.append("LIGHTING_CONTROLS")
    if (s.get("payload") or {}).get("lights") != (o.get("payload") or {}).get("lights"): errors.append("LIGHT_PAYLOAD")

    result = {
        "tool": "PT_STAGE072_GEOMETRY_ROUNDTRIP_COMPARE_V2",
        "source": str(source),
        "output": str(output),
        "source_sha256": _sha(sb),
        "output_sha256": _sha(ob),
        "source_parse": s.get("full_parse"),
        "output_parse": o.get("full_parse"),
        "source_normal_family": source_normal_audit.get("classification"),
        "changed_face_normal_model": CURRENT_MODEL,
        "vertex_indices": sorted(edited_vertices),
        "vertex_edit_count": len(edited_vertices),
        "incident_face_count": len(incident),
        "file_size_before": len(sb),
        "file_size_after": len(ob),
        "source_area_encoding": sp.get("encoding"),
        "output_area_encoding": op.get("encoding"),
        "stagearea_changed": stagearea_changed,
        "stagearea_source": source_area,
        "stagearea_output": area_check,
        "texlinks_byte_identical": tex_exact,
        "lights_byte_identical": lights_exact,
        "vectnormal3_byte_identical": vectnormal3_exact,
        "untouched_face_normal4_byte_identical": untouched_normal4_exact,
        "changed_face_current_setnormal_exact": changed_normals_exact,
        "changed_face_normal_failures": changed_normal_failures,
        "opaque_trailing_byte_identical": opaque_exact,
        "opaque_trailing_bytes": len(source_suffix),
        "header_unexpected_diff_count": len(header_unexpected),
        "vertex_unexpected_diff_count": len(vertex_unexpected),
        "face_unexpected_diff_count": len(face_unexpected),
        "errors": errors,
        "check": "PASS" if not errors else "FAIL",
        "client_modified": False,
    }
    if report_path:
        rp = pathlib.Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError(f"Stage0.72 strict geometry roundtrip compare failed: {errors[:8]}")
    return result
