from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]


def _module():
    p=ROOT/'history_py/pt_smd_blender_import_v3_static_armature.py'
    spec=importlib.util.spec_from_file_location('pt_import_legacy_compat',p)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_material_string_block_accepts_only_nul_terminal_padding():
    m=_module()
    assert m.decode_cstrings(b'a\0b\0\0',2)==['a','b']
    with pytest.raises(ValueError,match='string block mismatch'):
        m.decode_cstrings(b'a\0b\0X',2)


def _free_writer_module(monkeypatch):
    import importlib.util, sys, types
    fake_bpy=types.ModuleType('bpy'); fake_bmesh=types.ModuleType('bmesh')
    fake_mathutils=types.ModuleType('mathutils')
    class Dummy: pass
    fake_mathutils.Matrix=Dummy; fake_mathutils.Vector=Dummy
    monkeypatch.setitem(sys.modules,'bpy',fake_bpy)
    monkeypatch.setitem(sys.modules,'bmesh',fake_bmesh)
    monkeypatch.setitem(sys.modules,'mathutils',fake_mathutils)
    p=ROOT/'pt_blender_to_smd_free_mesh_v3.py'
    spec=importlib.util.spec_from_file_location('pt_free_writer_legacy_compat',p)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _container(mod, objects, trailer=b''):
    import struct
    n=len(objects)
    first=mod.SZ_HDR+n*mod.SZ_INFO
    blocks=[]; table=[]; cursor=first
    for name,parent,tm in objects:
        raw=bytearray(mod.SZ_OBJ)
        raw[mod.O_NAME:mod.O_NAME+len(name)]=name.encode('latin-1')
        raw[mod.O_PARENT:mod.O_PARENT+len(parent)]=parent.encode('latin-1')
        struct.pack_into('<16i',raw,mod.O_TM,*tm)
        blocks.append(bytes(raw)); table.append((name,len(raw),cursor)); cursor+=len(raw)
    data=bytearray(first)
    data[:len(mod.HEADER)]=mod.HEADER
    struct.pack_into('<i',data,24,n)
    for i,(name,length,start) in enumerate(table):
        off=mod.SZ_HDR+i*mod.SZ_INFO
        data[off:off+len(name)]=name.encode('latin-1')
        struct.pack_into('<i',data,off+32,length); struct.pack_into('<i',data,off+36,start)
    return bytes(data)+b''.join(blocks)+trailer


def test_free_mesh_parser_preserves_opaque_trailer_contract(monkeypatch):
    m=_free_writer_module(monkeypatch)
    tm=tuple(range(16))
    data=_container(m,[('Bone','',tm)],trailer=b'\xAA\xBBopaque')
    infos=m.parse_file(data)
    assert infos[-1]['start']+infos[-1]['length'] < len(data)
    assert data[infos[-1]['start']+infos[-1]['length']:] == b'\xAA\xBBopaque'


def test_free_mesh_skeleton_collapses_only_identical_duplicate(monkeypatch):
    m=_free_writer_module(monkeypatch)
    tm=tuple(range(16))
    same=_container(m,[('Bone','Root',tm),('Bone','Root',tm)])
    assert m.parse_skeleton(same)['Bone']==tm
    conflict=_container(m,[('Bone','Root',tm),('Bone','Other',tm)])
    with pytest.raises(ValueError,match='conflicting'):
        m.parse_skeleton(conflict)
