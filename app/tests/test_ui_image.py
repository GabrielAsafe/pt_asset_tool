from __future__ import annotations

import struct
from pathlib import Path

from pt_asset_tool.ui_image import PNG_SIG, tga_to_png_bytes


def test_uncompressed_tga_converts_to_png(tmp_path: Path):
    # 2x2, 24-bit, bottom-left origin. BGR pixels: red, green / blue, white.
    h=bytearray(18); h[2]=2
    struct.pack_into('<HHHHBB',h,8,0,0,2,2,24,0)
    pixels = bytes([
        0,0,255,   0,255,0,
        255,0,0,   255,255,255,
    ])
    p=tmp_path/'x.tga'; p.write_bytes(bytes(h)+pixels)
    out=tga_to_png_bytes(p)
    assert out.startswith(PNG_SIG)
    assert b'IHDR' in out and b'IDAT' in out


def test_catalog_marks_tga_previewable(tmp_path: Path):
    from pt_asset_tool.ui_catalog import CatalogIndex, UIStateStore
    client=tmp_path/'client'; client.mkdir(); p=client/'image/interface/a.tga'; p.parent.mkdir(parents=True); p.write_bytes(b'not parsed during indexing')
    idx=CatalogIndex(client,UIStateStore(tmp_path/'state.json')); idx.rebuild()
    row=idx.get_asset('image/interface/a.tga')
    assert row and row['previewable'] is True and row['category']=='UI'
