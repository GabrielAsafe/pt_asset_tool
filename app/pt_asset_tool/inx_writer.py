from __future__ import annotations

import hashlib
import os
import pathlib
import struct
import tempfile
from typing import Any

import pt_inx_motion_core_v2 as inxcore

FORMAT = "PT_INX_MOTION_WRITER_CANDIDATE_V1"
ROUNDTRIP_FORMAT = "PT_INX_MOTION_ROUNDTRIP_V1"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _u32_bytes(value: int) -> list[int]:
    if not 0 <= int(value) <= 0xFFFFFFFF:
        raise ValueError(f"u32 out of range: {value}")
    value = int(value)
    return [(value >> (8 * i)) & 0xFF for i in range(4)]


def _pack_le_bytes(parts: list[int]) -> int:
    if len(parts) != 4 or any(not 0 <= int(v) <= 0xFF for v in parts):
        raise ValueError("four byte values required")
    return sum(int(v) << (8 * i) for i, v in enumerate(parts))


def encode_start(frame: int, code: int) -> tuple[int, int]:
    """Inverse of pt_inx_motion_core_v2.decode_start()."""
    f = _u32_bytes(frame)
    c = _u32_bytes(code)
    raw_kw = _pack_le_bytes([f[0], c[2], f[1], c[3]])
    raw_frame = _pack_le_bytes([f[3], c[1], f[2], c[0]])
    decoded, ok, keyword = inxcore.decode_start(raw_kw, raw_frame, int(code))
    if decoded != int(frame) or not ok or keyword != int(code):
        raise AssertionError("start encoder inverse check failed")
    return raw_kw, raw_frame


def encode_end(frame: int, code: int) -> tuple[int, int]:
    """Inverse of pt_inx_motion_core_v2.decode_end()."""
    f = _u32_bytes(frame)
    c = _u32_bytes(code)
    raw_kw = _pack_le_bytes([f[2], c[1], f[3], c[0]])
    raw_frame = _pack_le_bytes([f[0], c[3], f[1], c[2]])
    decoded, ok, keyword = inxcore.decode_end(raw_kw, raw_frame, int(code))
    if decoded != int(frame) or not ok or keyword != int(code):
        raise AssertionError("end encoder inverse check failed")
    return raw_kw, raw_frame


def _motion_offset(parsed: dict[str, Any], index: int) -> int:
    if not 0 <= int(index) < int(parsed["motion_count"]):
        raise IndexError(f"motion index out of range: {index}")
    return inxcore.OFF_MOTIONINFO + int(index) * int(parsed["layout"]["motion_size"])


def _put_u32(buf: bytearray, off: int, value: int) -> None:
    if not 0 <= int(value) <= 0xFFFFFFFF:
        raise ValueError(f"u32 out of range: {value}")
    struct.pack_into("<I", buf, off, int(value))


def _put_i32(buf: bytearray, off: int, value: int) -> None:
    if not -(2**31) <= int(value) <= 2**31 - 1:
        raise ValueError(f"i32 out of range: {value}")
    struct.pack_into("<i", buf, off, int(value))


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    if len(before) != len(after):
        raise ValueError("INX writer must preserve file size")
    return [i for i, (a, b) in enumerate(zip(before, after)) if a != b]


def _ranges_to_offsets(ranges: list[tuple[int, int]]) -> set[int]:
    out: set[int] = set()
    for start, length in ranges:
        out.update(range(int(start), int(start) + int(length)))
    return out


def _resolve_motion(parsed: dict[str, Any], selector: str | int) -> dict[str, Any]:
    motions = list(parsed["motions"])
    if isinstance(selector, int) or str(selector).strip().isdigit():
        idx = int(selector)
        hits = [m for m in motions if int(m["index"]) == idx]
        if not hits:
            raise KeyError(f"motion index not found: {idx}")
        return hits[0]
    q = str(selector).strip().upper()
    hits = [m for m in motions if str(m.get("state_name", "")).upper() == q]
    if not hits:
        raise KeyError(f"motion state not found: {selector}")
    if len(hits) != 1:
        raise RuntimeError(f"motion state is ambiguous; use index: {selector} matches {[m['index'] for m in hits]}")
    return hits[0]


