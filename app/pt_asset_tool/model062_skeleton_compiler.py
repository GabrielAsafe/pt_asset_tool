from __future__ import annotations

import hashlib
import math
import struct
from typing import Any

from .model062_static_compiler import (
    MAGIC,
    HEADER_SIZE,
    OBJECT_INFO_SIZE,
    OBJECT_HEADER_SIZE,
    FIXED_SCALE,
    HEAD_NEW_NORMAL,
    _fixed_name,
    _identity_i32,
    _identity_f32,
)

FORMAT = "PT_MODEL062_SKELETON_COMPILER_V1"
MAX_OBJECTS = 128
MAX_FRAME_RANGES = 32
ROT_SIZE = 20
POS_SIZE = 16
SCALE_SIZE = 16
MATRIX_SIZE = 64


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _vec3(value: Any, label: str, default: tuple[float, float, float] | None = None) -> tuple[float, float, float]:
    if value is None and default is not None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"SMB_{label}_VEC3_REQUIRED")
    out = tuple(float(x) for x in value)
    if not all(math.isfinite(x) for x in out):
        raise ValueError(f"SMB_{label}_FINITE_REQUIRED")
    return out  # type: ignore[return-value]


def _axis_angle(value: Any, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, dict):
        raise ValueError(f"SMB_{label}_OBJECT_REQUIRED")
    axis = _vec3(value.get("axis"), f"{label}_AXIS")
    angle = float(value.get("angle") or 0.0)
    if not math.isfinite(angle):
        raise ValueError(f"SMB_{label}_ANGLE_FINITE_REQUIRED")
    length = math.sqrt(sum(v * v for v in axis))
    if abs(angle) > 0.0 and length <= 1e-12:
        raise ValueError(f"SMB_{label}_AXIS_NONZERO_REQUIRED")
    if length > 1e-12:
        axis = tuple(v / length for v in axis)  # type: ignore[assignment]
    else:
        axis = (0.0, 0.0, 1.0)
    return axis[0], axis[1], axis[2], angle


def _quat_from_axis(x: float, y: float, z: float, angle: float) -> tuple[float, float, float, float]:
    half = angle / 2.0
    sn = math.sin(half)
    return (sn * x, sn * y, sn * z, math.cos(half))


def _matrix_from_quat(q: tuple[float, float, float, float], translation: tuple[int, int, int] = (0, 0, 0)) -> list[float]:
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy), 0.0,
        2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx), 0.0,
        2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy), 0.0,
        float(translation[0]) / FIXED_SCALE, float(translation[1]) / FIXED_SCALE, float(translation[2]) / FIXED_SCALE, 1.0,
    ]


def _matmul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for j in range(4):
        for i in range(4):
            out[4 * j + i] = sum(a[4 * j + k] * b[4 * k + i] for k in range(4))
    return out


def _to_fixed_matrix(m: list[float]) -> bytes:
    vals = []
    for row in range(4):
        for col in range(4):
            v = m[row * 4 + col]
            vals.append(int(round(v * FIXED_SCALE)))
    return struct.pack("<16i", *vals)


def _inverse_rigid(m: list[float]) -> list[float]:
    # Source authoring matrices here are rotation + translation only.  Invert the
    # 3x3 by transpose and translate by -T*R^-1 using the legacy row-vector layout.
    r = [[m[row * 4 + col] for col in range(3)] for row in range(3)]
    rt = [[r[col][row] for col in range(3)] for row in range(3)]
    t = [m[12], m[13], m[14]]
    it = [-(t[0] * rt[0][c] + t[1] * rt[1][c] + t[2] * rt[2][c]) for c in range(3)]
    return [
        rt[0][0], rt[0][1], rt[0][2], 0.0,
        rt[1][0], rt[1][1], rt[1][2], 0.0,
        rt[2][0], rt[2][1], rt[2][2], 0.0,
        it[0], it[1], it[2], 1.0,
    ]


def _frame_entry(start: int, end: int, pos_num: int, pos_cnt: int) -> bytes:
    return struct.pack("<4i", start, end, pos_num, pos_cnt)


