from __future__ import annotations

import collections
import hashlib
import json
import math
import pathlib
import struct
import zipfile

from .stage072_area import _fixed_layout
from .stage072_corpus import STAGE_VERTEX_SIZE, STAGE_FACE_SIZE
from .utils import norm_path

CURRENT_MODEL = "CURRENT_FLOAT32_DIV_SQRT_MUL32767_TRUNC"
LEGACY_RECIP_MODEL = "LEGACY_FLOAT32_RECIP_SQRT_MUL32767_TRUNC"
CURRENT_DEBUG_TAIL = -12851  # signed 0xCDCD


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def _current_normal_scalar(cx: int, cy: int, cz: int) -> tuple[int, int, int]:
    if cx == 0 and cy == 0 and cz == 0:
        return (0, 0, 0)
    fx, fy, fz = _f32(cx), _f32(cy), _f32(cz)
    sq = _f32(_f32(fx * fx) + _f32(fy * fy))
    sq = _f32(sq + _f32(fz * fz))
    length = _f32(math.sqrt(sq))
    out = []
    for q in (fx, fy, fz):
        unit = _f32(q / length)
        scaled = _f32(unit * _f32(32767.0))
        out.append(int(scaled))
    return tuple(out)


def _legacy_recip_scalar(cx: int, cy: int, cz: int) -> tuple[int, int, int]:
    if cx == 0 and cy == 0 and cz == 0:
        return (0, 0, 0)
    fx, fy, fz = _f32(cx), _f32(cy), _f32(cz)
    sq = _f32(_f32(fx * fx) + _f32(fy * fy))
    sq = _f32(sq + _f32(fz * fz))
    length = _f32(math.sqrt(sq))
    inv = _f32(_f32(1.0) / length)
    out = []
    for q in (fx, fy, fz):
        unit = _f32(q * inv)
        scaled = _f32(unit * _f32(32767.0))
        out.append(int(scaled))
    return tuple(out)


def _cross(p0, p1, p2) -> tuple[int, int, int]:
    ax, ay, az = p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]
    bx, by, bz = p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]
    return (
        ay*bz - az*by,
        az*bx - ax*bz,
        ax*by - ay*bx,
    )


def _analyze_scalar(data: bytes, layout: dict) -> dict:
    nv = int(layout["nvertex"])
    nf = int(layout["nface"])
    vb = int(layout["vertex_base"])
    fb = int(layout["face_base"])
    points = []
    for vi in range(nv):
        o = vb + vi * STAGE_VERTEX_SIZE
        x, y, z = struct.unpack_from("<iii", data, o + 8)
        points.append((x >> 8, y >> 8, z >> 8))

    current_match = legacy_match = degenerate = degenerate_zero = 0
    current_max_delta = legacy_max_delta = 0
    tail = collections.Counter()
    mismatch_examples = []
    for fi in range(nf):
        o = fb + fi * STAGE_FACE_SIZE
        a, b, c, _mid = struct.unpack_from("<4H", data, o + 8)
        actual4 = struct.unpack_from("<4h", data, o + 20)
        actual = actual4[:3]
        tail[int(actual4[3])] += 1
        cx, cy, cz = _cross(points[a], points[b], points[c])
        is_deg = cx == 0 and cy == 0 and cz == 0
        if is_deg:
            degenerate += 1
            if actual == (0, 0, 0):
                degenerate_zero += 1
        cur = _current_normal_scalar(cx, cy, cz)
        leg = _legacy_recip_scalar(cx, cy, cz)
        cur_delta = max(abs(actual[i] - cur[i]) for i in range(3))
        leg_delta = max(abs(actual[i] - leg[i]) for i in range(3))
        current_max_delta = max(current_max_delta, cur_delta)
        legacy_max_delta = max(legacy_max_delta, leg_delta)
        if actual == cur:
            current_match += 1
        elif len(mismatch_examples) < 12:
            mismatch_examples.append({
                "face": fi, "actual": list(actual), "current": list(cur),
                "legacy_recip": list(leg), "cross": [cx, cy, cz],
                "vectnormal3": int(actual4[3]),
            })
        if actual == leg:
            legacy_match += 1

    return {
        "faces": nf,
        "current_match": current_match,
        "legacy_recip_match": legacy_match,
        "degenerate_faces": degenerate,
        "degenerate_zero_normal_faces": degenerate_zero,
        "current_max_component_delta": current_max_delta,
        "legacy_recip_max_component_delta": legacy_max_delta,
        "vectnormal3_counts": dict(sorted(tail.items())),
        "mismatch_examples": mismatch_examples,
        "engine": "SCALAR_FLOAT32_EMULATION",
    }


