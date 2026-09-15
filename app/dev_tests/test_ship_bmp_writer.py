from __future__ import annotations

import struct

from pt_asset_tool.rare_outliers import SHIP_BMP_DIB40_KEY
from pt_asset_tool.rare_support import decode_ship_bmp_bytes, build_ship_bmp_bytes


def _protected_ship_bmp() -> bytes:
    width=2; height=2; image_size=width*height*3; total=54+image_size+2
    std=bytearray(total)
    std[:2]=b'BM'; struct.pack_into('<I',std,2,total); struct.pack_into('<I',std,10,54)
    struct.pack_into('<I',std,14,40); struct.pack_into('<i',std,18,width); struct.pack_into('<i',std,22,height)
    struct.pack_into('<H',std,26,1); struct.pack_into('<H',std,28,24); struct.pack_into('<I',std,30,0); struct.pack_into('<I',std,34,image_size)
    std[54:54+image_size]=bytes(range(1,image_size+1)); std[-2:]=b'\0\0'
    protected=bytearray(std)
    protected[:2]=b'PX'
    for c in range(2,14): protected[c]=(std[c]+c*c)&0xFF
    for i,key in enumerate(SHIP_BMP_DIB40_KEY): protected[14+i]=(std[14+i]+key)&0xFF
    return bytes(protected)


def test_ship_bmp_candidate_pixel_edit_roundtrips_and_preserves_protected_header():
    baseline=_protected_ship_bmp()
    editable,meta=decode_ship_bmp_bytes(baseline)
    assert editable[:2]==b'BM'
    changed=bytearray(editable); changed[54] ^= 0x55
    rebuilt,build=build_ship_bmp_bytes(baseline,bytes(changed))
    assert rebuilt[:54]==baseline[:54]
    assert rebuilt[-2:]==baseline[-2:]
    assert rebuilt[54] != baseline[54]
    decoded,_=decode_ship_bmp_bytes(rebuilt)
    assert decoded==bytes(changed)
    assert build['protected_header_byte_identical'] is True
    assert build['client_modified'] is False
