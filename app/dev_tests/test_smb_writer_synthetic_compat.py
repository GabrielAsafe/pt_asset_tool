from __future__ import annotations

import pathlib
import struct

from pt_asset_tool.motion_core import load_smb_evaluator
from pt_asset_tool.smb_writer import first_editable_key, parse_smb_structural, patch_key, validate_track_roundtrip
from pt_asset_tool.standalone_animation_devtest import audit_smb_animation_corpus
from pt_asset_tool.writer_corpus_audit import _adjacent_distinct_float32

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _make_smb(path: pathlib.Path, *, physique: bool, pos_x: float = 1.0, parent: str = "") -> pathlib.Path:
    ev = load_smb_evaluator(ROOT)
    obj_start = ev.SIZE_DFILE_HEADER + ev.SIZE_DFILE_OBJINFO
    nv, nf, nt, nr, np, ns = (1 if physique else 0), 0, 0, 0, 1, 0
    length = ev.SIZE_OBJ3D + nv * ev.SIZE_VERTEX + np * ev.SIZE_TM_POS + (nv * 32 if physique else 0)
    data = bytearray(obj_start + length)
    data[:len(ev.SMD_HEADER)] = ev.SMD_HEADER
    struct.pack_into('<i', data, 24, 1)  # object count
    struct.pack_into('<i', data, 28, 0)  # material count
    struct.pack_into('<i', data, 40, 0)  # header TmFrameCounter
    info = ev.SIZE_DFILE_HEADER
    data[info:info+4] = b'Bip\0'
    struct.pack_into('<ii', data, info + 32, length, obj_start)
    raw = obj_start
    if physique:
        struct.pack_into('<I', data, raw + 16, 1)
    struct.pack_into('<iii', data, raw + ev.O_NVERTEX, nv, nf, nt)
    data[raw + ev.O_NODENAME:raw + ev.O_NODENAME + 4] = b'Bip\0'
    if parent:
        pb=parent.encode('ascii')+b'\0'
        data[raw + ev.O_NODEPARENT:raw + ev.O_NODEPARENT + len(pb)] = pb
    struct.pack_into('<iii', data, raw + ev.O_TMROTCNT, nr, np, ns)
    struct.pack_into('<i', data, raw + ev.O_TMFRAMECNT, 0)
    pos_base = obj_start + ev.SIZE_OBJ3D + nv * ev.SIZE_VERTEX
    struct.pack_into('<i3f', data, pos_base, 0, float(pos_x), 2.0, 3.0)
    if physique:
        ph = pos_base + ev.SIZE_TM_POS
        data[ph:ph+4] = b'Bip\0'
    path.write_bytes(data)
    return path



def _make_duplicate_name_smb(path: pathlib.Path) -> pathlib.Path:
    ev = load_smb_evaluator(ROOT)
    count = 2
    table_end = ev.SIZE_DFILE_HEADER + count * ev.SIZE_DFILE_OBJINFO
    object_len = ev.SIZE_OBJ3D + ev.SIZE_TM_POS
    starts = [table_end, table_end + object_len]
    data = bytearray(table_end + count * object_len)
    data[:len(ev.SMD_HEADER)] = ev.SMD_HEADER
    struct.pack_into('<i', data, 24, count)
    struct.pack_into('<i', data, 28, 0)
    struct.pack_into('<i', data, 40, 0)
    for idx, start in enumerate(starts):
        info = ev.SIZE_DFILE_HEADER + idx * ev.SIZE_DFILE_OBJINFO
        data[info:info+4] = b'Bip\0'
        struct.pack_into('<ii', data, info + 32, object_len, start)
        data[start + ev.O_NODENAME:start + ev.O_NODENAME + 4] = b'Bip\0'
        struct.pack_into('<iii', data, start + ev.O_NVERTEX, 0, 0, 0)
        struct.pack_into('<iii', data, start + ev.O_TMROTCNT, 0, 1, 0)
        struct.pack_into('<i', data, start + ev.O_TMFRAMECNT, 0)
        pos_base = start + ev.SIZE_OBJ3D
        struct.pack_into('<i3f', data, pos_base, 0, 1.0 + idx, 2.0, 3.0)
    path.write_bytes(data)
    return path

