import importlib.util
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pt_tga_test", ROOT / "pt_protected_tga_v1.py")
tga = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tga)


def _std_header(*, image_type=2, w=2, h=1, bpp=24):
    h18 = bytearray(18)
    h18[2] = image_type
    struct.pack_into("<H", h18, 12, w)
    struct.pack_into("<H", h18, 14, h)
    h18[16] = bpp
    return bytes(h18)


def _protected_no_footer(*, image_type=2):
    std = _std_header(image_type=image_type)
    if image_type == 2:
        body = bytes(range(6))
    else:
        body = b"\x81\x01\x02\x03"
    return tga.protect_header(std, "FULL18") + body


def test_protected_type2_no_footer_exact_payload_roundtrip():
    raw = _protected_no_footer(image_type=2)
    info = tga.inspect_bytes(raw)
    assert info["protected"] is True
    assert info["container_variant"] == "TGA1_STYLE_NO_FOOTER_EXACT_PAYLOAD"
    assert info["footer_size"] == 0
    editable, _ = tga.decode_bytes(raw)
    changed = bytearray(editable)
    changed[info["payload_start"]] ^= 1
    rebuilt, _, _ = tga.build_bytes(raw, bytes(changed))
    assert rebuilt[:18] == raw[:18]
    assert len(rebuilt) == len(raw)
    decoded, _ = tga.decode_bytes(rebuilt)
    assert decoded == bytes(changed)


def test_protected_rle_no_footer_remains_blocked():
    raw = _protected_no_footer(image_type=10)
    with pytest.raises(ValueError):
        tga.inspect_bytes(raw)


def test_protected_type2_tga20_extension_suffix_preserved():
    std = _std_header(image_type=2)
    pixels = bytes(range(6))
    ext_off = 18 + len(pixels)
    ext = bytearray(tga.EXTENSION_AREA_SIZE)
    struct.pack_into("<H", ext, 0, tga.EXTENSION_AREA_SIZE)
    footer = struct.pack("<II", ext_off, 0) + tga.FOOTER_SIG
    raw = tga.protect_header(std, "FULL18") + pixels + bytes(ext) + footer
    info = tga.inspect_bytes(raw)
    assert info["container_variant"] == "TGA20_EXTENSION_AREA_495"
    editable, _ = tga.decode_bytes(raw)
    changed = bytearray(editable)
    changed[info["payload_start"] + 1] ^= 1
    rebuilt, _, _ = tga.build_bytes(raw, bytes(changed))
    assert rebuilt[info["payload_end"]:] == raw[info["payload_end"]:]


def test_exact_regression_gate_keeps_no_footer_protected_tga(tmp_path):
    from types import SimpleNamespace
    from pt_asset_tool.texture_codec_devtest import audit_proprietary_texture_exact_regressions

    source = tmp_path / "crow2.tga"
    source.write_bytes(_protected_no_footer(image_type=2))
    asset = SimpleNamespace(primary_path="weapons/crow2.tga", family="TGA_NONSTANDARD_OR_PROTECTED")

    class Registry:
        def resolve(self, logical):
            assert str(logical).casefold() == "weapons/crow2.tga"
            return asset

    class Resolver:
        def resolve(self, logical, required=True):
            return source

    root = tmp_path / "app"
    root.mkdir()
    # The production codec module is loaded from project_root; mirror just that
    # one tool in the synthetic project.
    (root / "pt_protected_tga_v1.py").write_bytes((ROOT / "pt_protected_tga_v1.py").read_bytes())
    before = source.read_bytes()
    result = audit_proprietary_texture_exact_regressions(root, Registry(), Resolver(), ["weapons/crow2.tga"])
    assert result["status"] == "PASS"
    assert result["pass_count"] == 1
    assert source.read_bytes() == before
