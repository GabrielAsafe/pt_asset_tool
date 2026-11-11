"""Read-only strict SRES-v2 embedded localization extractor."""
from __future__ import annotations
import hashlib
import struct
from pathlib import Path

HEADER = struct.Struct('<4sHH10I32s')
RECORD = struct.Struct('<6I')
EMBEDDED_LOCALIZATION_PATH = '__summit_internal__/localization.sloc'

def extract_sloc_bytes(source: Path | bytes) -> bytes:
    data = source.read_bytes() if isinstance(source, Path) else source
    if len(data) < HEADER.size:
        raise ValueError('SRES too small')
    magic, version, flags, rc, ro, rs, so, ss, po, ps, profile, z0, z1, sha = HEADER.unpack_from(data)
    if magic != b'SRES' or version != 2 or flags or rs != RECORD.size or ro != HEADER.size or z0 or z1:
        raise ValueError('SRES header invalid')
    if so != ro + rc * rs or po != so + ss or po + ps != len(data):
        raise ValueError('SRES layout invalid')
    if hashlib.sha256(data[HEADER.size:]).digest() != sha:
        raise ValueError('SRES body SHA mismatch')
    def string(off):
        if off >= ss: raise ValueError('SRES string offset')
        pos = so + off
        end = data.find(b'\0', pos, so + ss)
        if end < 0: raise ValueError('SRES unterminated string')
        return data[pos:end].decode('utf-8')
    found = []
    for idx in range(rc):
        path, ident, kind, flags, rel, size = RECORD.unpack_from(data, ro + idx * rs)
        if rel > ps or size > ps - rel: raise ValueError('SRES payload outside range')
        if string(path) == EMBEDDED_LOCALIZATION_PATH:
            if string(ident) != 'summit.localization.catalog.v2' or kind != 4 or flags != 0:
                raise ValueError('embedded localization identity mismatch')
            found.append(data[po + rel:po + rel + size])
    if len(found) != 1:
        raise ValueError(f'expected exactly one embedded localization, found {len(found)}')
    if len(found[0]) < 80 or found[0][:4] != b'SLOC':
        raise ValueError('embedded localization payload invalid')
    return found[0]
