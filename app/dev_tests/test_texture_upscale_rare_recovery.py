from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image

from pt_asset_tool import texture_upscale as t
from pt_asset_tool.rare_outliers import SHIP_BMP_DIB40_KEY, TGA_KEY, _probe_tga
from pt_asset_tool.rare_support import decode_ship_bmp_bytes


def _bmp_bytes(size=(8, 8)) -> bytes:
    im = Image.new("RGB", size, (11, 22, 33))
    out = io.BytesIO()
    im.save(out, format="BMP")
    return out.getvalue()


def _protect_ship(std: bytes) -> bytes:
    physical = bytearray(std + b"\0\0")
    struct.pack_into("<I", physical, 2, len(physical))
    out = bytearray(physical)
    out[:2] = b"A8"
    for c in range(2, 14):
        out[c] = (physical[c] + (c * c)) & 0xFF
    for i, key in enumerate(SHIP_BMP_DIB40_KEY):
        out[14 + i] = (physical[14 + i] + key) & 0xFF
    return bytes(out)


def _tga_bytes(size=(8, 8)) -> bytes:
    im = Image.new("RGBA", size, (10, 20, 30, 255))
    out = io.BytesIO()
    im.save(out, format="TGA", compression=None)
    return out.getvalue()


def _protect_dimensions(std: bytes) -> bytes:
    out = bytearray(std)
    for i in range(12, 16):
        out[i] = (out[i] + TGA_KEY[i]) & 0xFF
    return bytes(out)


def test_ship_bmp_resize_reencodes_proven_family(tmp_path: Path):
    source = _protect_ship(_bmp_bytes())
    src = tmp_path / "ship.bmp"
    src.write_bytes(source)

    rec, meta = t.inspect_texture(src)
    assert rec.format == "BMP_SHIP_DIB40_PROTECTED_EXACT"
    assert rec.protection_mode == "SHIP_DIB40"
    image = t.decode_texture(src, rec, meta)
    resized = t.upscale_lanczos(image, 2, profile="faithful")
    encoded = t.encode_texture(resized, source, rec, meta)

    decoded, proof = decode_ship_bmp_bytes(encoded)
    assert proof["width"] == 16
    assert proof["height"] == 16
    with Image.open(io.BytesIO(decoded)) as verify:
        verify.load()
        assert verify.size == (16, 16)


def test_dimension_only_tga_resize_reencodes_same_physical_family(tmp_path: Path):
    source = _protect_dimensions(_tga_bytes())
    assert _probe_tga(source)["classification"].startswith("TGA_PROTECTED_DIMENSIONS_12_15")
    src = tmp_path / "dimension-only.tga"
    src.write_bytes(source)

    rec, meta = t.inspect_texture(src)
    assert rec.format == "TGA_RARE_PHYSICAL_COMPAT"
    assert rec.protection_mode == "DIMENSIONS_12_15"
    image = t.decode_texture(src, rec, meta)
    resized = t.upscale_lanczos(image, 2, profile="faithful")
    encoded = t.encode_texture(resized, source, rec, meta)

    proof = _probe_tga(encoded)
    assert proof["classification"].startswith("TGA_PROTECTED_DIMENSIONS_12_15")
    decoded, _ = t._rare_tga_decode_for_upscale(encoded)
    with Image.open(io.BytesIO(decoded)) as verify:
        verify.load()
        assert verify.size == (16, 16)


def test_zero_filled_tga_remains_fail_closed():
    assert t._rare_tga_decode_for_upscale(bytes(64)) is None


def _protect_g8_runtime(std: bytes) -> bytes:
    # Exact runtime protection: first two bytes become G8 and bytes 2..17 use c*c.
    out = bytearray(std)
    out[0:2] = b"G8"
    for c in range(2, 18):
        out[c] = (out[c] + (c * c)) & 0xFF
    return bytes(out)


def test_g8_runtime_tga_resize_reencodes_reversible_family(tmp_path: Path):
    standard = _tga_bytes()
    # Add a historical non-TGA2 trailer so rare_outliers rejects the container
    # while the exact runtime transform + Pillow still yields a valid image.
    source = _protect_g8_runtime(standard[:-26] + b"LEGACY")
    assert source[:2] == b"G8"
    assert _probe_tga(source)["classification"] == "TGA_ANOMALY_UNRESOLVED"

    src = tmp_path / "dropitem.tga"
    src.write_bytes(source)
    rec, meta = t.inspect_texture(src)
    assert rec.format == "TGA_RARE_PHYSICAL_COMPAT"
    assert rec.protection_mode == "G8_RUNTIME"

    image = t.decode_texture(src, rec, meta)
    resized = t.upscale_lanczos(image, 2, profile="faithful")
    encoded = t.encode_texture(resized, source, rec, meta)
    assert encoded[:2] == b"G8"

    decoded = t._runtime_decrypt_tga(encoded)
    with Image.open(io.BytesIO(decoded)) as verify:
        verify.load()
        assert verify.size == (16, 16)


def test_g8_runtime_non_image_remains_fail_closed():
    raw = b"G8" + bytes(range(2, 18)) + b"not-an-image"
    assert t._runtime_g8_candidate(raw) is None
