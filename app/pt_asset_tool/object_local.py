from __future__ import annotations

"""SMD Model0.62 static object-local transform parser/evaluator.

V1 intentionally targets the flat/no-Physique layout proven by the client corpus.
Rotation keys in the source are incremental local quaternions; the serialized
TmPrevRot matrix beside each key is the accumulated absolute rotation and is
used as source truth for preview/evaluation.
"""

import bisect
import json
import math
import pathlib
import struct
from typing import Any

SMD_HEADER = b"SMD Model data Ver 0.62"
SMD_HEADER_SIZE = 556
SMD_INFO_SIZE = 40
SMD_OBJECT_SIZE = 2236
SMD_VERTEX_SIZE = 24
SMD_FACE_SIZE = 36
SMD_TEXLINK_SIZE = 32
ROT_KEY_SIZE = 20
POS_KEY_SIZE = 16
SCALE_KEY_SIZE = 16
PREVROT_SIZE = 64
ENGINE_UNITS_PER_PREVIEW_FRAME = 160

O_PHYSIQUE_PTR = 16
O_NVERTEX = 84
O_NFACE = 88
O_NTEXLINK = 92
O_NODE_NAME = 172
O_NODE_PARENT = 204
O_TM = 240
O_TM_INVERT = 304
O_Q = 628
O_SCALE = 644
O_POS = 656
O_NROT = 684
O_NPOS = 688
O_NSCALE = 692
O_TM_ROT_FRAME = 696
O_TM_POS_FRAME = 1208
O_TM_SCALE_FRAME = 1720
O_TM_FRAME_CNT = 2232
O_TM_ROTATE = 432
MAX_TM_SEGMENTS = 32


