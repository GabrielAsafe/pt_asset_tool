from __future__ import annotations

import hashlib
import math
import os
import pathlib
import struct
import tempfile
from typing import Any

from .motion_core import load_smb_evaluator

ROUNDTRIP_FORMAT = "PT_SMB_TRACK_ROUNDTRIP_V1"
WRITER_FORMAT = "PT_SMB_KEY_WRITER_CANDIDATE_V1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    if len(before) != len(after):
        raise ValueError("SMB writer must preserve file size")
    return [i for i, (a, b) in enumerate(zip(before, after)) if a != b]


def _parse_smb_tracks_relaxed(evaluator: Any, path: pathlib.Path, data: bytes) -> dict[str, Any]:
    """Parse serialized SMB tracks without requiring a closed bone hierarchy.

    Animation evaluation needs every parent to exist so it can build TmSort.
    A byte-preserving writer for an existing key does not: some real support
    skeletons (for example separate NPC/head SMBs) intentionally reference a
    parent supplied by another model/skeleton. Keep those two contracts
    separate instead of weakening the animation evaluator.
    """
    if len(data) < evaluator.SIZE_DFILE_HEADER:
        raise RuntimeError("SMB too small")
    if not data.startswith(evaluator.SMD_HEADER):
        raise RuntimeError("invalid SMB header")

    obj_count = evaluator.i32(data, 24)
    mat_count = evaluator.i32(data, 28)
    tm_frame_count = evaluator.i32(data, 40)
    if obj_count < 0:
        raise RuntimeError(f"invalid object count={obj_count}")
    if mat_count != 0:
        raise RuntimeError(f"expected skeleton MatCounter=0, got {mat_count}")
    if not 0 <= tm_frame_count <= evaluator.MAX_SEGMENTS:
        raise RuntimeError(f"invalid TmFrameCounter={tm_frame_count}")

    bones: list[dict[str, Any]] = []
    for idx in range(obj_count):
        io = evaluator.SIZE_DFILE_HEADER + idx * evaluator.SIZE_DFILE_OBJINFO
        if io + evaluator.SIZE_DFILE_OBJINFO > len(data):
            raise RuntimeError(f"SMB object table truncated at {idx}")
        name_info = evaluator.cstr(data[io:io + 32])
        length = evaluator.i32(data, io + 32)
        start = evaluator.i32(data, io + 36)
        if length < evaluator.SIZE_OBJ3D or start < 0 or start + length > len(data):
            raise RuntimeError(f"SMB object[{idx}] invalid range start={start} length={length}")
        raw = data[start:start + evaluator.SIZE_OBJ3D]
        name = evaluator.cstr(raw[evaluator.O_NODENAME:evaluator.O_NODENAME + 32])
        parent = evaluator.cstr(raw[evaluator.O_NODEPARENT:evaluator.O_NODEPARENT + 32])
        if name != name_info:
            raise RuntimeError(f"object table/name mismatch {name_info!r} != {name!r}")

        physique_ptr = evaluator.u32(raw, getattr(evaluator, "O_PHYSIQUE_PTR", 16))
        nv = evaluator.i32(raw, evaluator.O_NVERTEX)
        nf = evaluator.i32(raw, evaluator.O_NFACE)
        nt = evaluator.i32(raw, evaluator.O_NTEXLINK)
        nr = evaluator.i32(raw, evaluator.O_TMROTCNT)
        np = evaluator.i32(raw, evaluator.O_TMPOSCNT)
        ns = evaluator.i32(raw, evaluator.O_TMSCALECNT)
        if min(nv, nf, nt, nr, np, ns) < 0:
            raise RuntimeError(f"{name}: negative serialized count")

        rot_base = start + evaluator.SIZE_OBJ3D + nv * evaluator.SIZE_VERTEX + nf * evaluator.SIZE_FACE + nt * evaluator.SIZE_TEXLINK
        pos_base = rot_base + nr * evaluator.SIZE_TM_ROT
        scale_base = pos_base + np * evaluator.SIZE_TM_POS
        prevrot_base = scale_base + ns * evaluator.SIZE_TM_SCALE
        has_physique = physique_ptr != 0
        physique_base = prevrot_base + nr * evaluator.SIZE_FMATRIX if has_physique else None
        end = (physique_base + nv * 32) if has_physique else (prevrot_base + nr * evaluator.SIZE_FMATRIX)
        if end != start + length:
            raise RuntimeError(f"SMB layout mismatch for {name}: {end}!={start+length}")

        rot = [struct.unpack_from("<i4f", data, rot_base + k * evaluator.SIZE_TM_ROT) for k in range(nr)]
        pos = [struct.unpack_from("<i3f", data, pos_base + k * evaluator.SIZE_TM_POS) for k in range(np)]
        scale = [struct.unpack_from("<4i", data, scale_base + k * evaluator.SIZE_TM_SCALE) for k in range(ns)]
        prevrot = [evaluator.matrix_f32(data, prevrot_base + k * evaluator.SIZE_FMATRIX) for k in range(nr)]
        bones.append({
            "index": idx,
            "name": name,
            "parent_name": parent,
            "rot": rot,
            "pos": pos,
            "scale": scale,
            "prevrot": prevrot,
            "has_physique": has_physique,
            "physique_base": physique_base,
            "physique_bytes": nv * 32 if has_physique else 0,
        })

    name_counts: dict[str, int] = {}
    for b in bones:
        name = str(b["name"])
        name_counts[name] = name_counts.get(name, 0) + 1
    names = set(name_counts)
    duplicate_node_names = sorted([name for name, count in name_counts.items() if count > 1], key=str.casefold)
    header_frames = []
    for slot in range(tm_frame_count):
        start_fr, end_fr, pos_num, pos_cnt = struct.unpack_from("<4i", data, 44 + slot * 16)
        header_frames.append({
            "slot": slot, "start": start_fr, "end": end_fr,
            "pos_num": pos_num, "pos_cnt": pos_cnt,
        })
    missing_parents = sorted({
        str(b["parent_name"]) for b in bones
        if b.get("parent_name") and str(b["parent_name"]) not in names
    })
    return {
        "obj_count": obj_count,
        "tm_frame_count": tm_frame_count,
        "header_frames": header_frames,
        "bones": bones,
        "missing_parent_names": missing_parents,
        "duplicate_node_names": duplicate_node_names,
        "node_names_unique": not duplicate_node_names,
        "hierarchy_closed": not missing_parents and not duplicate_node_names,
        "serialized_layout_closed": True,
    }


