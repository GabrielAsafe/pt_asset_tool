from __future__ import annotations

import struct
from pathlib import Path

from pt_asset_tool.model062_material_writer import locate_materials, rebuild_material_fields, verify_material_candidate


def _material_smd(path: Path, *, two_side: int = 0) -> Path:
    sh=556; group=88; mat=320
    total=sh+group+mat
    b=bytearray(total)
    b[:23]=b"SMD Model data Ver 0.62"
    struct.pack_into("<i", b, 24, 0)  # object count
    struct.pack_into("<i", b, 28, 1)  # material count
    struct.pack_into("<i", b, 32, sh) # material group
    struct.pack_into("<i", b, 36, total) # first object / end material region
    struct.pack_into("<I", b, sh+8, 1)
    raw=sh+group
    struct.pack_into("<I", b, raw+0, 0) # material not carrying optional string
    struct.pack_into("<I", b, raw+124, two_side)
    struct.pack_into("<f", b, raw+144, 0.0)
    struct.pack_into("<f", b, raw+148, 0.0)
    path.write_bytes(b)
    return path


def test_model062_material_writer_changes_only_authorized_field_bytes(tmp_path):
    src=_material_smd(tmp_path/'src.smd', two_side=0)
    before=src.read_bytes()
    layout=locate_materials(before)
    assert layout['material_count']==1
    rebuilt, report=rebuild_material_fields(before, material_index=0, edits={'two_side':1})
    assert report['status']=='PASS' and report['edit_observed'] is True
    verify=verify_material_candidate(before,rebuilt,material_index=0,edits={'two_side':1})
    assert verify['status']=='PASS'
    assert verify['diff_outside_authorized_fields']==[]
    assert 1 <= verify['diff_byte_count'] <= 4


def test_model062_material_writer_rejects_unsafe_values(tmp_path):
    import pytest
    src=_material_smd(tmp_path/'src.smd')
    with pytest.raises(ValueError,match='two_side'):
        rebuild_material_fields(src,material_index=0,edits={'two_side':7})
    with pytest.raises(ValueError,match='transparency'):
        rebuild_material_fields(src,material_index=0,edits={'transparency':2.0})
