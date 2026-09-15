from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
import struct
import tempfile
import zipfile
from typing import Any

from .utils import low_path, norm_path

FORMAT = "PT_RARE_OUTLIERS_FAMILY_PROOF_V3"
MODEL062 = b"SMD Model data Ver 0.62"
SMD_HEADER_SIZE = 556
SMD_OBJINFO_SIZE = 40
SMD_OBJECT_SIZE = 2236

# Canonical D_NEW_REVERSE_ENGINEERING list from the project's v12.1/v12.2
# physical survey. Keep this explicit: the point of this gate is to prove or
# refine these known exceptions, not silently absorb arbitrary new failures.
KNOWN_OUTLIERS = [
    "char/tmABCD/ar0nass.smd",
    "char/tmABCD/at_dragon.smd",
    "char/tmABCD/CartolaFS.smd",
    "char/tmABCD/CartolaMG.smd",
    "char/tmABCD/CartolaPS.smd",
    "char/tmABCD/CartolaSH.smd",
    "Effect/AssaEffect/force.bmp",
    "Effect/sky/s.bmp",
    "game/maps/chrselect/ship_bottom.bmp",
    "game/maps/chrselect/ship_crest.bmp",
    "game/maps/chrselect/ship_door.bmp",
    "game/maps/chrselect/ship_floor.bmp",
    "game/maps/chrselect/ship_frame.bmp",
    "game/maps/chrselect/ship_nest.bmp",
    "game/maps/chrselect/ship_nest_part.bmp",
    "game/maps/chrselect/ship_pillar.bmp",
    "game/maps/chrselect/ship_rope.bmp",
    "game/maps/chrselect/ship_sides.bmp",
]

# Historical protected-TGA transform. V0.7.0 keeps the V0.6.9 physical
# family split and adds exact classification for the three remaining files.
TGA_KEY = bytes.fromhex("47380409101924314051647990a9c4e10021")
TGA_FOOTER_SIG = b"TRUEVISION-XFILE.\x00"
TGA_FOOTER_SIZE = 26

# Five physical SMDs are normal Model0.62 bodies with only this 24-byte
# alternate magic.  The rest of each file parses through the already-proven
# Model0.62/TexLink parser after replacing exactly these 24 bytes in a
# temporary diagnostic copy.  Originals are never modified.
MODEL062_ALT_MAGIC = bytes.fromhex("a582ac581598298c859f12c8841f748c8f428fa81b84aa00")
MODEL062_MAGIC24 = MODEL062 + b"\0"