def _cstring(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("latin1", "replace")


def _finite(values) -> bool:
    return all(math.isfinite(float(x)) for x in values)


def _quat_normalize(q: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x*x + y*y + z*z + w*w)
    if n < 1e-20:
        raise ValueError("zero quaternion")
    return (x/n, y/n, z/n, w/n)


def _quat_conjugate(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def _quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw*bx + ax*bw + ay*bz - az*by,
        aw*by - ax*bz + ay*bw + az*bx,
        aw*bz + ax*by - ay*bx + az*bw,
        aw*bw - ax*bx - ay*by - az*bz,
    )


def quat_slerp(a, b, t: float):
    a = _quat_normalize(a)
    b = _quat_normalize(b)
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0.0:
        b = tuple(-x for x in b)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 0.9995:
        out = tuple(x + (y-x)*t for x, y in zip(a, b))
        return _quat_normalize(out)
    theta0 = math.acos(dot)
    sin0 = math.sin(theta0)
    s0 = math.sin((1.0-t)*theta0) / sin0
    s1 = math.sin(t*theta0) / sin0
    return tuple(s0*x + s1*y for x, y in zip(a, b))


def quat_to_matrix4(q):
    x, y, z, w = _quat_normalize(q)
    return (
        (1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), 0.0),
        (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), 0.0),
        (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def quat_to_matrix4_raw(q):
    """Client-compatible quaternion matrix without normalization.

    Legacy effect SMDs intentionally contain non-unit quaternion keys.  The
    original smFMatrixFromQuaternion path preserves their magnitude, which
    becomes affine scale/shear after cumulative multiplication.
    """
    x, y, z, w = (float(v) for v in q)
    return (
        (1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), 0.0),
        (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), 0.0),
        (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _d3dmath_slerp_zero_to(q, alpha: float):
    """Compatibility form of the client's GetRotFrame interpolation.

    smOBJ3D::GetRotFrame calls D3DMath_QuaternionSlerp with the first
    quaternion literally (0,0,0,0) and the *next incremental* key as the
    second quaternion.  For the classic D3DMath slerp equation that reduces
    to sin(alpha*pi/2) * q.  No normalization is performed afterwards.
    """
    t=max(0.0,min(1.0,float(alpha)))
    k=math.sin(t*math.pi*0.5)
    return tuple(k*float(v) for v in q)


def matrix4_transpose(m):
    return tuple(tuple(float(m[c][r]) for c in range(4)) for r in range(4))


def matrix4_inverse(m):
    # Small dependency-free Gauss-Jordan inverse for affine/runtime matrices.
    a=[[float(m[r][c]) for c in range(4)] + [1.0 if r==c else 0.0 for c in range(4)] for r in range(4)]
    for col in range(4):
        pivot=max(range(col,4), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError('singular object-local matrix')
        if pivot != col:
            a[col],a[pivot]=a[pivot],a[col]
        div=a[col][col]
        a[col]=[x/div for x in a[col]]
        for r in range(4):
            if r==col: continue
            f=a[r][col]
            if f:
                a[r]=[a[r][c]-f*a[col][c] for c in range(8)]
    return tuple(tuple(a[r][c+4] for c in range(4)) for r in range(4))


def matrix4_identity_error(m):
    return max(abs(float(m[r][c])-(1.0 if r==c else 0.0)) for r in range(4) for c in range(4))


def matrix4_mul(a, b):
    return tuple(tuple(sum(a[r][k]*b[k][c] for k in range(4)) for c in range(4)) for r in range(4))


def matrix4_to_quat(m):
    # Standard column-vector rotation matrix -> (x,y,z,w), branch-stable.
    r00, r01, r02 = m[0][:3]
    r10, r11, r12 = m[1][:3]
    r20, r21, r22 = m[2][:3]
    trace = r00 + r11 + r22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (r21-r12) / s
        y = (r02-r20) / s
        z = (r10-r01) / s
    elif r00 > r11 and r00 > r22:
        s = math.sqrt(max(0.0, 1.0+r00-r11-r22)) * 2.0
        w = (r21-r12) / s
        x = 0.25 * s
        y = (r01+r10) / s
        z = (r02+r20) / s
    elif r11 > r22:
        s = math.sqrt(max(0.0, 1.0+r11-r00-r22)) * 2.0
        w = (r02-r20) / s
        x = (r01+r10) / s
        y = 0.25 * s
        z = (r12+r21) / s
    else:
        s = math.sqrt(max(0.0, 1.0+r22-r00-r11)) * 2.0
        w = (r10-r01) / s
        x = (r02+r20) / s
        y = (r12+r21) / s
        z = 0.25 * s
    return _quat_normalize((x, y, z, w))


def _matrix_from_flat(values):
    return tuple(tuple(float(values[r*4+c]) for c in range(4)) for r in range(4))


def _matrix_max_error(a, b) -> float:
    return max(abs(float(a[r][c])-float(b[r][c])) for r in range(4) for c in range(4))


def _validate_frames(keys: list[dict[str, Any]], label: str) -> None:
    frames = [int(k["frame"]) for k in keys]
    if frames != sorted(frames):
        raise ValueError(f"{label} frames are not monotonic: {frames[:12]}")
    if len(set(frames)) != len(frames):
        raise ValueError(f"{label} contains duplicate frames")


def _parse_tm_frame_table(data: bytes, obj_off: int, offset: int, count: int, key_count: int, label: str) -> list[dict[str, int]]:
    if not 0 <= int(count) <= MAX_TM_SEGMENTS:
        raise ValueError(f"{label} TmFrameCnt={count} outside 0..{MAX_TM_SEGMENTS}")
    rows: list[dict[str, int]] = []
    for slot in range(int(count)):
        start, end, pos_num, pos_cnt = struct.unpack_from("<4i", data, obj_off + offset + slot*16)
        if pos_cnt < 0 or pos_num < 0:
            raise ValueError(f"{label} segment[{slot}] negative pos_num/pos_cnt")
        if end < start:
            raise ValueError(f"{label} segment[{slot}] end before start: {start}..{end}")
        if pos_cnt and pos_num >= int(key_count):
            raise ValueError(f"{label} segment[{slot}] pos_num={pos_num} outside key_count={key_count}")
        rows.append({"slot": slot, "start": start, "end": end, "pos_num": pos_num, "pos_cnt": pos_cnt})
    return rows


def _active_tm_segment(segments: list[dict[str, Any]], frame: float) -> dict[str, Any] | None:
    for seg in segments:
        if int(seg.get("pos_cnt") or 0) > 0 and float(seg["start"]) <= float(frame) < float(seg["end"]):
            return seg
    return None



def _fixed_matrix4(raw):
    return tuple(tuple(float(raw[r*4+c]) / 256.0 for c in range(4)) for r in range(4))


def _identity_error(m):
    ident = tuple(tuple(1.0 if r == c else 0.0 for c in range(4)) for r in range(4))
    return _matrix_max_error(m, ident)


def validate_hierarchy(parsed: dict[str, Any]) -> dict[str, Any]:
    """Resolve NodeParent with the runtime's LinkObject semantics.

    The client scans objects in file order and assigns the first case-insensitive
    NodeName match.  A missing NodeParent is *not* fatal: pParent remains null and
    the object is later inserted in TmSort as a root.  Duplicate NodeNames are
    therefore legal (though diagnostically interesting).
    """
    objects = parsed["objects"]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for obj in objects:
        by_name.setdefault(str(obj["name"]).casefold(), []).append(obj)

    duplicate_groups = {
        vals[0]["name"]: [int(x["index"]) for x in vals]
        for vals in by_name.values() if len(vals) > 1
    }
    roots: list[str] = []
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for obj in objects:
        obj["parent_index"] = None
        obj["runtime_parent_resolution"] = "ROOT_NO_NODEPARENT"
        parent_name = str(obj.get("parent") or "")
        if not parent_name:
            roots.append(obj["name"])
            continue
        hits = by_name.get(parent_name.casefold()) or []
        if not hits:
            # Exact client behavior: LinkObject leaves pParent == 0.
            obj["runtime_parent_resolution"] = "UNRESOLVED_RUNTIME_ROOT"
            roots.append(obj["name"])
            unresolved.append({"object": obj["name"], "object_index": int(obj["index"]), "parent": parent_name})
            continue
        parent = hits[0]
        if parent is obj:
            raise ValueError(f"NodeParent self-cycle under runtime first-match semantics: object={obj['name']!r}")
        obj["parent_index"] = int(parent["index"])
        obj["runtime_parent_resolution"] = "FIRST_CASE_INSENSITIVE_MATCH"
        rel = matrix4_mul(tuple(tuple(x for x in row) for row in obj["tm_matrix"]),
                          tuple(tuple(x for x in row) for row in parent["tm_invert_matrix"]))
        obj["bind_local_matrix"] = [list(r) for r in rel]
        obj["bind_local_identity_error"] = _identity_error(rel)
        edges.append({"parent": parent["name"], "parent_index": int(parent["index"]),
                      "child": obj["name"], "child_index": int(obj["index"]),
                      "child_motion_class": obj["motion_class"],
                      "bind_local_identity_error": obj["bind_local_identity_error"]})

    # Cycle check on the *effective* runtime parent graph.
    visiting: set[int] = set()
    done: set[int] = set()
    def visit(obj: dict[str, Any]) -> None:
        idx = int(obj["index"])
        if idx in done:
            return
        if idx in visiting:
            raise ValueError(f"NodeParent cycle detected at object index={idx} name={obj['name']!r}")
        visiting.add(idx)
        pi = obj.get("parent_index")
        if pi is not None:
            visit(objects[int(pi)])
        visiting.remove(idx)
        done.add(idx)
    for obj in objects:
        visit(obj)

    return {
        "root_objects": roots,
        "parent_edges": edges,
        "parent_edge_count": len(edges),
        "unresolved_parent_count": len(unresolved),
        "unresolved_parents": unresolved,
        "duplicate_node_name_group_count": len(duplicate_groups),
        "duplicate_node_name_groups": duplicate_groups,
        "parent_resolution_semantics": "CLIENT_LINKOBJECT_FIRST_MATCH_UNRESOLVED_AS_ROOT",
    }


def parse_object_local_smd(path: str | pathlib.Path, *, strict_v1: bool = False) -> dict[str, Any]:
    path = pathlib.Path(path).expanduser().resolve()
    data = path.read_bytes()
    if len(data) < SMD_HEADER_SIZE or not data.startswith(SMD_HEADER):
        raise ValueError("not SMD Model data Ver 0.62")
    object_count = struct.unpack_from("<i", data, 24)[0]
    if object_count <= 0 or SMD_HEADER_SIZE + object_count*SMD_INFO_SIZE > len(data):
        raise ValueError(f"invalid object_count={object_count}")

    objects = []
    for idx in range(object_count):
        info_off = SMD_HEADER_SIZE + idx*SMD_INFO_SIZE
        info_name = _cstring(data[info_off:info_off+32])
        obj_len, obj_off = struct.unpack_from("<2i", data, info_off+32)
        if obj_off < 0 or obj_len < SMD_OBJECT_SIZE or obj_off+obj_len > len(data):
            raise ValueError(f"object[{idx}] invalid bounds start={obj_off} length={obj_len}")
        physique_ptr = struct.unpack_from("<I", data, obj_off+O_PHYSIQUE_PTR)[0]
        if physique_ptr:
            raise ValueError(f"object[{idx}] {info_name}: Physique is not object-local static V1")
        nv = struct.unpack_from("<i", data, obj_off+O_NVERTEX)[0]
        nf = struct.unpack_from("<i", data, obj_off+O_NFACE)[0]
        nt = struct.unpack_from("<i", data, obj_off+O_NTEXLINK)[0]
        nr = struct.unpack_from("<i", data, obj_off+O_NROT)[0]
        np = struct.unpack_from("<i", data, obj_off+O_NPOS)[0]
        ns = struct.unpack_from("<i", data, obj_off+O_NSCALE)[0]
        tm_frame_cnt = struct.unpack_from("<i", data, obj_off+O_TM_FRAME_CNT)[0]
        if min(nv, nf, nt, nr, np, ns, tm_frame_cnt) < 0:
            raise ValueError(f"object[{idx}] negative count")
        if tm_frame_cnt > MAX_TM_SEGMENTS:
            raise ValueError(f"object[{idx}] TmFrameCnt={tm_frame_cnt} > {MAX_TM_SEGMENTS}")

        arr = obj_off + SMD_OBJECT_SIZE + nv*SMD_VERTEX_SIZE + nf*SMD_FACE_SIZE + nt*SMD_TEXLINK_SIZE
        arrays_end = arr + nr*ROT_KEY_SIZE + np*POS_KEY_SIZE + ns*SCALE_KEY_SIZE + nr*PREVROT_SIZE
        if arrays_end != obj_off + obj_len:
            raise ValueError(
                f"object[{idx}] serialized length mismatch expected_end={obj_off+obj_len} parsed_end={arrays_end}"
            )

        rot_keys = []
        for i in range(nr):
            frame, x, y, z, w = struct.unpack_from("<i4f", data, arr+i*ROT_KEY_SIZE)
            if not _finite((x, y, z, w)):
                raise ValueError(f"object[{idx}] non-finite rotation key {i}")
            norm = math.sqrt(x*x+y*y+z*z+w*w)
            if norm < 1e-8:
                raise ValueError(f"object[{idx}] zero/degenerate rotation quaternion key={i}")
            rot_keys.append({"frame": frame, "q_incremental_xyzw": [x, y, z, w], "q_norm": norm})
        _validate_frames(rot_keys, f"object[{idx}].rot")

        pos_off = arr + nr*ROT_KEY_SIZE
        pos_keys = []
        for i in range(np):
            frame, x, y, z = struct.unpack_from("<i3f", data, pos_off+i*POS_KEY_SIZE)
            if not _finite((x, y, z)):
                raise ValueError(f"object[{idx}] non-finite position key {i}")
            pos_keys.append({"frame": frame, "xyz": [x, y, z]})
        _validate_frames(pos_keys, f"object[{idx}].pos")

        scale_off = pos_off + np*POS_KEY_SIZE
        scale_keys = []
        for i in range(ns):
            frame, sx, sy, sz = struct.unpack_from("<4i", data, scale_off+i*SCALE_KEY_SIZE)
            scale_keys.append({"frame": frame, "raw": [sx, sy, sz], "xyz": [sx/256.0, sy/256.0, sz/256.0]})
        _validate_frames(scale_keys, f"object[{idx}].scale")

        prev_off = scale_off + ns*SCALE_KEY_SIZE
        prevrot = []
        cumulative_max_error = 0.0
        normalized_cumulative_max_error = 0.0
        max_quaternion_norm_deviation = 0.0
        for i in range(nr):
            flat = struct.unpack_from("<16f", data, prev_off+i*PREVROT_SIZE)
            if not _finite(flat):
                raise ValueError(f"object[{idx}] non-finite TmPrevRot matrix {i}")
            matrix = _matrix_from_flat(flat)
            # q_absolute is diagnostic only for affine rows; preview uses the full matrix.
            try:
                q_abs = matrix4_to_quat(matrix)
            except Exception:
                q_abs = (0.0, 0.0, 0.0, 1.0)
            prevrot.append({"frame": rot_keys[i]["frame"], "matrix": [list(r) for r in matrix], "q_absolute_xyzw": list(q_abs)})
            q_inc = tuple(rot_keys[i]["q_incremental_xyzw"])
            max_quaternion_norm_deviation=max(max_quaternion_norm_deviation, abs(float(rot_keys[i]["q_norm"])-1.0))
            previous_matrix = tuple(tuple(float(v) for v in row) for row in prevrot[i-1]["matrix"]) if i else None
            predicted_raw = quat_to_matrix4_raw(q_inc) if i == 0 else matrix4_mul(previous_matrix, quat_to_matrix4_raw(q_inc))
            predicted_norm = quat_to_matrix4(q_inc) if i == 0 else matrix4_mul(previous_matrix, quat_to_matrix4(q_inc))
            cumulative_max_error = max(cumulative_max_error, _matrix_max_error(predicted_raw, matrix))
            normalized_cumulative_max_error = max(normalized_cumulative_max_error, _matrix_max_error(predicted_norm, matrix))
        if nr and cumulative_max_error > 2e-4:
            raise ValueError(
                f"OBJECT_LOCAL_ROTATION_SOURCE_MISMATCH object[{idx}] raw quaternion accumulation does not reproduce TmPrevRot "
                f"max_error={cumulative_max_error:.8g}"
            )
        legacy_affine = bool(nr and (max_quaternion_norm_deviation > 2e-3 or normalized_cumulative_max_error > 2e-4))
        rotation_mode = "LEGACY_AFFINE_RAW_QUATERNION_MATRIX" if legacy_affine else "ACCUMULATED_TM_PREV_ROT"

        tm_raw = struct.unpack_from("<16i", data, obj_off+O_TM)
        tm_invert_raw = struct.unpack_from("<16i", data, obj_off+O_TM_INVERT)
        tm_rotate_raw = struct.unpack_from("<16i", data, obj_off+O_TM_ROTATE)
        base_q = struct.unpack_from("<4f", data, obj_off+O_Q)
        base_scale_raw = struct.unpack_from("<3i", data, obj_off+O_SCALE)
        base_pos_raw = struct.unpack_from("<3i", data, obj_off+O_POS)
        rot_frames = _parse_tm_frame_table(data, obj_off, O_TM_ROT_FRAME, tm_frame_cnt, nr, f"object[{idx}].rot")
        pos_frames = _parse_tm_frame_table(data, obj_off, O_TM_POS_FRAME, tm_frame_cnt, np, f"object[{idx}].pos")
        scale_frames = _parse_tm_frame_table(data, obj_off, O_TM_SCALE_FRAME, tm_frame_cnt, ns, f"object[{idx}].scale")
        channels = [name for name, count in (("ROT", nr), ("POS", np), ("SCALE", ns)) if count]
        obj = {
            "index": idx,
            "info_name": info_name,
            "name": _cstring(data[obj_off+O_NODE_NAME:obj_off+O_NODE_NAME+32]) or info_name,
            "parent": _cstring(data[obj_off+O_NODE_PARENT:obj_off+O_NODE_PARENT+32]),
            "object_offset": obj_off,
            "object_length": obj_len,
            "nVertex": nv, "nFace": nf, "nTexLink": nt,
            "nRot": nr, "nPos": np, "nScale": ns, "TmFrameCnt": tm_frame_cnt,
            "channels_serialized": channels,
            "tm_raw": list(tm_raw),
            "tm_invert_raw": list(tm_invert_raw),
            "tm_rotate_raw": list(tm_rotate_raw),
            "tm_matrix": [list(r) for r in _fixed_matrix4(tm_raw)],
            "tm_invert_matrix": [list(r) for r in _fixed_matrix4(tm_invert_raw)],
            "tm_rotate_matrix": [list(r) for r in _fixed_matrix4(tm_rotate_raw)],
            "base_q_xyzw": list(base_q),
            "base_scale_raw": list(base_scale_raw),
            "base_scale_xyz": [v/256.0 for v in base_scale_raw],
            "base_pos_raw": list(base_pos_raw),
            "base_pos_xyz": [v/256.0 for v in base_pos_raw],
            "rot_keys": rot_keys,
            "pos_keys": pos_keys,
            "scale_keys": scale_keys,
            "tm_prev_rot": prevrot,
            "rot_frames": rot_frames,
            "pos_frames": pos_frames,
            "scale_frames": scale_frames,
            "segmented_tmframe": bool(tm_frame_cnt),
            "rotation_semantics_check": "PASS" if nr else "NOT_APPLICABLE",
            "rotation_mode": rotation_mode if nr else "NOT_APPLICABLE",
            "legacy_affine_rotation": bool(legacy_affine),
            "rotation_cumulative_max_error": cumulative_max_error,
            "rotation_normalized_cumulative_max_error": normalized_cumulative_max_error,
            "max_quaternion_norm_deviation": max_quaternion_norm_deviation,
        }
        objects.append(obj)

    result = {
        "format": "PT_OBJECT_LOCAL_SOURCE_V1",
        "source": str(path),
        "file_size": len(data),
        "object_count": object_count,
        "objects": objects,
    }
    for obj in objects:
        _annotate_motion(obj)
    hierarchy = validate_hierarchy(result)
    result.update(hierarchy)
    result["animated_child_count"] = sum(1 for o in objects if o.get("parent_index") is not None and o.get("motion_class") == "ANIMATED")
    result["animated_object_count"] = sum(1 for o in objects if o["motion_class"] == "ANIMATED")
    result["hold_object_count"] = sum(1 for o in objects if o["motion_class"] == "HOLD")
    result["object_local_object_count"] = sum(1 for o in objects if o["channels_serialized"])
    result["legacy_affine_object_count"] = sum(1 for o in objects if o.get("legacy_affine_rotation"))
    result["legacy_affine_objects"] = [o["name"] for o in objects if o.get("legacy_affine_rotation")]
    result["max_engine_frame"] = max((o["max_engine_frame"] for o in objects), default=0)
    return result


def _interp_vec(keys: list[dict[str, Any]], frame: float, field: str, fallback):
    if not keys:
        return tuple(float(x) for x in fallback)
    frames = [k["frame"] for k in keys]
    if frame <= frames[0]:
        return tuple(float(x) for x in keys[0][field])
    if frame >= frames[-1]:
        return tuple(float(x) for x in keys[-1][field])
    hi = bisect.bisect_right(frames, frame)
    lo = hi-1
    f0, f1 = frames[lo], frames[hi]
    t = (float(frame)-f0)/(f1-f0)
    a, b = keys[lo][field], keys[hi][field]
    return tuple(float(x)+(float(y)-float(x))*t for x, y in zip(a, b))


def _interp_rot(obj: dict[str, Any], frame: float):
    rows = obj["tm_prev_rot"]
    if not rows:
        return _quat_normalize(tuple(obj["base_q_xyzw"]))
    frames = [r["frame"] for r in rows]
    if frame <= frames[0]:
        return tuple(rows[0]["q_absolute_xyzw"])
    if frame >= frames[-1]:
        return tuple(rows[-1]["q_absolute_xyzw"])
    hi = bisect.bisect_right(frames, frame)
    lo = hi-1
    t = (float(frame)-frames[lo])/(frames[hi]-frames[lo])
    return quat_slerp(tuple(rows[lo]["q_absolute_xyzw"]), tuple(rows[hi]["q_absolute_xyzw"]), t)


def _interp_rot_matrix(obj: dict[str, Any], frame: float):
    rows=obj["tm_prev_rot"]
    if not rows:
        return quat_to_matrix4_raw(tuple(obj["base_q_xyzw"]))
    frames=[r["frame"] for r in rows]
    if frame <= frames[0]:
        return tuple(tuple(float(v) for v in row) for row in rows[0]["matrix"])
    if frame >= frames[-1]:
        return tuple(tuple(float(v) for v in row) for row in rows[-1]["matrix"])
    hi=bisect.bisect_right(frames, frame)
    lo=hi-1
    alpha=(float(frame)-frames[lo])/(frames[hi]-frames[lo])
    prev=tuple(tuple(float(v) for v in row) for row in rows[lo]["matrix"])
    q_next=tuple(obj["rot_keys"][hi]["q_incremental_xyzw"])
    step=quat_to_matrix4_raw(_d3dmath_slerp_zero_to(q_next, alpha))
    return matrix4_mul(prev, step)


def _interp_vec_segmented(keys: list[dict[str, Any]], segments: list[dict[str, Any]], frame: float, field: str, fallback):
    seg = _active_tm_segment(segments, frame)
    if seg is None or not keys:
        return tuple(float(x) for x in fallback)
    base = int(seg["pos_num"])
    if not 0 <= base < len(keys):
        raise ValueError(f"segmented {field} base={base} outside key_count={len(keys)}")
    if float(keys[base]["frame"]) > float(frame):
        return tuple(float(x) for x in fallback)
    for i in range(base, len(keys)-1):
        s = int(keys[i]["frame"]); e = int(keys[i+1]["frame"])
        if s <= frame < e:
            t = (float(frame)-s)/float(e-s)
            a, b = keys[i][field], keys[i+1][field]
            return tuple(float(x)+(float(y)-float(x))*t for x,y in zip(a,b))
    # Real runtime data is expected to contain a following sentinel key for the
    # active segment. Treat absence as malformed rather than guessing/holding.
    raise ValueError(f"segmented {field} track has no interpolation interval for frame={frame} base={base}")


def _interp_scale_segmented(obj: dict[str, Any], frame: float):
    keys = obj["scale_keys"]
    seg = _active_tm_segment(obj.get("scale_frames") or [], frame)
    if seg is None or not keys:
        return (1.0, 1.0, 1.0)
    base = int(seg["pos_num"])
    if not 0 <= base < len(keys):
        raise ValueError(f"segmented scale base={base} outside key_count={len(keys)}")
    if int(keys[base]["frame"]) > frame:
        return (1.0, 1.0, 1.0)
    for i in range(base, len(keys)-1):
        s = int(keys[i]["frame"]); e = int(keys[i+1]["frame"])
        if s <= frame < e:
            # Match the client's 8-bit fixed interpolation rather than using a
            # floating lerp. This matters at intermediate frames.
            alpha = (int(frame-s) << 8) // int(e-s)
            a = keys[i]["raw"]; b = keys[i+1]["raw"]
            raw = [int(a[j]) + (((int(b[j])-int(a[j])) * alpha) >> 8) for j in range(3)]
            return tuple(v/256.0 for v in raw)
    raise ValueError(f"segmented scale track has no interpolation interval for frame={frame} base={base}")


def _interp_rot_matrix_segmented(obj: dict[str, Any], frame: float):
    seg = _active_tm_segment(obj.get("rot_frames") or [], frame)
    rows = obj["tm_prev_rot"]
    keys = obj["rot_keys"]
    if seg is None or not keys:
        return tuple(tuple(float(v) for v in row) for row in obj["tm_rotate_matrix"])
    base = int(seg["pos_num"])
    if not 0 <= base < len(keys):
        raise ValueError(f"segmented rotation base={base} outside key_count={len(keys)}")
    if int(keys[base]["frame"]) > frame:
        return tuple(tuple(1.0 if r == c else 0.0 for c in range(4)) for r in range(4))
    for i in range(base, len(keys)-1):
        s = int(keys[i]["frame"]); e = int(keys[i+1]["frame"])
        if s <= frame < e:
            alpha = (float(frame)-s)/float(e-s)
            prev = tuple(tuple(float(v) for v in row) for row in rows[i]["matrix"])
            q_next = tuple(keys[i+1]["q_incremental_xyzw"])
            step = quat_to_matrix4_raw(_d3dmath_slerp_zero_to(q_next, alpha))
            return matrix4_mul(prev, step)
    raise ValueError(f"segmented rotation track has no interpolation interval for frame={frame} base={base}")


def local_runtime_matrix(obj: dict[str, Any], engine_frame: float):
    # Runtime matrix evaluation always uses serialized TmPrevRot + raw next
    # incremental quaternion when rotation keys exist.  Standard preview paths
    # may still expose quaternion TRS, but affine world evaluation must preserve
    # every source matrix bit/scale component for all objects in the scene.
    segmented = bool(int(obj.get("TmFrameCnt") or 0))
    if segmented:
        qmat=[list(r) for r in _interp_rot_matrix_segmented(obj, engine_frame)]
    elif obj.get("rot_keys"):
        qmat=[list(r) for r in _interp_rot_matrix(obj, engine_frame)]
    else:
        qmat=[list(r) for r in quat_to_matrix4(_interp_rot(obj, engine_frame))]
    scale = _interp_scale_segmented(obj, engine_frame) if segmented else _interp_vec(obj["scale_keys"], engine_frame, "xyz", obj["base_scale_xyz"])
    scale_active = _active_tm_segment(obj.get("scale_frames") or [], engine_frame) is not None if segmented else bool(obj["scale_keys"])
    if scale_active:
        sm=((scale[0],0.0,0.0,0.0),(0.0,scale[1],0.0,0.0),(0.0,0.0,scale[2],0.0),(0.0,0.0,0.0,1.0))
        qmat=[list(r) for r in matrix4_mul(tuple(tuple(r) for r in qmat),sm)]
    pos = _interp_vec_segmented(obj["pos_keys"], obj.get("pos_frames") or [], engine_frame, "xyz", obj["base_pos_xyz"]) if segmented else _interp_vec(obj["pos_keys"], engine_frame, "xyz", obj["base_pos_xyz"])
    qmat[3][0],qmat[3][1],qmat[3][2]=map(float,pos)
    qmat[0][3]=qmat[1][3]=qmat[2][3]=0.0
    qmat[3][3]=1.0
    return tuple(tuple(float(v) for v in r) for r in qmat)


def runtime_world_matrices(parsed: dict[str, Any], engine_frame: float):
    objects=parsed["objects"]
    cache={}
    def eval_idx(idx):
        if idx in cache: return cache[idx]
        obj=objects[idx]
        local=local_runtime_matrix(obj, engine_frame)
        pi=obj.get("parent_index")
        world=local if pi is None else matrix4_mul(local, eval_idx(int(pi)))
        cache[idx]=world
        return world
    for i in range(len(objects)): eval_idx(i)
    return cache


def normalized_world_affine_delta(parsed: dict[str, Any], object_index: int, engine_frame: float, reference_frame: float):
    ref=runtime_world_matrices(parsed, reference_frame)[int(object_index)]
    cur=runtime_world_matrices(parsed, engine_frame)[int(object_index)]
    # Row-vector runtime convention: W_ref * D = W_cur.  Blender consumes the
    # transpose, so D_col = (inv(W_ref)*W_cur)^T.
    drow=matrix4_mul(matrix4_inverse(ref),cur)
    return matrix4_transpose(drow)


def absolute_sample(obj: dict[str, Any], engine_frame: float) -> dict[str, Any]:
    if int(obj.get("TmFrameCnt") or 0):
        pos = _interp_vec_segmented(obj["pos_keys"], obj.get("pos_frames") or [], engine_frame, "xyz", obj["base_pos_xyz"])
        scale = _interp_scale_segmented(obj, engine_frame)
        rotm = _interp_rot_matrix_segmented(obj, engine_frame)
        try:
            rot = matrix4_to_quat(rotm)
        except Exception:
            rot = (0.0, 0.0, 0.0, 1.0)
    else:
        pos = _interp_vec(obj["pos_keys"], engine_frame, "xyz", obj["base_pos_xyz"])
        scale = _interp_vec(obj["scale_keys"], engine_frame, "xyz", obj["base_scale_xyz"])
        rot = _interp_rot(obj, engine_frame)
    return {"engine_frame": float(engine_frame), "location": list(pos), "scale": list(scale), "rotation_xyzw": list(rot)}


def normalized_sample(obj: dict[str, Any], engine_frame: float, reference_frame: float | None = None) -> dict[str, Any]:
    if reference_frame is None:
        reference_frame = float(obj.get("reference_engine_frame", 0))
    if obj.get("legacy_affine_rotation"):
        refm=local_runtime_matrix(obj, reference_frame)
        curm=local_runtime_matrix(obj, engine_frame)
        drow=matrix4_mul(matrix4_inverse(refm),curm)
        return {
            "engine_frame": float(engine_frame),
            "location": [float(drow[3][i]) for i in range(3)],
            "scale": [1.0,1.0,1.0],
            "rotation_xyzw": [0.0,0.0,0.0,1.0],
            "affine_matrix_row": [list(r) for r in drow],
            "affine_identity_error": matrix4_identity_error(drow),
        }
    ref = absolute_sample(obj, reference_frame)
    cur = absolute_sample(obj, engine_frame)
    loc = [cur["location"][i]-ref["location"][i] for i in range(3)]
    scale = []
    zero_scale_axes = []
    base_scale = [float(v) for v in obj.get("base_scale_xyz", (1.0, 1.0, 1.0))]
    for axis, (a, b) in enumerate(zip(cur["scale"], ref["scale"])):
        if abs(b) < 1e-12:
            # Some real effect SMDs intentionally spawn from scale zero.  The
            # client interpolates TmScale directly and multiplies it into qmat;
            # there is no division by the first key.  A relative first-key
            # normalization is therefore singular and semantically wrong.
            # For those axes, express the source scale absolutely over the
            # imported/static bind scale instead.  Non-zero reference axes keep
            # the established first-key-normalized behavior.
            zero_scale_axes.append(axis)
            bind = base_scale[axis] if axis < len(base_scale) else 1.0
            if abs(bind) < 1e-12:
                if abs(a) > 1e-8:
                    raise ValueError(
                        f"ZERO_SCALE_REFERENCE_AND_BIND_ZERO axis={axis} "
                        f"ref={ref['scale']} base={base_scale} cur={cur['scale']}"
                    )
                scale.append(0.0)
            else:
                scale.append(a / bind)
        else:
            scale.append(a/b)
    q_ref = tuple(ref["rotation_xyzw"])
    q_cur = tuple(cur["rotation_xyzw"])
    q_delta = _quat_normalize(_quat_mul(_quat_conjugate(q_ref), q_cur))
    return {
        "engine_frame": float(engine_frame),
        "location": loc,
        "scale": scale,
        "rotation_xyzw": list(q_delta),
        "scale_reference_semantics": (
            "ZERO_SCALE_SPAWN_ABSOLUTE_OVER_STATIC_BIND" if zero_scale_axes
            else "FIRST_KEY_RATIO"
        ),
        "zero_scale_reference_axes": zero_scale_axes,
    }


def _annotate_motion(obj: dict[str, Any]) -> None:
    frames = {int(k["frame"]) for group in (obj["rot_keys"], obj["pos_keys"], obj["scale_keys"]) for k in group}
    segment_boundaries: set[int] = set()
    if int(obj.get("TmFrameCnt") or 0):
        for group in (obj.get("rot_frames") or [], obj.get("pos_frames") or [], obj.get("scale_frames") or []):
            for seg in group:
                if int(seg.get("pos_cnt") or 0) > 0:
                    segment_boundaries.add(int(seg["start"]))
                    segment_boundaries.add(int(seg["end"]))
        frames.update(segment_boundaries)
    frames = sorted(frames)
    ref = frames[0] if frames else 0
    maxf = frames[-1] if frames else 0
    obj["reference_engine_frame"] = ref
    obj["max_engine_frame"] = maxf
    obj["source_key_frames"] = frames
    obj["segment_boundaries"] = sorted(segment_boundaries)
    ref_abs = absolute_sample(obj, ref) if frames else {"scale": list(obj.get("base_scale_xyz", (1.0, 1.0, 1.0)))}
    zero_scale_axes = [i for i, v in enumerate(ref_abs.get("scale", ())) if abs(float(v)) < 1e-12]
    obj["zero_scale_reference_axes"] = zero_scale_axes
    obj["scale_reference_semantics"] = (
        "ZERO_SCALE_SPAWN_ABSOLUTE_OVER_STATIC_BIND" if zero_scale_axes
        else "FIRST_KEY_RATIO"
    )
    if not frames:
        obj["motion_class"] = "NONE"
        obj["channels_animated"] = []
        return
    changed = {"ROT": False, "POS": False, "SCALE": False}
    for f in frames:
        s = normalized_sample(obj, f, ref)
        if obj.get("legacy_affine_rotation"):
            d=s["affine_matrix_row"]
            linear_err=max(abs(float(d[r][c])-(1.0 if r==c else 0.0)) for r in range(3) for c in range(3))
            if linear_err > 1e-5: changed["ROT"] = True
            if max(abs(float(d[3][i])) for i in range(3)) > 1e-5: changed["POS"] = True
        else:
            if max(abs(v) for v in s["location"]) > 1e-5:
                changed["POS"] = True
            if max(abs(v-1.0) for v in s["scale"]) > 1e-5:
                changed["SCALE"] = True
            q = s["rotation_xyzw"]
            # q and -q represent the same rotation.
            if abs(abs(q[3])-1.0) > 1e-6 or max(abs(q[i]) for i in range(3)) > 1e-5:
                changed["ROT"] = True
    obj["channels_animated"] = [c for c in ("ROT", "POS", "SCALE") if changed[c]]
    if obj.get("legacy_affine_rotation") and changed["ROT"]:
        obj["channels_animated"] = ["ROT_AFFINE" if c=="ROT" else c for c in obj["channels_animated"]]
    obj["motion_class"] = "ANIMATED" if obj["channels_animated"] else "HOLD"


def preview_engine_frames(obj: dict[str, Any], step: int = ENGINE_UNITS_PER_PREVIEW_FRAME) -> list[int]:
    ref = int(obj.get("reference_engine_frame", 0))
    end = int(obj.get("max_engine_frame", ref))
    if end < ref:
        raise ValueError("max frame precedes reference frame")
    frames = set(int(x) for x in obj.get("source_key_frames") or [])
    frames.update(int(x) for x in obj.get("segment_boundaries") or [])
    if step <= 0:
        raise ValueError("preview step must be positive")
    f = ref
    while f <= end:
        frames.add(f)
        f += step
    frames.add(end)
    return sorted(x for x in frames if ref <= x <= end)


def compact_report(parsed: dict[str, Any], *, include_key_samples: bool = True) -> dict[str, Any]:
    rows = []
    for obj in parsed["objects"]:
        row = {
            "index": obj["index"], "name": obj["name"], "parent": obj["parent"],
            "nVertex": obj["nVertex"], "nFace": obj["nFace"], "nTexLink": obj["nTexLink"],
            "nRot": obj["nRot"], "nPos": obj["nPos"], "nScale": obj["nScale"], "TmFrameCnt": obj["TmFrameCnt"],
            "segmented_tmframe": bool(obj.get("segmented_tmframe")),
            "rot_frames": obj.get("rot_frames", []), "pos_frames": obj.get("pos_frames", []), "scale_frames": obj.get("scale_frames", []),
            "channels_serialized": obj["channels_serialized"], "channels_animated": obj["channels_animated"],
            "motion_class": obj["motion_class"], "reference_engine_frame": obj["reference_engine_frame"],
            "max_engine_frame": obj["max_engine_frame"], "rotation_semantics_check": obj["rotation_semantics_check"],
            "rotation_mode": obj.get("rotation_mode"), "legacy_affine_rotation": obj.get("legacy_affine_rotation",False),
            "rotation_cumulative_max_error": obj["rotation_cumulative_max_error"],
            "rotation_normalized_cumulative_max_error": obj.get("rotation_normalized_cumulative_max_error",0.0),
            "max_quaternion_norm_deviation": obj.get("max_quaternion_norm_deviation",0.0),
            "parent_index": obj.get("parent_index"),
            "bind_local_identity_error": obj.get("bind_local_identity_error"),
            "scale_reference_semantics": obj.get("scale_reference_semantics"),
            "zero_scale_reference_axes": obj.get("zero_scale_reference_axes", []),
        }
        if include_key_samples and obj["source_key_frames"]:
            frames = obj["source_key_frames"]
            pick = sorted(set([frames[0], frames[len(frames)//2], frames[-1]]))
            row["normalized_samples"] = [normalized_sample(obj, f, obj["reference_engine_frame"]) for f in pick]
        rows.append(row)
    return {
        "format": parsed["format"], "source": parsed["source"], "file_size": parsed["file_size"],
        "object_count": parsed["object_count"], "object_local_object_count": parsed["object_local_object_count"],
        "animated_object_count": parsed["animated_object_count"], "hold_object_count": parsed["hold_object_count"],
        "max_engine_frame": parsed["max_engine_frame"], "objects": rows,
        "root_objects": parsed.get("root_objects", []),
        "parent_edges": parsed.get("parent_edges", []),
        "parent_edge_count": parsed.get("parent_edge_count", 0),
        "unresolved_parent_count": parsed.get("unresolved_parent_count", 0),
        "unresolved_parents": parsed.get("unresolved_parents", []),
        "duplicate_node_name_group_count": parsed.get("duplicate_node_name_group_count", 0),
        "duplicate_node_name_groups": parsed.get("duplicate_node_name_groups", {}),
        "parent_resolution_semantics": parsed.get("parent_resolution_semantics"),
        "animated_child_count": parsed.get("animated_child_count", 0),
        "legacy_affine_object_count": parsed.get("legacy_affine_object_count",0),
        "legacy_affine_objects": parsed.get("legacy_affine_objects",[]),
        "hierarchy_semantics": "LOCAL_QMAT_TIMES_PARENT_TMRESULT",
        "rotation_semantics": "RAW_QUATERNION_MATRIX_OR_ACCUMULATED_TM_PREV_ROT",
        "source_rot_key_semantics": "INCREMENTAL_LOCAL_QUATERNION",
        "preview_reference": "FIRST_KEY_NORMALIZED_OBJECT_LOCAL_WITH_ZERO_SCALE_SPAWN_EXCEPTION",
    }


def write_compact_report(path: str | pathlib.Path, parsed: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compact_report(parsed), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return path
