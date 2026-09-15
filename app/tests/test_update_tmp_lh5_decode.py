from __future__ import annotations
import pathlib, struct
from pt_asset_tool.update_tmp_lh5_decode import _decode_lha_archive_bytes, _png_info, _strict_lh5_level0_entry
from pt_asset_tool.update_tmp_lha_forensics import _crc16_lha


def _lha0(name: str, payload: bytes) -> bytes:
    nb=name.encode('ascii')
    hsize=22 + len(nb) + 2 - 2
    b=bytearray(2+hsize)
    b[0]=hsize
    b[2:7]=b'-lh0-'
    struct.pack_into('<II',b,7,len(payload),len(payload))
    struct.pack_into('<I',b,15,0)
    b[19]=0x20; b[20]=0; b[21]=len(nb); b[22:22+len(nb)]=nb
    struct.pack_into('<H',b,22+len(nb),_crc16_lha(payload))
    b[1]=sum(b[2:2+hsize]) & 0xff
    return bytes(b)+payload+b'\x00'


def test_libarchive_bridge_reads_lha_and_preserves_bytes():
    payload=b'hello libarchive lha bridge'
    raw=_lha0('x.txt',payload)
    expected=[{'filename':'x.txt','original_size':len(payload)}]
    decoded, meta=_decode_lha_archive_bytes(raw,expected)
    assert decoded[0]['filename']=='x.txt'
    assert decoded[0]['data']==payload
    assert decoded[0]['decoded_size']==len(payload)
    assert meta['library']


def test_png_info_strict_ihdr():
    p=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',320,200)+b'abcde'
    r=_png_info(p)
    assert r['png_magic_ok'] and r['ihdr_ok']
    assert r['width']==320 and r['height']==200


def test_wrapper_has_v0103_lh5_command():
    text=(pathlib.Path(__file__).parents[1]/'payload/pt_asset.py').read_text()
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'update-tmp-lh5-decode' in text


def test_strict_lh5_guard_preserves_numeric_level_zero():
    e={
        'method':'-lh5-',
        'level':0,
        'checksum_ok':True,
        'payload_bounds_ok_level0':True,
    }
    assert _strict_lh5_level0_entry(e) is True
    assert _strict_lh5_level0_entry({**e, 'level':None}) is False
    assert _strict_lh5_level0_entry({**e, 'method':'-lh0-'}) is False