def parse_smb_structural(project_root: pathlib.Path, path: pathlib.Path) -> dict[str, Any]:
    """Parse exact SMB serialized tracks without requiring a closed hierarchy.

    This is a structural/writer contract only.  A file with external parents is
    not thereby certified for standalone animation evaluation.
    """
    evaluator = load_smb_evaluator(pathlib.Path(project_root))
    path = pathlib.Path(path)
    return _parse_smb_tracks_relaxed(evaluator, path, path.read_bytes())


def _layout_for_bones(project_root: pathlib.Path, path: pathlib.Path) -> tuple[Any, dict, list[dict[str, Any]], bytes]:
    evaluator = load_smb_evaluator(pathlib.Path(project_root))
    path = pathlib.Path(path)
    data = path.read_bytes()
    parsed = _parse_smb_tracks_relaxed(evaluator, path, data)
    infos = []
    for idx in range(int(parsed["obj_count"])):
        io = evaluator.SIZE_DFILE_HEADER + idx * evaluator.SIZE_DFILE_OBJINFO
        name = evaluator.cstr(data[io:io + 32])
        length = evaluator.i32(data, io + 32)
        start = evaluator.i32(data, io + 36)
        raw = data[start:start + evaluator.SIZE_OBJ3D]
        physique_ptr = evaluator.u32(raw, getattr(evaluator, "O_PHYSIQUE_PTR", 16))
        nv = evaluator.i32(raw, evaluator.O_NVERTEX)
        nf = evaluator.i32(raw, evaluator.O_NFACE)
        nt = evaluator.i32(raw, evaluator.O_NTEXLINK)
        nr = evaluator.i32(raw, evaluator.O_TMROTCNT)
        np = evaluator.i32(raw, evaluator.O_TMPOSCNT)
        ns = evaluator.i32(raw, evaluator.O_TMSCALECNT)
        rot_base = start + evaluator.SIZE_OBJ3D + nv * evaluator.SIZE_VERTEX + nf * evaluator.SIZE_FACE + nt * evaluator.SIZE_TEXLINK
        pos_base = rot_base + nr * evaluator.SIZE_TM_ROT
        scale_base = pos_base + np * evaluator.SIZE_TM_POS
        prevrot_base = scale_base + ns * evaluator.SIZE_TM_SCALE
        has_physique = physique_ptr != 0
        physique_base = prevrot_base + nr * evaluator.SIZE_FMATRIX if has_physique else None
        end = (physique_base + nv * 32) if has_physique else (prevrot_base + nr * evaluator.SIZE_FMATRIX)
        if end != start + length:
            raise RuntimeError(f"SMB layout mismatch for {name}: {end}!={start+length}")
        infos.append({
            "index": idx, "name": name, "start": start, "length": length,
            "rot_count": nr, "pos_count": np, "scale_count": ns,
            "rot_base": rot_base, "pos_base": pos_base, "scale_base": scale_base,
            "prevrot_base": prevrot_base,
            "has_physique": has_physique, "physique_base": physique_base,
            "physique_bytes": nv * 32 if has_physique else 0,
        })
    return evaluator, parsed, infos, data