def _animation_ranges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    animations = payload.get("animations") or []
    if not isinstance(animations, list) or len(animations) > MAX_FRAME_RANGES:
        raise ValueError("SMB_ANIMATION_RANGE_LIMIT_32")
    out: list[dict[str, Any]] = []
    previous_end = -1
    for idx, row in enumerate(animations):
        if not isinstance(row, dict):
            raise ValueError(f"SMB_ANIMATION_OBJECT_REQUIRED:{idx}")
        start = int(row.get("start_frame") or 0)
        end = int(row.get("end_frame") or 0)
        if start < 0 or end <= start:
            raise ValueError(f"SMB_ANIMATION_FRAME_RANGE_INVALID:{idx}:{start}:{end}")
        if start < previous_end:
            raise ValueError(f"SMB_ANIMATION_RANGES_OVERLAP:{idx}")
        previous_end = end
        tracks = row.get("tracks") or {}
        if not isinstance(tracks, dict):
            raise ValueError(f"SMB_ANIMATION_TRACKS_OBJECT_REQUIRED:{idx}")
        out.append({"name": str(row.get("name") or f"anim_{idx}"), "start": start, "end": end, "tracks": tracks})
    return out


def _check_track_frames(keys: list[dict[str, Any]], start: int, end: int, label: str) -> None:
    frames = [int(k.get("frame")) for k in keys]
    if frames != sorted(frames) or len(frames) != len(set(frames)):
        raise ValueError(f"SMB_{label}_FRAMES_MUST_BE_STRICT_ASCENDING")
    if any(frame < start or frame > end for frame in frames):
        raise ValueError(f"SMB_{label}_FRAME_OUTSIDE_RANGE:{start}:{end}")
    if keys and len(keys) == 1:
        raise ValueError(f"SMB_{label}_TRACK_REQUIRES_ZERO_OR_AT_LEAST_2_KEYS")