def test_smb_physique_tail_is_part_of_exact_layout_and_preserved(tmp_path):
    source = _make_smb(tmp_path/'physique.smb', physique=True)
    before = source.read_bytes()
    r = validate_track_roundtrip(ROOT, source)
    assert r['status'] == 'PASS'
    assert r['byte_identical'] is True
    ev = load_smb_evaluator(ROOT)
    parsed = ev.parse_smb(source)
    assert parsed['bones'][0]['has_physique'] is True
    out = tmp_path/'edited.smb'
    patch_key(ROOT, source, out, bone='Bip', track='pos', key_index=0, x=4.0)
    assert source.read_bytes() == before
    # Physique tail is not in the edit allowlist and must remain exact.
    assert out.read_bytes()[-32:] == before[-32:]


def test_adjacent_float32_probe_is_distinct_when_decimal_delta_would_quantize_away(tmp_path):
    source = _make_smb(tmp_path/'large.smb', physique=False, pos_x=100_000_000.0)
    key = first_editable_key(ROOT, source)
    old = float(key['values'][0])
    assert struct.unpack('<f', struct.pack('<f', old + 0.25))[0] == old
    new = _adjacent_distinct_float32(old)
    assert struct.unpack('<f', struct.pack('<f', new))[0] != old
    out = tmp_path/'large_edit.smb'
    result = patch_key(ROOT, source, out, bone='Bip', track='pos', key_index=0, x=new)
    assert result['status'] == 'PASS'
    assert result['changed_byte_count'] > 0


def test_external_parent_smb_is_structurally_valid_but_not_standalone_evaluable(tmp_path):
    source = _make_smb(tmp_path/'support.smb', physique=False, parent='ExternalRoot')
    ev = load_smb_evaluator(ROOT)
    import pytest
    with pytest.raises(RuntimeError, match='missing parent'):
        ev.parse_smb(source)
    relaxed = parse_smb_structural(ROOT, source)
    assert relaxed['hierarchy_closed'] is False
    assert relaxed['missing_parent_names'] == ['ExternalRoot']

    class Registry:
        records = [{'extension': '.smb', 'relative_path': 'char/npc/support.smb', 'category_hint': 'NPC'}]
    class Resolver:
        def resolve(self, logical, required=True):
            return source
    audit = audit_smb_animation_corpus(Registry(), Resolver())
    assert audit['status'] == 'PASS'
    assert audit['parse_pass_count'] == 1
    assert audit['by_domain']['NPC']['external_parent_support_count'] == 1
    assert audit['animated_smb_file_count'] == 0

def test_duplicate_nodename_smb_is_structural_support_only(tmp_path):
    source = _make_duplicate_name_smb(tmp_path/'duplicate.smb')
    ev = load_smb_evaluator(ROOT)
    import pytest
    with pytest.raises(RuntimeError, match='duplicate NodeName'):
        ev.parse_smb(source)
    relaxed = parse_smb_structural(ROOT, source)
    assert relaxed['serialized_layout_closed'] is True
    assert relaxed['node_names_unique'] is False
    assert relaxed['duplicate_node_names'] == ['Bip']
    assert relaxed['hierarchy_closed'] is False

    class Registry:
        records = [{'extension': '.smb', 'relative_path': 'char/monster/duplicate.smb', 'category_hint': 'MONSTER'}]
    class Resolver:
        def resolve(self, logical, required=True):
            return source
    audit = audit_smb_animation_corpus(Registry(), Resolver())
    assert audit['status'] == 'PASS'
    assert audit['parse_pass_count'] == 1
    assert audit['animated_smb_file_count'] == 0
    assert audit['by_domain']['MONSTER']['structural_support_pass_count'] == 1
    assert audit['by_domain']['MONSTER']['duplicate_name_support_count'] == 1



def test_adjacent_distinct_float32_handles_negative_zero():
    import math, struct

    old = struct.unpack("<f", struct.pack("<I", 0x80000000))[0]
    assert math.copysign(1.0, old) < 0.0
    new = _adjacent_distinct_float32(old)
    assert math.isfinite(new)
    assert new != old
    assert struct.pack("<f", new) != struct.pack("<f", old)
    assert math.copysign(1.0, new) < 0.0