def rebuild_semantic_bytes(path: pathlib.Path) -> tuple[bytes, dict[str, Any]]:
    """Validate a preservation-aware no-op MotionInfo roundtrip.

    Plain scalar fields are written back at their proven offsets. Encoded
    start/end pairs are *decoded/verified but preserved byte-for-byte* because
    the real corpus contains valid non-canonical encodings (notably for zero
    frame values). Unknown/reserved bytes are never normalized. A byte-identical
    result is the required evidence for a no-op roundtrip.
    """
    path = pathlib.Path(path)
    before = path.read_bytes()
    parsed = inxcore.parse_inx(path)
    buf = bytearray(before)
    encoded_records = 0
    noncanonical_start = 0
    noncanonical_end = 0
    semantic_variant_records = 0
    for motion in parsed["motions"]:
        off = _motion_offset(parsed, int(motion["index"]))
        _put_u32(buf, off, int(motion["state"]))
        if motion["encoding"] == "KEYWORD_ENCODED":
            # Prove that the semantic values are encodable, but do not replace
            # a valid source representation with our canonical inverse form.
            # Some shipped INX records encode the same semantic frame through
            # a different raw pair. Normalizing those bytes would violate the
            # writer's preservation contract even though parsing is unchanged.
            skw, sraw = encode_start(int(motion["start"]), int(parsed["file_code"]))
            ekw, eraw = encode_end(int(motion["end"]), int(parsed["file_code"]))
            source_start = (inxcore.u32(before, off + 4), inxcore.u32(before, off + 8))
            source_end = (inxcore.u32(before, off + 12), inxcore.u32(before, off + 16))
            start_variant = source_start != (skw, sraw)
            end_variant = source_end != (ekw, eraw)
            noncanonical_start += int(start_variant)
            noncanonical_end += int(end_variant)
            semantic_variant_records += int(start_variant or end_variant)
            encoded_records += 1
        else:
            # Plain records keep keyword DWORDs untouched. Only rewrite the
            # parsed direct frame DWORDs to prove their stable offsets.
            _put_u32(buf, off + 8, int(motion["start"]))
            _put_u32(buf, off + 16, int(motion["end"]))
        _put_u32(buf, off + int(parsed["layout"]["repeat"]), int(motion["repeat"]))
        key = int(motion["key_code"])
        if not 0 <= key <= 0xFF:
            raise ValueError(f"key_code out of range in source motion {motion['index']}: {key}")
        buf[off + int(parsed["layout"]["key_code"])] = key
        _put_i32(buf, off + int(parsed["layout"]["motion_frame"]), int(motion["motion_frame"]))
    return bytes(buf), {
        "format": ROUNDTRIP_FORMAT,
        "source": str(path),
        "layout": parsed["layout"]["name"],
        "motion_count": int(parsed["motion_count"]),
        "encoded_records_verified_and_preserved": encoded_records,
        "noncanonical_start_encoding_count": noncanonical_start,
        "noncanonical_end_encoding_count": noncanonical_end,
        "semantic_variant_record_count": semantic_variant_records,
        "source_sha256": _sha256_bytes(before),
        "rebuilt_sha256": _sha256_bytes(bytes(buf)),
        "byte_identical": before == bytes(buf),
        "changed_byte_count": len(_changed_offsets(before, bytes(buf))),
        "client_modified": False,
    }


def validate_noop_roundtrip(path: pathlib.Path) -> dict[str, Any]:
    _rebuilt, report = rebuild_semantic_bytes(path)
    report["status"] = "PASS" if report["byte_identical"] else "FAIL"
    return report


