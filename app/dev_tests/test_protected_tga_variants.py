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


def test_protected_rle_no_footer_run_packet_exact_closure_is_supported():
    # 0x81 is a 2-pixel run packet followed by one 24-bit pixel.
    raw = _protected_no_footer(image_type=10)
    info=tga.inspect_bytes(raw)
    assert info["protected"] is True
    assert info["rle_decoded_pixel_count"] == 2
    assert info["rle_packet_count"] == 1


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


def _rle_payload_raw_pixels(*, w=2, h=1, bpp=24):
    # One raw packet containing exactly w*h pixels.
    pixel_bytes=bpp//8
    count=w*h
    return bytes([count-1]) + bytes(range(count*pixel_bytes))


def _protected_rle_exact(*, w=2, h=1, bpp=24):
    std=_std_header(image_type=10,w=w,h=h,bpp=bpp)
    return tga.protect_header(std,"FULL18") + _rle_payload_raw_pixels(w=w,h=h,bpp=bpp)


def test_protected_rle_no_footer_exact_closure_is_supported():
    raw=_protected_rle_exact(w=2,h=1,bpp=24)
    info=tga.inspect_bytes(raw)
    assert info["protected"] is True
    assert info["container_variant"] == "TGA1_RLE_NO_FOOTER_EXACT_CLOSURE"
    assert info["rle_decoded_pixel_count"] == 2
    editable,_=tga.decode_bytes(raw)
    einfo=tga.inspect_bytes(editable)
    witness=tga.editable_payload_witness_offset(editable,einfo)
    assert witness == 19  # byte 18 is packet header; byte 19 starts pixel data
    changed=bytearray(editable); changed[witness] ^= 1
    rebuilt,_,_=tga.build_bytes(raw,bytes(changed))
    decoded,_=tga.decode_bytes(rebuilt)
    assert decoded == bytes(changed)


def test_protected_rle_no_footer_truncated_packet_rejected():
    std=_std_header(image_type=10,w=2,h=1,bpp=24)
    raw=tga.protect_header(std,"FULL18") + bytes([1]) + b"\x01\x02\x03"  # raw packet says 2 pixels, carries 1
    with pytest.raises(ValueError):
        tga.inspect_bytes(raw)


def test_protected_rle_no_footer_pixel_overrun_rejected():
    std=_std_header(image_type=10,w=2,h=1,bpp=24)
    raw=tga.protect_header(std,"FULL18") + bytes([2]) + bytes(range(9))  # raw packet says 3 pixels
    with pytest.raises(ValueError):
        tga.inspect_bytes(raw)



def _protected_rle_tga20_extension(*, declared_ext_size=495, physical_ext_size=495, developer_offset=0):
    std=_std_header(image_type=10,w=2,h=1,bpp=24)
    payload=_rle_payload_raw_pixels(w=2,h=1,bpp=24)
    ext_off=18+len(payload)
    ext=bytearray(physical_ext_size)
    struct.pack_into("<H",ext,0,declared_ext_size)
    footer=struct.pack("<II",ext_off,developer_offset)+tga.FOOTER_SIG
    return tga.protect_header(std,"FULL18")+payload+bytes(ext)+footer


def test_protected_rle_tga20_declared_494_physical_495_exact_boundary_is_supported():
    raw=_protected_rle_tga20_extension(declared_ext_size=494,physical_ext_size=495,developer_offset=0)
    info=tga.inspect_bytes(raw)
    assert info["protected"] is True
    assert info["container_variant"] == "TGA20_EXTENSION_AREA_495_DECLARED_494_OFF_BY_ONE"
    assert info["extension_size"] == 494
    assert info["extension_size_effective"] == 495
    assert info["extension_size_policy"] == "DECLARED_494_PHYSICAL_495_EXACT_BOUNDARY"
    assert info["rle_decoded_pixel_count"] == 2
    editable,_=tga.decode_bytes(raw)
    einfo=tga.inspect_bytes(editable)
    assert einfo["container_variant"] == info["container_variant"]
    witness=tga.editable_payload_witness_offset(editable,einfo)
    changed=bytearray(editable); changed[witness] ^= 1
    rebuilt,_,_=tga.build_bytes(raw,bytes(changed))
    assert rebuilt[info["payload_end"]:] == raw[info["payload_end"]:]
    assert rebuilt[:18] == raw[:18]


def test_declared_494_is_rejected_when_physical_span_is_not_exactly_495():
    raw=_protected_rle_tga20_extension(declared_ext_size=494,physical_ext_size=494,developer_offset=0)
    with pytest.raises(ValueError):
        tga.inspect_bytes(raw)


def test_declared_494_is_rejected_when_developer_area_is_present():
    # Developer offset is nonzero, so the exact no-developer physical proof does not hold.
    std=_std_header(image_type=10,w=2,h=1,bpp=24)
    payload=_rle_payload_raw_pixels(w=2,h=1,bpp=24)
    ext_off=18+len(payload)
    ext=bytearray(495); struct.pack_into("<H",ext,0,494)
    dev_off=ext_off+495
    footer=struct.pack("<II",ext_off,dev_off)+tga.FOOTER_SIG
    raw=tga.protect_header(std,"FULL18")+payload+bytes(ext)+b"DEV"+footer
    with pytest.raises(ValueError):
        tga.inspect_bytes(raw)