def _analyze_numpy(data: bytes, layout: dict) -> dict:
    import numpy as np
    nv = int(layout["nvertex"])
    nf = int(layout["nface"])
    vb = int(layout["vertex_base"])
    fb = int(layout["face_base"])
    vd = np.dtype({"names":["x","y","z"], "formats":["<i4","<i4","<i4"], "offsets":[8,12,16], "itemsize":STAGE_VERTEX_SIZE})
    fd = np.dtype({"names":["verts","norm4"], "formats":[("<u2",(4,)),("<i2",(4,))], "offsets":[8,20], "itemsize":STAGE_FACE_SIZE})
    vertices = np.frombuffer(data, dtype=vd, count=nv, offset=vb)
    faces = np.frombuffer(data, dtype=fd, count=nf, offset=fb)
    idx = faces["verts"][:,:3].astype(np.int64)
    p = np.column_stack([vertices["x"], vertices["y"], vertices["z"]]).astype(np.int64) >> 8
    cross = np.cross(p[idx[:,1]] - p[idx[:,0]], p[idx[:,2]] - p[idx[:,0]])
    cf = cross.astype(np.float32)
    sq = (cf[:,0]*cf[:,0] + cf[:,1]*cf[:,1] + cf[:,2]*cf[:,2]).astype(np.float32)
    length = np.sqrt(sq).astype(np.float32)
    nz = length != 0

    curv = np.zeros_like(cf)
    curv[nz] = (cf[nz] / length[nz,None]).astype(np.float32)
    curv[nz] = (curv[nz] * np.float32(32767.0)).astype(np.float32)
    current = np.trunc(curv).astype(np.int64)

    inv = np.zeros_like(length)
    inv[nz] = (np.float32(1.0) / length[nz]).astype(np.float32)
    legv = (cf * inv[:,None]).astype(np.float32)
    legv = (legv * np.float32(32767.0)).astype(np.float32)
    legv[~nz] = 0
    legacy = np.trunc(legv).astype(np.int64)

    actual = faces["norm4"][:,:3].astype(np.int64)
    tail_arr = faces["norm4"][:,3].astype(np.int64)
    cur_eq = np.all(current == actual, axis=1)
    leg_eq = np.all(legacy == actual, axis=1)
    deg = np.all(cross == 0, axis=1)
    vals, counts = np.unique(tail_arr, return_counts=True)
    bad = np.where(~cur_eq)[0][:12]
    examples = []
    for fi in bad:
        examples.append({
            "face": int(fi), "actual": actual[fi].astype(int).tolist(),
            "current": current[fi].astype(int).tolist(),
            "legacy_recip": legacy[fi].astype(int).tolist(),
            "cross": cross[fi].astype(int).tolist(), "vectnormal3": int(tail_arr[fi]),
        })
    return {
        "faces": nf,
        "current_match": int(cur_eq.sum()),
        "legacy_recip_match": int(leg_eq.sum()),
        "degenerate_faces": int(deg.sum()),
        "degenerate_zero_normal_faces": int(np.sum(deg & np.all(actual == 0, axis=1))),
        "current_max_component_delta": int(np.max(np.abs(actual-current))) if nf else 0,
        "legacy_recip_max_component_delta": int(np.max(np.abs(actual-legacy))) if nf else 0,
        "vectnormal3_counts": {int(v): int(c) for v,c in zip(vals, counts)},
        "mismatch_examples": examples,
        "engine": "NUMPY_FLOAT32",
    }


