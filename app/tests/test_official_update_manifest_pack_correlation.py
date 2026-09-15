from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from pt_asset_tool.official_update_manifest_pack_correlation import _calibrate_setfile, _probe_pack, _target_family_refs


def _record(path: str, size: int, crc: int) -> bytes:
    # Synthetic updater-manifest-like record: fields immediately before path.
    pre = bytearray(24)
    struct.pack_into('<I', pre, 0, size)       # START-24
    struct.pack_into('<I', pre, 4, crc)        # START-20
    return bytes(pre) + path.encode('latin-1') + b'\x00' + b'\x00' * 16


def test_manifest_calibration_and_tff_detection(tmp_path):
    donor = tmp_path / 'donor'; donor.mkdir()
    image = donor / 'image'; image.mkdir()
    # Enough real loose refs to prove a structural size/CRC field.
    recs = []
    for i in range(80):
        p = image / f'cal{i:03d}.bmp'
        data = (f'CAL-{i:03d}-'.encode() * 20) + bytes(range(64))
        p.write_bytes(data)
        recs.append(_record(f'image/cal{i:03d}.bmp', len(data), zlib.crc32(data) & 0xffffffff))
    recs.append(_record('char/tmABCD/TfbF01.smd', 1234, 0x11223344))
    recs.append(_record('char/tmABCD/TfhF01.smd', 567, 0x55667788))
    sf = donor / 'setfile.lst'; sf.write_bytes(b''.join(recs))
    c = _calibrate_setfile(sf, donor, max_crc=100)
    assert c['strong_size_field_proven'] is True
    assert c['strong_crc32_field_proven'] is True
    assert c['best_size_field']['anchor'] == 'START' and c['best_size_field']['rel'] == -24
    assert c['best_crc32_field']['anchor'] == 'START' and c['best_crc32_field']['rel'] == -20
    refs = _target_family_refs(sf)
    assert any(x.lower().endswith('tfbf01.smd') for x in refs)
    assert any(x.lower().endswith('tfhf01.smd') for x in refs)


def test_pack_probe_detects_raw_magic_and_plaintext(tmp_path):
    root = tmp_path / 'donor'; (root/'image').mkdir(parents=True)
    p = root/'image/cdata1'
    p.write_bytes(b'X'*200 + b'SMD Model data Ver 0.62' + b'Y'*200 + b'char/tmABCD/TfbF01.smd')
    r = _probe_pack(p, root)
    assert r['known_magic_counts']['MODEL062'] == 1
    assert r['plaintext_tmabcd_count'] == 1
    assert r['size'] == p.stat().st_size


def test_overlay_version_and_route_present():
    root = Path(__file__).resolve().parents[1]
    text = (root/'payload/pt_asset.py').read_text()
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'official-update-manifest-pack-correlation' in text