def _object_blob(spec: dict[str, Any], animations: list[dict[str, Any]]) -> tuple[bytes, dict[str, Any]]:
    name = str(spec.get("name") or "").strip()
    parent = str(spec.get("parent") or "").strip()
    position = _vec3(spec.get("position"), "BIND_POSITION", (0.0, 0.0, 0.0))
    fixed_pos = tuple(int(round(v * FIXED_SCALE)) for v in position)
    bind_axis = _axis_angle(spec.get("rotation") or {"axis": [0, 0, 1], "angle": 0}, "BIND_ROTATION")
    bind_quat = _quat_from_axis(*bind_axis)
    bind_matrix = _matrix_from_quat(bind_quat, fixed_pos)
    bind_inverse = _inverse_rigid(bind_matrix)
    scale = _vec3(spec.get("scale"), "BIND_SCALE", (1.0, 1.0, 1.0))
    fixed_scale = tuple(int(round(v * FIXED_SCALE)) for v in scale)

    rot_bytes = bytearray(); pos_bytes = bytearray(); scale_bytes = bytearray(); prev_rot_bytes = bytearray()
    rot_frames = [b"\0" * 16 for _ in range(MAX_FRAME_RANGES)]
    pos_frames = [b"\0" * 16 for _ in range(MAX_FRAME_RANGES)]
    scale_frames = [b"\0" * 16 for _ in range(MAX_FRAME_RANGES)]
    rot_count = pos_count = scale_count = 0

    for aidx, anim in enumerate(animations):
        track = anim["tracks"].get(name) or anim["tracks"].get(name.casefold()) or {}
        if track and not isinstance(track, dict):
            raise ValueError(f"SMB_TRACK_OBJECT_REQUIRED:{name}:{aidx}")
        track = track or {}
        rkeys = track.get("rotation_axis_angle") or []
        pkeys = track.get("position") or []
        skeys = track.get("scale") or []
        if not all(isinstance(x, list) for x in (rkeys, pkeys, skeys)):
            raise ValueError(f"SMB_TRACK_LIST_REQUIRED:{name}:{aidx}")
        _check_track_frames(rkeys, anim["start"], anim["end"], f"ROT:{name}:{aidx}")
        _check_track_frames(pkeys, anim["start"], anim["end"], f"POS:{name}:{aidx}")
        _check_track_frames(skeys, anim["start"], anim["end"], f"SCALE:{name}:{aidx}")

        rot_start = rot_count
        cumulative = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        for key in rkeys:
            aa = _axis_angle({"axis": key.get("axis"), "angle": key.get("angle")}, f"ROT_KEY:{name}:{aidx}")
            q = _quat_from_axis(*aa)
            # Source stores the quaternion-converted key and the cumulative
            # delta-rotation matrix for the same key in TmPrevRot.
            rot_bytes += struct.pack("<i4f", int(key["frame"]), *q)
            cumulative = _matmul(cumulative, _matrix_from_quat(q))
            prev_rot_bytes += struct.pack("<16f", *cumulative)
            rot_count += 1
        if rkeys:
            rot_frames[aidx] = _frame_entry(anim["start"], anim["end"], rot_start, len(rkeys))

        pos_start = pos_count
        for key in pkeys:
            p = _vec3(key.get("value"), f"POS_KEY:{name}:{aidx}")
            pos_bytes += struct.pack("<i3f", int(key["frame"]), *p)
            pos_count += 1
        if pkeys:
            pos_frames[aidx] = _frame_entry(anim["start"], anim["end"], pos_start, len(pkeys))

        scale_start = scale_count
        for key in skeys:
            s = _vec3(key.get("value"), f"SCALE_KEY:{name}:{aidx}")
            fs = tuple(int(round(v * FIXED_SCALE)) for v in s)
            scale_bytes += struct.pack("<4i", int(key["frame"]), *fs)
            scale_count += 1
        if skeys:
            scale_frames[aidx] = _frame_entry(anim["start"], anim["end"], scale_start, len(skeys))

    hdr = bytearray(OBJECT_HEADER_SIZE)
    struct.pack_into("<I", hdr, 0, HEAD_NEW_NORMAL)
    # No mesh/material/physique storage is needed for a bone pattern node.
    struct.pack_into("<iiiii", hdr, 76, 0, 0, 0, 0, 0)
    struct.pack_into("<I", hdr, 96, 1)
    struct.pack_into("<I", hdr, 100, 0x01 | 0x04 | 0x08 | 0x10 | 0x20)
    hdr[172:204] = _fixed_name(name, 32)
    hdr[204:236] = b"\0" * 32 if not parent else _fixed_name(parent, 32)
    hdr[240:304] = _to_fixed_matrix(bind_matrix)
    hdr[304:368] = _to_fixed_matrix(bind_inverse)
    hdr[368:432] = _identity_f32()
    hdr[432:496] = _to_fixed_matrix(_matrix_from_quat(bind_quat))
    hdr[496:560] = _to_fixed_matrix(bind_matrix)
    hdr[560:624] = _to_fixed_matrix(bind_matrix)
    struct.pack_into("<4f", hdr, 628, *bind_quat)
    struct.pack_into("<6i", hdr, 644, *fixed_scale, *fixed_pos)
    struct.pack_into("<4I", hdr, 668, 1 if rot_count else 0, 1 if pos_count else 0, 1 if scale_count else 0, 1 if rot_count else 0)
    struct.pack_into("<3i", hdr, 684, rot_count, pos_count, scale_count)
    for idx in range(MAX_FRAME_RANGES):
        hdr[696 + idx * 16:696 + (idx + 1) * 16] = rot_frames[idx]
        hdr[1208 + idx * 16:1208 + (idx + 1) * 16] = pos_frames[idx]
        hdr[1720 + idx * 16:1720 + (idx + 1) * 16] = scale_frames[idx]
    struct.pack_into("<i", hdr, 2232, len(animations))

    blob = bytes(hdr + rot_bytes + pos_bytes + scale_bytes + prev_rot_bytes)
    expected = OBJECT_HEADER_SIZE + rot_count * ROT_SIZE + pos_count * POS_SIZE + scale_count * SCALE_SIZE + rot_count * MATRIX_SIZE
    if len(blob) != expected:
        raise AssertionError(f"SMB_OBJECT_SIZE_INTERNAL:{name}:{len(blob)}:{expected}")
    return blob, {
        "name": name,
        "parent": parent or None,
        "rotation_key_count": rot_count,
        "position_key_count": pos_count,
        "scale_key_count": scale_count,
        "animation_count": len(animations),
    }