def patch_motion(
    source: pathlib.Path,
    output: pathlib.Path,
    *,
    motion: str | int,
    start: int | None = None,
    end: int | None = None,
    repeat: int | None = None,
    key_code: int | None = None,
    motion_frame: int | None = None,
) -> dict[str, Any]:
    """Write a single MotionInfo edit to a new INX under a caller-owned output.

    This is deliberately a candidate writer: it never changes file size, never
    rewrites unknown bytes, and verifies the output by reparsing it before the
    atomic rename.
    """
    source = pathlib.Path(source).resolve()
    output = pathlib.Path(output).resolve()
    before = source.read_bytes()
    parsed = inxcore.parse_inx(source)
    selected = _resolve_motion(parsed, motion)
    idx = int(selected["index"])
    off = _motion_offset(parsed, idx)
    buf = bytearray(before)
    allowed_ranges: list[tuple[int, int]] = []
    requested: dict[str, int] = {}
    ignored_semantic_noops: list[str] = []

    new_start = int(selected["start"] if start is None else start)
    new_end = int(selected["end"] if end is None else end)
    if new_start < 0 or new_end < 0 or new_start > 0xFFFFFFFF or new_end > 0xFFFFFFFF:
        raise ValueError("start/end must fit uint32")
    if new_end < new_start:
        raise ValueError(f"motion end must be >= start: {new_start}>{new_end}")

    start_changed = start is not None and new_start != int(selected["start"])
    end_changed = end is not None and new_end != int(selected["end"])
    if start is not None and not start_changed:
        ignored_semantic_noops.append("start")
    if end is not None and not end_changed:
        ignored_semantic_noops.append("end")

    if start_changed or end_changed:
        if selected["encoding"] == "KEYWORD_ENCODED":
            if start_changed:
                skw, sraw = encode_start(new_start, int(parsed["file_code"]))
                _put_u32(buf, off + 4, skw); _put_u32(buf, off + 8, sraw)
                allowed_ranges += [(off + 4, 8)]
            if end_changed:
                ekw, eraw = encode_end(new_end, int(parsed["file_code"]))
                _put_u32(buf, off + 12, ekw); _put_u32(buf, off + 16, eraw)
                allowed_ranges += [(off + 12, 8)]
        else:
            if start_changed:
                _put_u32(buf, off + 8, new_start)
                allowed_ranges.append((off + 8, 4))
            if end_changed:
                _put_u32(buf, off + 16, new_end)
                allowed_ranges.append((off + 16, 4))
        if start_changed:
            requested["start"] = new_start
        if end_changed:
            requested["end"] = new_end

    if repeat is not None:
        if not 0 <= int(repeat) <= 0xFFFFFFFF:
            raise ValueError("repeat must fit uint32")
        if int(repeat) == int(selected["repeat"]):
            ignored_semantic_noops.append("repeat")
        else:
            roff = off + int(parsed["layout"]["repeat"])
            _put_u32(buf, roff, int(repeat)); allowed_ranges.append((roff, 4)); requested["repeat"] = int(repeat)
    if key_code is not None:
        if not 0 <= int(key_code) <= 0xFF:
            raise ValueError("key-code must fit uint8")
        if int(key_code) == int(selected["key_code"]):
            ignored_semantic_noops.append("key_code")
        else:
            koff = off + int(parsed["layout"]["key_code"])
            buf[koff] = int(key_code); allowed_ranges.append((koff, 1)); requested["key_code"] = int(key_code)
    if motion_frame is not None:
        if int(motion_frame) == int(selected["motion_frame"]):
            ignored_semantic_noops.append("motion_frame")
        else:
            moff = off + int(parsed["layout"]["motion_frame"])
            _put_i32(buf, moff, int(motion_frame)); allowed_ranges.append((moff, 4)); requested["motion_frame"] = int(motion_frame)

    if not requested:
        if ignored_semantic_noops:
            raise ValueError(
                "requested edit is a semantic no-op; source representation preserved: "
                + ",".join(ignored_semantic_noops)
            )
        raise ValueError("no MotionInfo edit requested")

    after = bytes(buf)
    changed = _changed_offsets(before, after)
    allowed = _ranges_to_offsets(allowed_ranges)
    outside = [i for i in changed if i not in allowed]
    if outside:
        raise AssertionError(f"writer changed bytes outside allowlist: {outside[:32]}")
    if not changed:
        raise ValueError("requested edit is a no-op; use validate inx-roundtrip for byte-exact proof")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    os.close(fd)
    tmp = pathlib.Path(tmp_name)
    try:
        tmp.write_bytes(after)
        reparsed = inxcore.parse_inx(tmp)
        rewritten = next(m for m in reparsed["motions"] if int(m["index"]) == idx)
        for field, expected in requested.items():
            if int(rewritten[field]) != int(expected):
                raise AssertionError(f"reparse mismatch {field}: {rewritten[field]} != {expected}")
        if len(tmp.read_bytes()) != len(before):
            raise AssertionError("writer changed file size")
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)

    return {
        "format": FORMAT,
        "status": "PASS",
        "authorization": "CANDIDATE_PT_BUILD_ONLY",
        "source": str(source),
        "output": str(output),
        "layout": parsed["layout"]["name"],
        "motion_index": idx,
        "motion_state": selected["state_name"],
        "encoding": selected["encoding"],
        "requested": requested,
        "semantic_noop_fields_ignored": ignored_semantic_noops,
        "source_sha256": _sha256_bytes(before),
        "output_sha256": _sha256_bytes(after),
        "file_size_preserved": len(before) == len(after),
        "changed_byte_count": len(changed),
        "changed_offsets": changed,
        "allowed_offsets_only": not outside,
        "client_modified": False,
        "production_authorized": False,
    }
