from __future__ import annotations
import mmap, pathlib, struct
from pt_asset_tool.update_tmp_lha_forensics import _crc16_lha, _inspect_payload_bytes
from pt_asset_tool.official_container_record_index import _lha_entries


def _lha0(name: str, payload: bytes) -> bytes:
    nb=name.encode('ascii')
    # LHA level 0 header: method..name + file CRC16. header_size excludes first 2 bytes.
    hsize=22 + len(nb) + 2 - 2
    b=bytearray(2+hsize)
    b[0]=hsize
    b[2:7]=b'-lh0-'
    struct.pack_into('<II',b,7,len(payload),len(payload))
    struct.pack_into('<I',b,15,0)
    b[19]=0x20; b[20]=0; b[21]=len(nb); b[22:22+len(nb)]=nb
    struct.pack_into('<H',b,22+len(nb),_crc16_lha(payload))
    b[1]=sum(b[2:2+hsize]) & 0xff
    return bytes(b)+payload


def test_lha0_parser_crc_and_nested_evidence(tmp_path):
    payload=b'prefix TfbF01.smd xxx SMD Model data Ver 0.62 suffix patch001.upw http://patch.example/x'
    p=tmp_path/'update.tmp'; p.write_bytes(_lha0('patch.bin',payload))
    with p.open('rb') as f:
        mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
        try: es=_lha_entries(mm)
        finally: mm.close()
    assert len(es)==1 and es[0]['method']=='-lh0-' and es[0]['checksum_ok'] and es[0]['payload_bounds_ok_level0']
    r=_inspect_payload_bytes(payload,tmp_path,'x')
    assert r['model062_magic_count']==1
    assert r['target_name_hits'][0]['text'].lower()=='tfbf01.smd'
    assert r['upw_hits'] and r['url_hits']


def test_wrapper_has_v0102_command():
    text=(pathlib.Path(__file__).parents[1]/'payload/pt_asset.py').read_text()
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'update-tmp-lha-forensics' in text