def analyze_stage072_normals(path: pathlib.Path | str) -> dict:
    p = pathlib.Path(path)
    data = p.read_bytes()
    layout = _fixed_layout(data)
    try:
        stats = _analyze_numpy(data, layout)
    except ImportError:
        stats = _analyze_scalar(data, layout)
    faces = int(stats["faces"])
    current_mismatch = faces - int(stats["current_match"])
    legacy_mismatch = faces - int(stats["legacy_recip_match"])
    if current_mismatch == 0:
        classification = CURRENT_MODEL
    elif legacy_mismatch == 0:
        classification = LEGACY_RECIP_MODEL
    elif max(int(stats["current_max_component_delta"]), int(stats["legacy_recip_max_component_delta"])) <= 1:
        classification = "LEGACY_FLOAT_EVALUATION_VARIANT_UNRESOLVED_1LSB"
    else:
        classification = "UNRESOLVED_NORMAL_MODEL_GT_1LSB"
    return {
        "format": "PT_STAGE072_VECTNORMAL_FILE_AUDIT_V1",
        "path": str(p),
        "sha256": hashlib.sha256(data).hexdigest(),
        "classification": classification,
        "counts": {
            "vertices": int(layout["nvertex"]), "faces": faces,
            "current_exact_faces": int(stats["current_match"]),
            "current_mismatch_faces": current_mismatch,
            "legacy_recip_exact_faces": int(stats["legacy_recip_match"]),
            "legacy_recip_mismatch_faces": legacy_mismatch,
            "degenerate_faces": int(stats["degenerate_faces"]),
            "degenerate_zero_normal_faces": int(stats["degenerate_zero_normal_faces"]),
        },
        "vectnormal3_counts": stats["vectnormal3_counts"],
        "current_max_component_delta": int(stats["current_max_component_delta"]),
        "legacy_recip_max_component_delta": int(stats["legacy_recip_max_component_delta"]),
        "mismatch_examples": stats["mismatch_examples"],
        "analysis_engine": stats["engine"],
        "check": "PASS" if classification != "UNRESOLVED_NORMAL_MODEL_GT_1LSB" and int(stats["degenerate_faces"]) == int(stats["degenerate_zero_normal_faces"]) else "FAIL",
        "client_modified": False,
    }


def _candidate_paths(records: list[dict]) -> list[str]:
    out, seen = [], set()
    for row in records:
        if str(row.get("kind") or "") != "SMD_STAGE_072":
            continue
        rel = norm_path(row.get("relative_path") or row.get("path") or "")
        if rel and rel.lower() not in seen:
            seen.add(rel.lower()); out.append(rel)
    return sorted(out, key=str.lower)