def compile_skeleton_model062(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    skeleton = payload.get("skeleton") if isinstance(payload.get("skeleton"), dict) else payload
    bones = skeleton.get("bones") or []
    if not isinstance(bones, list) or not 1 <= len(bones) <= MAX_OBJECTS:
        raise ValueError("SMB_BONE_COUNT_1_TO_128_REQUIRED")
    animations = _animation_ranges(skeleton)

    names: dict[str, str] = {}
    for idx, bone in enumerate(bones):
        if not isinstance(bone, dict):
            raise ValueError(f"SMB_BONE_OBJECT_REQUIRED:{idx}")
        name = str(bone.get("name") or "").strip()
        folded = name.casefold()
        if not name or folded in names:
            raise ValueError(f"SMB_BONE_NAME_DUPLICATE_OR_EMPTY:{name}")
        _fixed_name(name, 32)
        names[folded] = name
    for bone in bones:
        parent = str(bone.get("parent") or "").strip()
        if parent and parent.casefold() not in names:
            raise ValueError(f"SMB_BONE_PARENT_NOT_FOUND:{bone.get('name')}:{parent}")
        if parent and parent.casefold() == str(bone.get("name") or "").casefold():
            raise ValueError(f"SMB_BONE_SELF_PARENT:{parent}")

    # Fail closed on parent cycles because runtime LinkObject recursively relies on this hierarchy.
    parent_by = {str(b["name"]).casefold(): str(b.get("parent") or "").casefold() for b in bones}
    for start in parent_by:
        seen: set[str] = set()
        cur = start
        while cur:
            if cur in seen:
                raise ValueError(f"SMB_BONE_PARENT_CYCLE:{names.get(start, start)}")
            seen.add(cur)
            cur = parent_by.get(cur, "")

    object_blobs: list[bytes] = []
    object_meta: list[dict[str, Any]] = []
    for bone in bones:
        blob, meta = _object_blob(bone, animations)
        object_blobs.append(blob)
        object_meta.append(meta)

    mat_point = HEADER_SIZE + OBJECT_INFO_SIZE * len(bones)
    first_obj = mat_point  # SMB/bone patterns carry no material group.
    header = bytearray(HEADER_SIZE)
    header[:len(MAGIC)] = MAGIC
    struct.pack_into("<iiiii", header, 24, len(bones), 0, mat_point, first_obj, len(animations))
    for idx, anim in enumerate(animations):
        header[44 + idx * 16:44 + (idx + 1) * 16] = _frame_entry(anim["start"], anim["end"], 0, 0)

    infos = bytearray(); offset = first_obj
    for meta, blob in zip(object_meta, object_blobs):
        infos += _fixed_name(str(meta["name"]), 32)
        infos += struct.pack("<ii", len(blob), offset)
        offset += len(blob)
    data = bytes(header + infos + b"".join(object_blobs))
    if offset != len(data):
        raise AssertionError("SMB_PATTERN_SIZE_INTERNAL")

    return data, {
        "writer": "MODEL062_SOURCE_NATIVE_SKELETON_V1",
        "format": FORMAT,
        "magic": MAGIC.decode("ascii"),
        "bone_count": len(bones),
        "animation_count": len(animations),
        "animations": [{"name": a["name"], "start_frame": a["start"], "end_frame": a["end"]} for a in animations],
        "bones": object_meta,
        "material_count": 0,
        "supports_hierarchy": True,
        "supports_rotation_tracks": True,
        "supports_position_tracks": True,
        "supports_scale_tracks": True,
        "track_input_semantics": "ASE_DELTA_AXIS_ANGLE_COMPATIBLE",
        "deterministic_pointer_policy": True,
        "sha256": _sha(data),
        "source_evidence": [
            "Shared/rendering/legacy_3d/object/LegacyPatternSerialization.h",
            "Shared/rendering/legacy_3d/object/LegacyObjectDiskLayout.h",
            "Shared/rendering/legacy_3d/object/LegacyObjectSerialization.h",
            "Shared/rendering/legacy_3d/ase/AseGeometryReader.inl",
            "Shared/rendering/legacy_3d/ase/AseBoneMerge.inl",
            "Shared/rendering/legacy_3d/object/ObjectTrackSampling.h",
        ],
    }
