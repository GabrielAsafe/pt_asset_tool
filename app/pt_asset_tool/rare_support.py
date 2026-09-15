from __future__ import annotations

import json
import pathlib
import struct
from typing import Any

from .multilayer_texlink import parse_multilayer_semantics
from .rare_outliers import (
    MODEL062,
    MODEL062_ALT_MAGIC,
    MODEL062_MAGIC24,
    SHIP_BMP_DIB40_KEY,
    _probe_model062,
    _probe_ship_bmp_family,
    _probe_special_model062_body,
    _sourcecode_decrypt_bmp_header14,
)
from .utils import norm_path, sha256_file

ALT_MAGIC_SMD_FILES = [
    "char/tmABCD/ar0nass.smd",
    "char/tmABCD/CartolaFS.smd",
    "char/tmABCD/CartolaMG.smd",
    "char/tmABCD/CartolaPS.smd",
    "char/tmABCD/CartolaSH.smd",
]
LEGACY_NAME_MISMATCH_SMD_FILES = ["char/tmABCD/at_dragon.smd"]
SHIP_BMP_FILES = [
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


def prepare_model062_tooling_source(src: pathlib.Path, dst: pathlib.Path) -> dict[str, Any]:
    """Prepare a read-only tooling copy for the two proven rare Model0.62 subfamilies.

    Standard Model0.62 input is copied byte-identically.  The five alternate-magic
    files are normalized by replacing exactly bytes 0..23.  No other byte may
    change.  The physical source is never written.
    """
    data = src.read_bytes()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if data.startswith(MODEL062):
        dst.write_bytes(data)
        probe = _probe_model062(data)
        family = "MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT" if probe.get("object_name_mismatches") else "MODEL062_STANDARD"
        changed = []
    elif data[:24] == MODEL062_ALT_MAGIC:
        alt = _probe_special_model062_body(data)
        if alt is None:
            raise ValueError("alternate Model0.62 magic present but body proof failed")
        normalized = MODEL062_MAGIC24 + data[24:]
        if normalized[24:] != data[24:] or len(normalized) != len(data):
            raise AssertionError("Model0.62 normalization changed bytes outside prefix24")
        dst.write_bytes(normalized)
        family = "MODEL062_ALT_MAGIC_BODY_EXACT"
        changed = list(range(24))
    else:
        raise ValueError("not a proven rare Model0.62 family")

    sem = parse_multilayer_semantics(dst)
    if sem.get("htexture_mapping_errors") or sem.get("stage_index_errors"):
        raise ValueError("normalized Model0.62 semantic proof failed")
    return {
        "source": str(src),
        "prepared": str(dst),
        "family": family,
        "source_sha256": sha256_file(src),
        "prepared_sha256": sha256_file(dst),
        "prefix24_only_normalization": family == "MODEL062_ALT_MAGIC_BODY_EXACT",
        "changed_byte_offsets": changed,
        "object_count": sem.get("object_count"),
        "material_count": sem.get("material_count"),
        "total_faces": sem.get("total_faces"),
        "max_layers": sem.get("max_layers"),
        "htexture_mapping_errors": len(sem.get("htexture_mapping_errors") or []),
        "stage_index_errors": len(sem.get("stage_index_errors") or []),
        "client_modified": False,
    }


def decode_ship_bmp_bytes(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """Return a standard-BMP equivalent for the proven chrselect ship family.

    This is the in-memory counterpart of :func:`decode_ship_bmp_exact`.  It keeps
    the same fail-closed family proof and byte-preservation invariants, allowing
    read-only consumers such as the GUI preview endpoint to reuse the certified
    adapter without creating a temporary file.
    """
    proof = _probe_ship_bmp_family(data)
    if proof is None or proof.get("classification") != "BMP_SHIP_DIB40_PROTECTED_EXACT":
        raise ValueError("not BMP_SHIP_DIB40_PROTECTED_EXACT")

    out = bytearray(data)
    out[:14] = _sourcecode_decrypt_bmp_header14(data)
    for i, key in enumerate(SHIP_BMP_DIB40_KEY):
        out[14 + i] = (out[14 + i] - key) & 0xFF
    struct.pack_into("<I", out, 2, len(out))

    offbits = struct.unpack_from("<I", out, 10)[0]
    image_size = struct.unpack_from("<I", out, 34)[0]
    pixel_end = offbits + image_size
    if bytes(out[offbits:pixel_end]) != data[offbits:pixel_end]:
        raise AssertionError("ship BMP decode changed pixel bytes")
    if bytes(out[pixel_end:]) != data[pixel_end:]:
        raise AssertionError("ship BMP decode changed physical trailing bytes")
    if out[:2] != b"BM" or struct.unpack_from("<I", out, 14)[0] != 40:
        raise AssertionError("ship BMP standard-equivalent header invalid")

    meta = {
        "family": "BMP_SHIP_DIB40_PROTECTED_EXACT",
        "width": int(proof["decoded_width"]),
        "height": int(proof["decoded_height"]),
        "bpp": int(proof["decoded_bpp"]),
        "pixel_bytes": int(proof["decoded_image_size"]),
        "pixel_payload_byte_identical": True,
        "physical_trailing_zero_bytes": int(proof["physical_trailing_zero_bytes"]),
        "client_modified": False,
    }
    return bytes(out), meta


def build_ship_bmp_bytes(baseline: bytes, edited_standard: bytes) -> tuple[bytes, dict[str, Any]]:
    """Rebuild the proven chrselect ship BMP family from a standard edited BMP.

    The proprietary 54-byte header and the two physical trailing bytes are
    preserved exactly; only the raw 24-bpp pixel payload may change.
    """
    proof = _probe_ship_bmp_family(baseline)
    if proof is None or proof.get("classification") != "BMP_SHIP_DIB40_PROTECTED_EXACT":
        raise ValueError("baseline is not BMP_SHIP_DIB40_PROTECTED_EXACT")
    if len(edited_standard) != len(baseline) or edited_standard[:2] != b"BM":
        raise ValueError("edited ship BMP must be the same-size standard BMP equivalent")
    try:
        dib=struct.unpack_from("<I",edited_standard,14)[0]
        width=struct.unpack_from("<i",edited_standard,18)[0]
        height=struct.unpack_from("<i",edited_standard,22)[0]
        planes=struct.unpack_from("<H",edited_standard,26)[0]
        bpp=struct.unpack_from("<H",edited_standard,28)[0]
        compression=struct.unpack_from("<I",edited_standard,30)[0]
        image_size=struct.unpack_from("<I",edited_standard,34)[0]
        offbits=struct.unpack_from("<I",edited_standard,10)[0]
    except struct.error as exc:
        raise ValueError("edited ship BMP header truncated") from exc
    expected={
        "dib":40,"width":int(proof["decoded_width"]),"height":int(proof["decoded_height"]),
        "planes":1,"bpp":int(proof["decoded_bpp"]),"compression":0,
        "image_size":int(proof["decoded_image_size"]),"offbits":54,
    }
    got={"dib":dib,"width":width,"height":height,"planes":planes,"bpp":bpp,"compression":compression,"image_size":image_size,"offbits":offbits}
    if got != expected:
        raise ValueError(f"edited ship BMP structure differs from baseline: expected={expected} got={got}")
    pixel_end=offbits+image_size
    if edited_standard[pixel_end:] != b"\0\0":
        raise ValueError("edited ship BMP must retain the two physical trailing zero bytes")
    out=bytearray(baseline)
    out[offbits:pixel_end]=edited_standard[offbits:pixel_end]
    if bytes(out[:54]) != baseline[:54] or bytes(out[pixel_end:]) != baseline[pixel_end:]:
        raise RuntimeError("ship BMP rebuild changed protected header/trailing bytes")
    rebuilt=bytes(out)
    decoded,_=decode_ship_bmp_bytes(rebuilt)
    # bfSize is normalized by decode_ship_bmp_bytes, so the standard-equivalent
    # result must match the artist file byte-for-byte.
    if decoded != edited_standard:
        raise RuntimeError("ship BMP rebuild/decode did not roundtrip edited standard bytes")
    return rebuilt,{
        "family":"BMP_SHIP_DIB40_PROTECTED_EXACT",
        "width":expected["width"],"height":expected["height"],"bpp":expected["bpp"],
        "pixel_bytes":image_size,"protected_header_byte_identical":True,
        "physical_trailing_bytes_byte_identical":True,"client_modified":False,
    }


def decode_ship_bmp_exact(src: pathlib.Path, dst: pathlib.Path) -> dict[str, Any]:
    """Decode the proven chrselect ship BMP header family to a standard BMP copy.

    Only the 54-byte BMP/DIB header is transformed. Pixel payload and the two
    physical trailing zero bytes remain byte-identical. The source client file is
    never modified.
    """
    data = src.read_bytes()
    out, meta = decode_ship_bmp_bytes(data)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    return {
        "source": str(src),
        "prepared": str(dst),
        **meta,
    }


def audit_rare_support(resolver, *, work: pathlib.Path) -> dict[str, Any]:
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for logical in ALT_MAGIC_SMD_FILES + LEGACY_NAME_MISMATCH_SMD_FILES:
        try:
            src = resolver.resolve(logical, required=True)
            dst = work / "model062" / pathlib.PurePosixPath(logical)
            row = prepare_model062_tooling_source(src, dst)
            row["logical"] = logical
            rows.append(row)
        except Exception as exc:
            errors.append({"logical": logical, "error": f"{type(exc).__name__}: {exc}"})

    for logical in SHIP_BMP_FILES:
        try:
            src = resolver.resolve(logical, required=True)
            dst = work / "textures" / pathlib.PurePosixPath(logical)
            row = decode_ship_bmp_exact(src, dst)
            row["logical"] = logical
            rows.append(row)
        except Exception as exc:
            errors.append({"logical": logical, "error": f"{type(exc).__name__}: {exc}"})

    smd_rows = [r for r in rows if r["logical"].lower().endswith(".smd")]
    bmp_rows = [r for r in rows if r["logical"].lower().endswith(".bmp")]
    expected = len(ALT_MAGIC_SMD_FILES) + len(LEGACY_NAME_MISMATCH_SMD_FILES) + len(SHIP_BMP_FILES)
    status = "PASS" if len(rows) == expected and not errors else "FAIL"
    result = {
        "format": "PT_RARE_USABLE_FAMILY_SUPPORT_V1",
        "status": status,
        "expected_usable_outliers": expected,
        "prepared_usable_outliers": len(rows),
        "model062_prepared": len(smd_rows),
        "model062_alt_magic_prepared": sum(r.get("family") == "MODEL062_ALT_MAGIC_BODY_EXACT" for r in smd_rows),
        "model062_legacy_name_mismatch_prepared": sum(r.get("family") == "MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT" for r in smd_rows),
        "ship_bmp_prepared": len(bmp_rows),
        "errors": errors,
        "usable_family_support_complete_candidate": status == "PASS",
        "invalid_historical_assets_remain_unsupported": [
            "Effect/AssaEffect/force.bmp",
            "Effect/sky/s.bmp",
            "Effect/AssaEffect/MonsterFury/m_fury.tga",
            "Field/Ricarten/ch_tree1.tga",
        ],
        "preview_only_not_runtime_certified": ["Effect/Particle/ArchivoTmp.tga"],
        "client_modified": False,
        "rows": rows,
    }
    (work / "rare_support_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