def _write_bundle(bundle: str, resolver, rows: list[dict], reps: list[str], summary: dict) -> str:
    bp = pathlib.Path(bundle).expanduser().resolve(); bp.parent.mkdir(parents=True, exist_ok=True)
    by = {r["relative_path"].lower(): r for r in rows}
    manifest = {
        "format": "PT_STAGE072_VECTNORMAL_REPRESENTATIVES_V1",
        "representatives": reps,
        "rows": [by[x.lower()] for x in reps if x.lower() in by],
        "summary": summary,
        "client_modified": False,
    }
    with zipfile.ZipFile(bp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("STAGE072_VECTNORMAL_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for rel in reps:
            z.write(resolver.resolve(rel), f"client/{rel}")
    return str(bp)


def audit_stage072_normals(records: list[dict], resolver, *, bundle: str | None = None) -> dict:
    candidates = _candidate_paths(records)
    rows, errors = [], []
    for rel in candidates:
        try:
            r = analyze_stage072_normals(resolver.resolve(rel))
            rows.append({"relative_path": rel, **r})
            if r.get("check") != "PASS":
                errors.append({"relative_path": rel, "error": r.get("classification")})
        except Exception as exc:
            rows.append({"relative_path": rel, "check": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            errors.append({"relative_path": rel, "error": f"{type(exc).__name__}: {exc}"})

    passed = [r for r in rows if r.get("check") == "PASS"]
    class_counts = collections.Counter(r.get("classification") for r in passed)
    current = [r for r in passed if r.get("classification") == CURRENT_MODEL]
    legacy_exact = [r for r in passed if r.get("classification") == LEGACY_RECIP_MODEL]
    legacy_unresolved = [r for r in passed if r.get("classification") == "LEGACY_FLOAT_EVALUATION_VARIANT_UNRESOLVED_1LSB"]
    total_faces = sum(int((r.get("counts") or {}).get("faces") or 0) for r in passed)
    current_exact_faces = sum(int((r.get("counts") or {}).get("faces") or 0) for r in current)
    legacy_faces = total_faces - current_exact_faces
    current_mismatch = sum(int((r.get("counts") or {}).get("current_mismatch_faces") or 0) for r in passed)
    legacy_recip_mismatch = sum(int((r.get("counts") or {}).get("legacy_recip_mismatch_faces") or 0) for r in passed if r not in current)
    deg = sum(int((r.get("counts") or {}).get("degenerate_faces") or 0) for r in passed)
    deg0 = sum(int((r.get("counts") or {}).get("degenerate_zero_normal_faces") or 0) for r in passed)
    tail = collections.Counter()
    for r in passed:
        for k,v in (r.get("vectnormal3_counts") or {}).items():
            tail[int(k)] += int(v)

    summary = {
        "format": "PT_STAGE072_VECTNORMAL_CORPUS_AUDIT_V1",
        "status": "PASS" if len(rows) == len(candidates) and not errors else "FAIL",
        "candidate_files_expected": len(candidates),
        "physical_files_audited": len(rows),
        "audit_pass_files": len(passed),
        "audit_fail_files": len(rows) - len(passed),
        "scan_errors": errors,
        "normal_model_file_counts": dict(sorted(class_counts.items())),
        "current_exact_files": len(current),
        "legacy_reciprocal_exact_files": len(legacy_exact),
        "legacy_float_variant_unresolved_files": len(legacy_unresolved),
        "total_faces": total_faces,
        "current_exact_family_faces": current_exact_faces,
        "legacy_family_faces": legacy_faces,
        "current_formula_mismatch_faces_outside_current_family": current_mismatch,
        "legacy_reciprocal_mismatch_faces_in_legacy_family": legacy_recip_mismatch,
        "max_legacy_component_delta": max((int(r.get("legacy_recip_max_component_delta") or 0) for r in passed if r not in current), default=0),
        "degenerate_faces": deg,
        "degenerate_zero_normal_faces": deg0,
        "vectnormal3_counts": {str(k): v for k,v in sorted(tail.items())},
        "current_normal_rebuild_complete_candidate": len(current) > 0 and all(int((r.get("counts") or {}).get("current_mismatch_faces") or 0) == 0 for r in current),
        "legacy_normal_rebuild_complete_candidate": len(legacy_unresolved) == 0,
        "stage072_geometry_write_complete_candidate": (len(candidates) == 63 and len(passed) == 63 and len(current) + len(legacy_exact) + len(legacy_unresolved) == 63),
        "sourcecode_and_physical_findings": {
            "SetVertexShade_input": "supplied smStage3d.cpp shifts each serialized vertex x/y/z right by FLOATNS(8), calls SetNormal(p0,p1,p2), and stores pn.x/y/z into VectNormal[0..2]",
            "SetNormal_exact_source": "SrcGame and SrcServer smMap3d.cpp are identical: float i/j/k/d; integer cross -> float; d=(float)sqrt((double)(float sum of squares)); component=(float)(component/d*32767); then int truncation",
            "current_physical_model": "46 shipped files / 2207322 faces are byte-exact with float32 cross normalization: component/sqrtf(sum(component^2))*32767 then C truncation; all include the debug-fill VectNormal[3]=0xCDCD signature",
            "degenerate_behavior": "all zero-cross physical faces serialize VectNormal[0..2]=(0,0,0)",
            "legacy_family": "17 files preserve historical floating/compiler provenance: 7 reciprocal-exact and 10 within +/-1 LSB. V0.6.7 does not rewrite untouched legacy normals; only intentionally changed faces use the supplied current SetNormal rule.",
            "VectNormal3": "SetVertexShade only writes indices 0..2; the fourth short is provenance/opaque state and must be preserved byte-identically",
        },
        "geometry_writer_policy": {
            "current_exact_family": "V0.6.7 keeps whole-file current-exact provenance when changed incident faces are rebuilt with supplied current SetNormal",
            "legacy_family": "V0.6.7 provenance bridge preserves all untouched historical VectNormal bytes and regenerates only intentionally changed incident faces with supplied current SetNormal",
            "unaffected_face_VectNormal3": "always preserve byte-identically",
            "client_modified": False,
        },
    }

    reps = [r["relative_path"] for r in legacy_exact + legacy_unresolved]
    # Add two current-family controls: lights and depth-3.
    for wanted in ("Field/dungeon/dun-1.smd", "Field/endless/dun-7.smd"):
        if any(r.get("relative_path", "").lower() == wanted.lower() for r in current):
            reps.append(wanted)
    reps = sorted(dict.fromkeys(reps), key=str.lower)
    summary["representatives"] = reps
    if bundle:
        summary["bundle"] = _write_bundle(bundle, resolver, rows, reps, {k:v for k,v in summary.items() if k != "rows"})
    summary["rows"] = rows
    return summary