def first_editable_key(project_root: pathlib.Path, path: pathlib.Path) -> dict[str, Any] | None:
    """Return the first existing editable key without changing the SMB.

    Preference is position, then rotation, then scale.  The helper is used by
    corpus probes so they can exercise the writer without duplicating relaxed
    SMB layout parsing or weakening animation hierarchy rules.
    """
    _evaluator, parsed, _infos, _before = _layout_for_bones(project_root, path)
    for track in ("pos", "rot", "scale"):
        for bone in parsed["bones"]:
            rows = list(bone.get(track) or [])
            if not rows:
                continue
            row = list(rows[0])
            return {
                "bone": bone["name"],
                "track": track,
                "key_index": 0,
                "frame": int(row[0]),
                "values": row[1:],
                "hierarchy_closed": bool(parsed.get("hierarchy_closed", True)),
                "missing_parent_names": list(parsed.get("missing_parent_names", [])),
            }
    return None


def validate_track_roundtrip(project_root: pathlib.Path, path: pathlib.Path) -> dict[str, Any]:
    evaluator, parsed, infos, before = _layout_for_bones(project_root, path)
    buf = bytearray(before)
    rewritten = {"rot": 0, "pos": 0, "scale": 0, "prevrot": 0}
    for info, bone in zip(infos, parsed["bones"]):
        if info["name"] != bone["name"]:
            raise RuntimeError("SMB writer bone order mismatch")
        for k, row in enumerate(bone["rot"]):
            struct.pack_into("<i4f", buf, info["rot_base"] + k * evaluator.SIZE_TM_ROT, int(row[0]), *map(float, row[1:]))
            rewritten["rot"] += 1
        for k, row in enumerate(bone["pos"]):
            struct.pack_into("<i3f", buf, info["pos_base"] + k * evaluator.SIZE_TM_POS, int(row[0]), *map(float, row[1:]))
            rewritten["pos"] += 1
        for k, row in enumerate(bone["scale"]):
            struct.pack_into("<4i", buf, info["scale_base"] + k * evaluator.SIZE_TM_SCALE, *map(int, row))
            rewritten["scale"] += 1
        for k, matrix in enumerate(bone["prevrot"]):
            struct.pack_into("<16f", buf, info["prevrot_base"] + k * evaluator.SIZE_FMATRIX, *map(float, matrix))
            rewritten["prevrot"] += 1
    rebuilt = bytes(buf)
    changed = _changed_offsets(before, rebuilt)
    return {
        "format": ROUNDTRIP_FORMAT,
        "status": "PASS" if not changed else "FAIL",
        "source": str(pathlib.Path(path).resolve()),
        "source_sha256": _sha(before),
        "rebuilt_sha256": _sha(rebuilt),
        "byte_identical": not changed,
        "changed_byte_count": len(changed),
        "rewritten_records": rewritten,
        "bone_count": len(parsed["bones"]),
        "tm_frame_count": int(parsed["tm_frame_count"]),
        "hierarchy_closed": bool(parsed.get("hierarchy_closed", True)),
        "missing_parent_names": list(parsed.get("missing_parent_names", [])),
        "client_modified": False,
    }