# Ten chrselect ship BMPs share one physically stable second-stage header
# transform after the SourceCode DecryptBMP first-14-byte transform.  This
# 40-byte additive key was recovered from independent BMP structural equations
# across all ten files and is accepted only when every decoded DIB/payload
# invariant closes exactly.  Pixel bytes are never transformed.
SHIP_BMP_DIB40_KEY = bytes.fromhex(
    "7a5b3a07e2cb92674a1beaa7724b02c79a5b1ac7844bf2a77c26ca6724d66207ba5bfa8722cb52e7"
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def _cstr(block: bytes) -> str:
    return block.split(b"\0", 1)[0].decode("latin1", "replace")


def _ascii_runs(data: bytes, *, limit: int = 24) -> list[str]:
    out: list[str] = []
    for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
        s = m.group(0).decode("ascii", "replace")
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _probe_model062(data: bytes) -> dict[str, Any]:
    row: dict[str, Any] = {
        "model062_header": data.startswith(MODEL062),
        "object_count": None,
        "object_names": [],
        "object_name_mismatches": [],
    }
    if not data.startswith(MODEL062) or len(data) < SMD_HEADER_SIZE:
        return row
    try:
        object_count = _i32(data, 24)
    except struct.error:
        row["error"] = "truncated Model0.62 file header"
        return row
    row["object_count"] = object_count
    if object_count < 0 or object_count > 100000:
        row["error"] = f"implausible object_count={object_count}"
        return row
    for oi in range(object_count):
        io = SMD_HEADER_SIZE + oi * SMD_OBJINFO_SIZE
        if io + SMD_OBJINFO_SIZE > len(data):
            row["error"] = f"object info {oi} truncated"
            break
        table_name = _cstr(data[io:io+32])
        start = _i32(data, io + 36)
        head_name = None
        if 0 <= start and start + 204 <= len(data):
            head_name = _cstr(data[start+172:start+204])
        item = {
            "index": oi,
            "table_name": table_name,
            "head_name": head_name,
            "object_start": start,
        }
        row["object_names"].append(item)
        if head_name is not None and table_name != head_name:
            row["object_name_mismatches"].append(item)
    return row


def _probe_bmp(data: bytes) -> dict[str, Any]:
    common_dib = {12, 16, 40, 52, 56, 64, 108, 124}
    out: dict[str, Any] = {
        "starts_BM": data[:2] == b"BM",
        "dib_at_14": None,
        "candidate_inner_BM_offsets": [],
        "candidate_dib_offsets": [],
        "classification": "UNRESOLVED_BINARY_BMP_OUTLIER",
    }
    if len(data) >= 18:
        try:
            dib14 = _u32(data, 14)
            out["dib_at_14"] = dib14
        except struct.error:
            pass
    if out["starts_BM"] and out["dib_at_14"] in common_dib:
        out["classification"] = "STANDARD_BMP"
    elif out["dib_at_14"] in common_dib:
        out["classification"] = "DIB_AFTER_PREFIX14"

    scan = data[:512]
    pos = 0
    while True:
        p = scan.find(b"BM", pos)
        if p < 0:
            break
        out["candidate_inner_BM_offsets"].append(p)
        pos = p + 1
        if len(out["candidate_inner_BM_offsets"]) >= 16:
            break
    for off in range(0, max(0, len(scan) - 4)):
        try:
            v = _u32(scan, off)
        except struct.error:
            break
        if v in common_dib:
            out["candidate_dib_offsets"].append({"offset": off, "dib_size": v})
            if len(out["candidate_dib_offsets"]) >= 24:
                break
    return out



def _sourcecode_decrypt_bmp_header14(data: bytes) -> bytes:
    if len(data) < 14:
        raise ValueError("BMP too small")
    out = bytearray(data[:14])
    if out[:2] != b"BM":
        out[:2] = b"BM"
        for c in range(2, 14):
            out[c] = (out[c] - (c * c)) & 0xFF
    # This is literal supplied SourceCode behavior: bfSize is zeroed after
    # decrypting the proprietary first 14 bytes.
    out[2:6] = b"\0\0\0\0"
    return bytes(out)


def _probe_ship_bmp_family(data: bytes) -> dict[str, Any] | None:
    if len(data) < 56:
        return None
    out = bytearray(data)
    out[:14] = _sourcecode_decrypt_bmp_header14(data)
    for i, key in enumerate(SHIP_BMP_DIB40_KEY):
        out[14 + i] = (out[14 + i] - key) & 0xFF

    try:
        dib = _u32(out, 14)
        width = _i32(out, 18)
        height = _i32(out, 22)
        planes = _u16(out, 26)
        bpp = _u16(out, 28)
        compression = _u32(out, 30)
        image_size = _u32(out, 34)
        offbits = _u32(out, 10)
    except struct.error:
        return None

    if not (
        dib == 40
        and width > 0 and height > 0
        and planes == 1
        and bpp == 24
        and compression == 0
        and offbits == 54
    ):
        return None
    expected_pixels = width * height * 3
    if image_size != expected_pixels:
        return None
    # Physical family invariant: pixel data is raw and begins at the decoded
    # bfOffBits=54.  Every shipped member carries exactly two zero bytes after
    # the declared pixel payload.
    pixel_end = offbits + expected_pixels
    if pixel_end + 2 != len(data) or data[pixel_end:] != b"\0\0":
        return None

    # Produce a standard-equivalent diagnostic header.  This fixes only the
    # non-semantic bfSize field for general image libraries; pixels + trailing
    # physical bytes stay exact.
    struct.pack_into("<I", out, 2, len(out))
    return {
        "classification": "BMP_SHIP_DIB40_PROTECTED_EXACT",
        "decoded_width": width,
        "decoded_height": height,
        "decoded_bpp": bpp,
        "decoded_image_size": image_size,
        "decoded_bfOffBits": offbits,
        "physical_trailing_zero_bytes": 2,
        "pixel_payload_byte_identical": bytes(out[54:pixel_end]) == data[54:pixel_end],
        "standard_equivalent_header54_hex": bytes(out[:54]).hex(),
    }


def _probe_special_model062_body(data: bytes) -> dict[str, Any] | None:
    if len(data) < SMD_HEADER_SIZE or data[:24] != MODEL062_ALT_MAGIC:
        return None
    normalized = bytearray(data)
    normalized[:24] = MODEL062_MAGIC24

    # First perform independent physical layout checks before invoking the
    # existing semantic parser in the audit caller.
    obj_count = _i32(normalized, 24)
    mat_count = _i32(normalized, 28)
    mat_point = _i32(normalized, 32)
    first_obj_point = _i32(normalized, 36)
    if not (0 <= obj_count <= 4096 and 0 <= mat_count <= 65535):
        return None
    if mat_point != SMD_HEADER_SIZE + obj_count * SMD_OBJINFO_SIZE:
        return None
    if not (mat_point <= first_obj_point <= len(normalized)):
        return None
    infos = []
    for oi in range(obj_count):
        off = SMD_HEADER_SIZE + oi * SMD_OBJINFO_SIZE
        if off + SMD_OBJINFO_SIZE > len(normalized):
            return None
        name = _cstr(normalized[off:off+32])
        length = _i32(normalized, off + 32)
        start = _i32(normalized, off + 36)
        if length <= 0 or start < first_obj_point or start + length > len(normalized):
            return None
        infos.append({"index": oi, "name": name, "length": length, "object_start": start})
    return {
        "classification": "MODEL062_ALT_MAGIC_BODY_EXACT_CANDIDATE",
        "object_count": obj_count,
        "material_count": mat_count,
        "material_file_point": mat_point,
        "first_object_point": first_obj_point,
        "object_infos": infos,
        "normalized_bytes": bytes(normalized),
    }


def _probe_archivotmp_recovery(data: bytes) -> dict[str, Any] | None:
    if len(data) < 44:
        return None
    raw = data[:18]
    direct = _tga_fields(raw)
    layout = _tga_footer_layout(data)
    if not (
        raw[:12] == b"\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        and direct["pixel_depth"] == 32
        and direct["descriptor"] == 0
        and layout["footer_tga20"]
        and int(layout.get("extension_offset") or 0) == 0
        and int(layout.get("developer_offset") or 0) == 0
    ):
        return None

    dec = bytearray(_tga_decode_header(raw, "DIMENSIONS_12_15"))
    f = _tga_fields(dec)
    width = f["width"]
    if width <= 0:
        return None
    payload_start = 18
    payload_end = int(layout["footer_offset"])
    payload = payload_end - payload_start
    bytespp = 4
    den = width * bytespp
    if payload <= 0 or payload % den:
        return None
    recovered_height = payload // den
    if recovered_height <= 0 or recovered_height > 8192:
        return None

    # Re-encode the payload-derived dimensions through the proven dimensions-
    # only transform.  ArchivoTmp differs by exactly one physical bit: bit 7 of
    # byte 14.  This is a constrained corruption recovery, not a generic guess.
    plain_dims = struct.pack("<HH", width, recovered_height)
    encoded_dims = bytes((plain_dims[i] + ((12 + i) * (12 + i))) & 0xFF for i in range(4))
    diff = bytes(a ^ b for a, b in zip(raw[12:16], encoded_dims))
    if diff != b"\x00\x00\x80\x00":
        return None
    struct.pack_into("<H", dec, 14, recovered_height)
    rf = _tga_fields(bytes(dec))
    if _tga_expected_uncompressed_bytes(rf) != payload:
        return None
    return {
        "classification": "TGA_DIMENSIONS_SINGLE_BIT_CORRUPT_RECOVERABLE_PREVIEW_ONLY",
        "recovered_width": width,
        "recovered_height": recovered_height,
        "pixel_depth": 32,
        "payload_bytes": payload,
        "physical_dimension_xor_vs_reencoded": diff.hex(),
        "corrupt_byte_offset": 14,
        "corrupt_bit_mask": "0x80",
        "recovered_header_hex": bytes(dec).hex(),
        "footer_layout": layout,
        "runtime_validity": "NOT_PROVEN_OLD_CLIENT_WOULD_DECODE_HEIGHT_192",
    }

def _tga_fields(h: bytes) -> dict[str, int]:
    if len(h) != 18:
        raise ValueError("TGA header must be 18 bytes")
    return {
        "id_length": h[0],
        "color_map_type": h[1],
        "image_type": h[2],
        "color_map_first": _u16(h, 3),
        "color_map_length": _u16(h, 5),
        "color_map_depth": h[7],
        "x_origin": _u16(h, 8),
        "y_origin": _u16(h, 10),
        "width": _u16(h, 12),
        "height": _u16(h, 14),
        "pixel_depth": h[16],
        "descriptor": h[17],
    }


def _tga_plausible(f: dict[str, int]) -> bool:
    # Exact historical protected-TGA gate: the protected corpus proved here is
    # true-color type 2/10, 24/32bpp, no color map.
    return (
        f["color_map_type"] == 0
        and f["image_type"] in (2, 10)
        and 0 < f["width"] <= 8192
        and 0 < f["height"] <= 8192
        and f["pixel_depth"] in (24, 32)
    )


def _tga_has_footer(data: bytes) -> bool:
    return len(data) >= TGA_FOOTER_SIZE and data[-18:] == TGA_FOOTER_SIG


def _tga_footer_layout(data: bytes) -> dict[str, Any]:
    """Parse only the fixed TGA 2.0 footer/extension placement needed by the gate."""
    out: dict[str, Any] = {
        "footer_tga20": _tga_has_footer(data),
        "footer_offset": None,
        "extension_offset": 0,
        "developer_offset": 0,
        "extension_size": None,
    }
    if not out["footer_tga20"]:
        return out
    footer_off = len(data) - TGA_FOOTER_SIZE
    out["footer_offset"] = footer_off
    out["extension_offset"] = _u32(data, footer_off)
    out["developer_offset"] = _u32(data, footer_off + 4)
    ext = out["extension_offset"]
    if ext and 0 <= ext <= footer_off - 2:
        out["extension_size"] = _u16(data, ext)
    return out


def _tga_decode_header(raw: bytes, mode: str) -> bytes:
    out = bytearray(18)
    if mode == "FULL18":
        for i in range(18):
            out[i] = (raw[i] - TGA_KEY[i]) & 0xFF
    elif mode == "KEEP_00_16":
        out[:2] = raw[:2]
        for i in range(2, 18):
            out[i] = (raw[i] - TGA_KEY[i]) & 0xFF
    elif mode == "DIMENSIONS_12_15":
        out[:] = raw
        for i in range(12, 16):
            out[i] = (raw[i] - TGA_KEY[i]) & 0xFF
    else:
        raise ValueError(mode)
    return bytes(out)


def _tga_expected_uncompressed_bytes(f: dict[str, int]) -> int | None:
    if f["image_type"] != 2:
        return None
    return f["width"] * f["height"] * (f["pixel_depth"] // 8)


def _tga_payload_boundary(data: bytes, payload_start: int) -> tuple[int, dict[str, Any]]:
    layout = _tga_footer_layout(data)
    if not layout["footer_tga20"]:
        return len(data), layout
    footer_off = int(layout["footer_offset"])
    boundaries = [footer_off]
    for key in ("extension_offset", "developer_offset"):
        off = int(layout[key] or 0)
        if payload_start <= off < footer_off:
            boundaries.append(off)
    return min(boundaries), layout


def _classify_protected_candidate(
    data: bytes,
    *,
    mode: str,
    decoded_header: bytes,
    fields: dict[str, int],
) -> dict[str, Any] | None:
    payload_start = 18 + fields["id_length"]
    if payload_start > len(data):
        return None
    expected = _tga_expected_uncompressed_bytes(fields)
    payload_end, layout = _tga_payload_boundary(data, payload_start)
    actual = payload_end - payload_start

    # Existing proven protected RLE family remains footer-backed. V0.6.9 does
    # not broaden variable-length payload acceptance without physical evidence.
    if fields["image_type"] == 10:
        if not layout["footer_tga20"] or actual < 0:
            return None
        return {
            "classification": f"TGA_PROTECTED_{mode}",
            "protection_mode": mode,
            "decoded_header_hex": decoded_header.hex(),
            "decoded_fields": fields,
            "payload_bytes": actual,
            "expected_uncompressed_payload_bytes": None,
            "container_variant": "TGA20_FOOTER",
            "footer_layout": layout,
        }

    if expected is None or actual != expected:
        return None

    if not layout["footer_tga20"]:
        # Physical corpus evidence: 98 type-2 protected TGAs are exact old-TGA
        # payloads with no TRUEVISION-XFILE footer. Exact size is mandatory.
        return {
            "classification": f"TGA_PROTECTED_{mode}_NO_FOOTER",
            "protection_mode": mode,
            "decoded_header_hex": decoded_header.hex(),
            "decoded_fields": fields,
            "payload_bytes": actual,
            "expected_uncompressed_payload_bytes": expected,
            "container_variant": "TGA1_STYLE_NO_FOOTER_EXACT_PAYLOAD",
            "footer_layout": layout,
        }

    ext = int(layout["extension_offset"] or 0)
    dev = int(layout["developer_offset"] or 0)
    footer_off = int(layout["footer_offset"])
    if ext:
        # TGA 2.0 defines a 495-byte Extension Area. The nine physical files
        # that V0.6.8 called payload mismatches have exactly this layout.
        ext_size = layout["extension_size"]
        if ext != payload_start + expected or ext_size != 495:
            return None
        ext_end = ext + 495
        if dev:
            if not (ext_end <= dev <= footer_off):
                return None
        elif ext_end != footer_off:
            return None
        suffix = "_TGA20_EXTENSION495"
        container = "TGA20_EXTENSION_AREA_495"
    else:
        if dev and dev != payload_start + expected:
            return None
        suffix = ""
        container = "TGA20_FOOTER"

    return {
        "classification": f"TGA_PROTECTED_{mode}{suffix}",
        "protection_mode": mode,
        "decoded_header_hex": decoded_header.hex(),
        "decoded_fields": fields,
        "payload_bytes": actual,
        "expected_uncompressed_payload_bytes": expected,
        "container_variant": container,
        "footer_layout": layout,
    }


def _probe_tga(data: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {
        "classification": "TGA_ANOMALY_UNRESOLVED",
        "size": len(data),
        "first18_hex": data[:18].hex(),
        "footer_tga20": _tga_has_footer(data),
        "candidate_decodes": [],
        "ascii_prefix": _ascii_runs(data[:512], limit=8),
    }
    if len(data) < 18:
        out["reason"] = "file_too_small_for_tga_header"
        return out
    if not any(data):
        out["classification"] = "TGA_ZERO_FILLED_NON_IMAGE_PLACEHOLDER"
        out["reason"] = "entire_file_zero_filled"
        return out
    raw = data[:18]
    # One shipped .tga is actually an IIS/HTML error document whose first 18
    # bytes passed through the FULL18 additive transform.  Decode only those
    # bytes and classify the content by its explicit text signature.
    full18_prefix = _tga_decode_header(raw, "FULL18") + data[18:256]
    if full18_prefix.startswith(b"\x00\x00DOCTYPE HTML") or b"<HTML><HEAD><TITLE>The page cannot be found</TITLE>" in full18_prefix:
        out["classification"] = "NON_IMAGE_HTML_MISLABELED_TGA"
        out["reason"] = "decoded_prefix_is_html_error_document"
        out["decoded_ascii_prefix"] = _ascii_runs(full18_prefix, limit=8)
        return out
    direct = _tga_fields(raw)
    out["direct_fields"] = direct
    if _tga_plausible(direct):
        out["classification"] = "TGA_STANDARD_TRUECOLOR"
        return out

    valid: list[tuple[str, bytes, dict[str, int]]] = []
    for mode in ("FULL18", "KEEP_00_16"):
        dec = _tga_decode_header(raw, mode)
        f = _tga_fields(dec)
        c = {"mode": mode, "decoded_header_hex": dec.hex(), "fields": f, "plausible": _tga_plausible(f)}
        out["candidate_decodes"].append(c)
        if _tga_plausible(f):
            valid.append((mode, dec, f))

    if len(valid) == 1:
        mode, dec, f = valid[0]
        accepted = _classify_protected_candidate(data, mode=mode, decoded_header=dec, fields=f)
        if accepted is not None:
            out.update(accepted)
            return out
        out["reason"] = "protected_candidate_layout_not_physically_proven"
        out["protected_candidate_mode"] = mode
        expected = _tga_expected_uncompressed_bytes(f)
        if expected is not None:
            payload_start = 18 + f["id_length"]
            payload_end, layout = _tga_payload_boundary(data, payload_start)
            out["actual_payload_bytes"] = payload_end - payload_start
            out["expected_payload_bytes"] = expected
            out["footer_layout"] = layout
        return out

    # Third physical family discovered by the V0.6.8 full-client census:
    # header bytes 0..11 and 16..17 are already standard, while only width and
    # height bytes 12..15 use the historical additive transform. Accept only
    # when the reconstructed header is plausible AND the physical payload
    # layout closes exactly. No dimensional guess is allowed.
    dec_dim = _tga_decode_header(raw, "DIMENSIONS_12_15")
    f_dim = _tga_fields(dec_dim)
    dim_shape = (
        raw[:12] == b"\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        and raw[16] in (24, 32)
        and _tga_plausible(f_dim)
    )
    cdim = {
        "mode": "DIMENSIONS_12_15",
        "decoded_header_hex": dec_dim.hex(),
        "fields": f_dim,
        "plausible": bool(dim_shape),
    }
    out["candidate_decodes"].append(cdim)
    if dim_shape:
        accepted = _classify_protected_candidate(
            data, mode="DIMENSIONS_12_15", decoded_header=dec_dim, fields=f_dim
        )
        if accepted is not None:
            out.update(accepted)
            return out
        recovered = _probe_archivotmp_recovery(data)
        if recovered is not None:
            out.update(recovered)
            return out
        out["reason"] = "dimension_only_candidate_layout_not_exact"
        out["protected_candidate_mode"] = "DIMENSIONS_12_15"
        expected = _tga_expected_uncompressed_bytes(f_dim)
        if expected is not None:
            payload_start = 18 + f_dim["id_length"]
            payload_end, layout = _tga_payload_boundary(data, payload_start)
            out["actual_payload_bytes"] = payload_end - payload_start
            out["expected_payload_bytes"] = expected
            out["footer_layout"] = layout
        return out

    out["reason"] = "protected_header_unresolved_or_ambiguous"
    return out

def _canonical_record_map(records: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in records:
        rel = norm_path(r.get("relative_path") or "")
        if rel:
            out[low_path(rel)] = r
    return out


def _probe_outlier(logical: str, path: pathlib.Path, record: dict | None) -> dict[str, Any]:
    data = path.read_bytes()
    ext = path.suffix.lower()
    row: dict[str, Any] = {
        "logical": logical,
        "physical": str(path),
        "canonical_record_present": record is not None,
        "record_kind": (record or {}).get("kind"),
        "compatibility_tier": (record or {}).get("compatibility_tier"),
        "size": len(data),
        "sha256": _sha(data),
        "first64_hex": data[:64].hex(),
        "last64_hex": data[-64:].hex(),
        "ascii_runs_first4k": _ascii_runs(data[:4096]),
    }
    if ext == ".smd":
        row["smd_probe"] = _probe_model062(data)
        if data.startswith(MODEL062):
            # at_dragon: normal Model0.62 body with one preserved historical
            # disagreement between object-table name and object-head name.
            from .multilayer_texlink import parse_multilayer_semantics
            sem = parse_multilayer_semantics(path)
            mismatches = (row["smd_probe"] or {}).get("object_name_mismatches") or []
            row["model062_semantic_probe"] = {
                "object_count": sem.get("object_count"),
                "material_count": sem.get("material_count"),
                "total_faces": sem.get("total_faces"),
                "max_layers": sem.get("max_layers"),
                "htexture_mapping_errors": len(sem.get("htexture_mapping_errors") or []),
                "stage_index_errors": len(sem.get("stage_index_errors") or []),
            }
            row["physical_family_candidate"] = (
                "MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT"
                if mismatches
                and not sem.get("htexture_mapping_errors")
                and not sem.get("stage_index_errors")
                else "MODEL062_STANDARD_OR_OTHER"
            )
        else:
            alt = _probe_special_model062_body(data)
            if alt is None:
                row["physical_family_candidate"] = "SPECIAL_SMD_UNKNOWN_HEADER"
            else:
                normalized = alt.pop("normalized_bytes")
                row["alternate_magic_probe"] = alt
                # Run the already-certified strict Model0.62 semantic parser on
                # a temporary diagnostic normalization.  Only bytes 0..23 are
                # changed, never the source asset.
                from .multilayer_texlink import parse_multilayer_semantics
                with tempfile.NamedTemporaryFile(suffix=".smd", delete=False) as tf:
                    tf.write(normalized)
                    tpath = pathlib.Path(tf.name)
                try:
                    sem = parse_multilayer_semantics(tpath)
                finally:
                    try:
                        tpath.unlink()
                    except OSError:
                        pass
                sem_probe = {
                    "object_count": sem.get("object_count"),
                    "material_count": sem.get("material_count"),
                    "total_faces": sem.get("total_faces"),
                    "max_layers": sem.get("max_layers"),
                    "htexture_mapping_errors": len(sem.get("htexture_mapping_errors") or []),
                    "stage_index_errors": len(sem.get("stage_index_errors") or []),
                    "normalization_changed_prefix_bytes_only": True,
                }
                row["model062_semantic_probe"] = sem_probe
                exact = (
                    sem_probe["object_count"] == alt["object_count"]
                    and sem_probe["material_count"] == alt["material_count"]
                    and sem_probe["htexture_mapping_errors"] == 0
                    and sem_probe["stage_index_errors"] == 0
                )
                row["physical_family_candidate"] = (
                    "MODEL062_ALT_MAGIC_BODY_EXACT" if exact else "SPECIAL_SMD_UNKNOWN_HEADER"
                )
    elif ext == ".bmp":
        row["bmp_probe"] = _probe_bmp(data)
        if data and not any(data):
            row["physical_family_candidate"] = "BMP_ZERO_FILLED_NON_IMAGE_PLACEHOLDER"
            row["bmp_probe"]["reason"] = "entire_file_zero_filled"
        elif data.startswith(b'"Server1"') and b'"Server2"' in data[:256]:
            row["physical_family_candidate"] = "BMP_TEXT_CONFIG_MISLABELED"
            row["bmp_probe"]["reason"] = "ascii_server_configuration_not_bitmap"
        else:
            ship = _probe_ship_bmp_family(data)
            if ship is not None:
                row["bmp_probe"].update(ship)
                row["physical_family_candidate"] = ship["classification"]
            else:
                row["physical_family_candidate"] = row["bmp_probe"]["classification"]
    else:
        row["physical_family_candidate"] = "UNEXPECTED_EXTENSION"
    return row


def audit_rare_outliers_and_tga(records: list[dict], resolver, *, bundle: str | pathlib.Path | None = None, progress: bool = False) -> dict[str, Any]:
    record_map = _canonical_record_map(records)
    outlier_rows: list[dict[str, Any]] = []
    missing_outliers: list[str] = []
    scan_errors: list[dict[str, str]] = []

    for logical in KNOWN_OUTLIERS:
        try:
            p = resolver.resolve(logical, required=True)
            outlier_rows.append(_probe_outlier(logical, p, record_map.get(low_path(logical))))
        except Exception as e:
            missing_outliers.append(logical)
            scan_errors.append({"scope": "OUTLIER", "logical": logical, "error": f"{type(e).__name__}: {e}"})

    # The five alternate-magic SMDs are now proved as ordinary Model0.62
    # bodies after a 24-byte diagnostic normalization.
    special_smds = [r for r in outlier_rows if r.get("physical_family_candidate") == "MODEL062_ALT_MAGIC_BODY_EXACT"]
    special_prefix_counts = collections.Counter(r["first64_hex"][:48] for r in special_smds)

    model062_name_mismatch_rows = []
    for r in outlier_rows:
        if r.get("physical_family_candidate") != "MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT":
            continue
        mis = (r.get("smd_probe") or {}).get("object_name_mismatches") or []
        model062_name_mismatch_rows.append({"logical": r["logical"], "mismatches": mis})

    bmp_family_counts = collections.Counter(
        r.get("physical_family_candidate")
        for r in outlier_rows if pathlib.PurePosixPath(r["logical"]).suffix.lower() == ".bmp"
    )

    tga_rows: list[dict[str, Any]] = []
    tga_counts: collections.Counter[str] = collections.Counter()
    tga_anomalies: list[dict[str, Any]] = []
    tga_support_issues: list[dict[str, Any]] = []
    # Use the canonical physical inventory instead of recursively walking the
    # entire client tree.  The registry was produced from the same client and
    # gives a deterministic complete TGA path set without an unbounded rglob.
    tga_logicals = sorted({
        norm_path(r.get("relative_path") or "")
        for r in records
        if norm_path(r.get("relative_path") or "").lower().endswith(".tga")
    }, key=str.casefold)
    total_tga = len(tga_logicals)
    if progress:
        print(f"[release-1-auto] TGA_CENSUS begin files={total_tga}", flush=True)
    for index, rel in enumerate(tga_logicals, 1):
        try:
            p = pathlib.Path(resolver.resolve(rel, required=True)).resolve()
            if progress and (index == 1 or index % 100 == 0 or index == total_tga):
                print(f"[release-1-auto] TGA_CENSUS {index}/{total_tga} {rel}", flush=True)
            data = p.read_bytes()
            pr = _probe_tga(data)
            cls = pr["classification"]
            tga_counts[cls] += 1
            row = {
                "logical": rel,
                "physical": str(p),
                "size": len(data),
                "sha256": _sha(data),
                **pr,
            }
            tga_rows.append(row)
            if cls == "TGA_ANOMALY_UNRESOLVED":
                tga_anomalies.append(row)
            if cls in {
                "TGA_ZERO_FILLED_NON_IMAGE_PLACEHOLDER",
                "NON_IMAGE_HTML_MISLABELED_TGA",
                "TGA_DIMENSIONS_SINGLE_BIT_CORRUPT_RECOVERABLE_PREVIEW_ONLY",
            }:
                tga_support_issues.append(row)
        except Exception as e:
            scan_errors.append({"scope": "TGA", "logical": rel, "error": f"{type(e).__name__}: {e}"})

    # V0.6.8 proved that the old "exactly two anomalies" premise was false:
    # footer/container variants had been mixed with codec failures. Census
    # completion now means every known outlier was recovered and every TGA was
    # physically scanned without I/O/parser errors. Unresolved TGAs remain an
    # explicit fail-closed support set and are bundled for family research.
    status = "PASS"
    if len(outlier_rows) != len(KNOWN_OUTLIERS) or missing_outliers or scan_errors:
        status = "FAIL"

    outlier_unresolved = [
        r for r in outlier_rows
        if r.get("physical_family_candidate") in {
            "SPECIAL_SMD_UNKNOWN_HEADER", "UNRESOLVED_BINARY_BMP_OUTLIER",
            "MODEL062_STANDARD_OR_OTHER", "UNEXPECTED_EXTENSION"
        }
    ]
    outlier_family_complete = len(outlier_unresolved) == 0 and len(outlier_rows) == len(KNOWN_OUTLIERS)
    tga_family_complete = len(tga_anomalies) == 0

    result: dict[str, Any] = {
        "format": FORMAT,
        "status": status,
        "known_outliers_expected": len(KNOWN_OUTLIERS),
        "known_outliers_physically_audited": len(outlier_rows),
        "missing_known_outliers": missing_outliers,
        "scan_errors": scan_errors,
        "outlier_extension_counts": dict(collections.Counter(pathlib.PurePosixPath(r["logical"]).suffix.lower() for r in outlier_rows)),
        "outlier_family_candidate_counts": dict(bmp_family_counts | collections.Counter(
            r.get("physical_family_candidate") for r in outlier_rows if pathlib.PurePosixPath(r["logical"]).suffix.lower() == ".smd"
        )),
        "model062_alt_magic_body_exact_files": [r["logical"] for r in special_smds],
        "model062_alt_magic_prefix24_counts": dict(special_prefix_counts),
        "model062_legacy_name_mismatch": model062_name_mismatch_rows,
        "tga_physical_files_scanned": len(tga_rows),
        "tga_classification_counts": dict(tga_counts),
        "tga_anomaly_count": len(tga_anomalies),
        "tga_anomalies": [
            {k: v for k, v in r.items() if k != "physical"}
            for r in tga_anomalies
        ],
        "tga_support_issue_count": len(tga_support_issues),
        "tga_support_issues": [
            {k: v for k, v in r.items() if k != "physical"}
            for r in tga_support_issues
        ],
        "rare_physical_census_complete_candidate": status == "PASS",
        "rare_outlier_family_classification_complete_candidate": outlier_family_complete,
        "unresolved_outlier_family_files": [r["logical"] for r in outlier_unresolved],
        "tga_family_classification_complete_candidate": tga_family_complete,
        "tga_unresolved_support_count": len(tga_anomalies),
        "tga_support_complete_candidate": len(tga_support_issues) == 0 and len(tga_anomalies) == 0,
        "support_complete_candidate": False,
        "policy": {
            "outliers": "family classification is physical and fail-closed; alternate SMD magic is normalized only in a temporary diagnostic copy",
            "bmp_ship_family": "accept only exact DIB40/header/payload equations; pixel bytes remain untouched and originals remain read-only",
            "tga_physical_families": "accept only exact physical header/container layouts; ArchivoTmp recovery is explicitly preview-only and not old-client runtime certification",
            "invalid_assets": "zero-filled placeholders and mislabeled text/HTML remain unsupported rather than guessed",
            "client_modified": False,
        },
        "rows": outlier_rows,
    }

    if bundle:
        bp = pathlib.Path(bundle).expanduser()
        if not bp.is_absolute():
            bp = pathlib.Path.cwd() / bp
        bp = bp.resolve(); bp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            seen: set[str] = set()
            for r in outlier_rows:
                p = pathlib.Path(r["physical"])
                arc = "client/" + norm_path(r["logical"])
                z.write(p, arc)
                seen.add(str(p.resolve()))
            for r in tga_support_issues + tga_anomalies:
                p = pathlib.Path(r["physical"])
                if str(p.resolve()) in seen:
                    continue
                z.write(p, "client/" + norm_path(r["logical"]))
            manifest = dict(result)
            manifest.pop("rows", None)
            z.writestr("diagnostic/RARE_OUTLIERS_TGA_CENSUS.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            z.writestr("diagnostic/KNOWN_OUTLIERS.txt", "\n".join(KNOWN_OUTLIERS) + "\n")
        result["bundle"] = str(bp)

    return result