def _find_bone(infos: list[dict[str, Any]], parsed: dict[str, Any], bone_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    q = str(bone_name).strip().casefold()
    hits = [(i, b) for i, b in zip(infos, parsed["bones"]) if str(b["name"]).casefold() == q]
    if not hits:
        raise KeyError(f"SMB bone not found: {bone_name}")
    if len(hits) != 1:
        raise RuntimeError(f"SMB bone name ambiguous: {bone_name}")
    return hits[0]


def patch_key(
    project_root: pathlib.Path,
    source: pathlib.Path,
    output: pathlib.Path,
    *,
    bone: str,
    track: str,
    key_index: int,
    x: float | int | None = None,
    y: float | int | None = None,
    z: float | int | None = None,
    w: float | None = None,
) -> dict[str, Any]:
    evaluator, parsed, infos, before = _layout_for_bones(project_root, source)
    info, parsed_bone = _find_bone(infos, parsed, bone)
    track = str(track).strip().lower()
    if track not in {"pos", "rot", "scale"}:
        raise ValueError("track must be pos, rot or scale")
    rows = list(parsed_bone[track])
    idx = int(key_index)
    if not 0 <= idx < len(rows):
        raise IndexError(f"{track} key index out of range: {idx}/{len(rows)}")
    original = list(rows[idx])
    requested = {k: v for k, v in {"x": x, "y": y, "z": z, "w": w}.items() if v is not None}
    if not requested:
        raise ValueError("no key component edit requested")
    if track != "rot" and w is not None:
        raise ValueError("w component is valid only for rot track")

    buf = bytearray(before)
    allowed: set[int] = set()
    if track == "rot":
        base = int(info["rot_base"]) + idx * evaluator.SIZE_TM_ROT
        values = list(map(float, original[1:5]))
        names = ["x", "y", "z", "w"]
        for ci, name in enumerate(names):
            if requested.get(name) is None:
                continue
            val = float(requested[name])
            if not math.isfinite(val):
                raise ValueError(f"non-finite rotation component: {name}={val}")
            values[ci] = val
            off = base + 4 + ci * 4
            struct.pack_into("<f", buf, off, val)
            allowed.update(range(off, off + 4))
    elif track == "pos":
        base = int(info["pos_base"]) + idx * evaluator.SIZE_TM_POS
        values = list(map(float, original[1:4]))
        for ci, name in enumerate(["x", "y", "z"]):
            if requested.get(name) is None:
                continue
            val = float(requested[name])
            if not math.isfinite(val) or abs(val) > 1e9:
                raise ValueError(f"unsafe/non-finite position component: {name}={val}")
            values[ci] = val
            off = base + 4 + ci * 4
            struct.pack_into("<f", buf, off, val)
            allowed.update(range(off, off + 4))
    else:
        base = int(info["scale_base"]) + idx * evaluator.SIZE_TM_SCALE
        values = list(map(int, original[1:4]))
        for ci, name in enumerate(["x", "y", "z"]):
            if requested.get(name) is None:
                continue
            valf = float(requested[name])
            if not math.isfinite(valf) or not valf.is_integer():
                raise ValueError(f"scale component must be an int32 value: {name}={requested[name]}")
            val = int(valf)
            if not -(2**31) <= val <= 2**31 - 1:
                raise ValueError(f"scale component out of int32 range: {name}={val}")
            values[ci] = val
            off = base + 4 + ci * 4
            struct.pack_into("<i", buf, off, val)
            allowed.update(range(off, off + 4))

    after = bytes(buf)
    changed = _changed_offsets(before, after)
    if not changed:
        raise ValueError("requested SMB key edit is a no-op")
    outside = [off for off in changed if off not in allowed]
    if outside:
        raise AssertionError(f"SMB writer changed bytes outside allowlist: {outside[:32]}")

    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    os.close(fd)
    tmp = pathlib.Path(tmp_name)
    try:
        tmp.write_bytes(after)
        reparsed = _parse_smb_tracks_relaxed(evaluator, tmp, tmp.read_bytes())
        rb = next(b for b in reparsed["bones"] if str(b["name"]).casefold() == str(bone).casefold())
        got = rb[track][idx]
        # Frame is immutable in this candidate. Compare requested components
        # after their file-format quantization (float32 or int32).
        for ci, name in enumerate(["x", "y", "z"] + (["w"] if track == "rot" else []), start=1):
            if name not in requested:
                continue
            expected = values[ci - 1]
            actual = got[ci]
            if track in {"pos", "rot"}:
                expected = struct.unpack("<f", struct.pack("<f", float(expected)))[0]
                if float(actual) != float(expected):
                    raise AssertionError(f"SMB reparse mismatch {name}: {actual}!={expected}")
            elif int(actual) != int(expected):
                raise AssertionError(f"SMB reparse mismatch {name}: {actual}!={expected}")
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)

    return {
        "format": WRITER_FORMAT,
        "status": "PASS",
        "authorization": "CANDIDATE_PT_BUILD_ONLY",
        "source": str(pathlib.Path(source).resolve()),
        "output": str(output),
        "bone": parsed_bone["name"],
        "track": track,
        "key_index": idx,
        "frame": int(original[0]),
        "requested": requested,
        "source_sha256": _sha(before),
        "output_sha256": _sha(after),
        "file_size_preserved": len(before) == len(after),
        "changed_byte_count": len(changed),
        "changed_offsets": changed,
        "allowed_offsets_only": not outside,
        "hierarchy_closed": bool(parsed.get("hierarchy_closed", True)),
        "missing_parent_names": list(parsed.get("missing_parent_names", [])),
        "client_modified": False,
        "production_authorized": False,
        "limitations": [
            "existing keyframes only",
            "frame timestamps and segment tables are immutable",
            "no key insertion/deletion",
            "no client publish",
        ],
    }
