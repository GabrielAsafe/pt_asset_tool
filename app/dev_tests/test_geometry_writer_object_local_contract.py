from __future__ import annotations

import importlib.util
import struct
import sys
import types
from pathlib import Path


def _load_core():
    # The writer is a Blender script, but its binary layout helpers are pure.
    # Stub only import-time Blender modules so these helpers can be regression-tested.
    old={k:sys.modules.get(k) for k in ('bpy','bmesh','mathutils')}
    sys.modules['bpy']=types.ModuleType('bpy')
    sys.modules['bmesh']=types.ModuleType('bmesh')
    mathutils=types.ModuleType('mathutils')
    mathutils.Matrix=type('Matrix',(),{})
    mathutils.Vector=type('Vector',(),{})
    sys.modules['mathutils']=mathutils
    try:
        path=Path(__file__).resolve().parents[1]/'pt_blender_to_smd_free_mesh_v3.py'
        spec=importlib.util.spec_from_file_location('pt_free_mesh_core_test',path)
        mod=importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k,v in old.items():
            if v is None: sys.modules.pop(k,None)
            else: sys.modules[k]=v


def _smd(core, *, physique: bool):
    first=core.SZ_HDR+core.SZ_INFO
    nv,nf,nt,nr,np,ns=3,1,1,1,1,1
    motion_len=nr*core.SZ_ROT+np*core.SZ_POS+ns*core.SZ_SCALE+nr*core.SZ_MATRIX
    phys_len=nv*32 if physique else 0
    length=core.SZ_OBJ+nv*core.SZ_VERT+nf*core.SZ_FACE+nt*core.SZ_TEX+motion_len+phys_len
    out=bytearray(first+length)
    out[:len(core.HEADER)]=core.HEADER
    struct.pack_into('<i',out,24,1)
    out[core.SZ_HDR:core.SZ_HDR+4]=b'Obj\0'
    struct.pack_into('<2i',out,core.SZ_HDR+32,length,first)
    raw=memoryview(out)[first:first+core.SZ_OBJ]
    raw[core.O_NAME:core.O_NAME+4]=b'Obj\0'
    struct.pack_into('<i',raw,core.O_NV,nv); struct.pack_into('<i',raw,core.O_NF,nf); struct.pack_into('<i',raw,core.O_NT,nt)
    struct.pack_into('<i',raw,core.O_NR,nr); struct.pack_into('<i',raw,core.O_NP,np); struct.pack_into('<i',raw,core.O_NS,ns)
    texbase=0x123400
    struct.pack_into('<I',raw,core.O_TEX_PTR,texbase)
    struct.pack_into('<I',raw,core.O_PHYS_PTR,0x55 if physique else 0)
    lay=core.obj_layout(first,nv,nf,nt,nr,np,ns,physique)
    # One valid face/TexLink is enough for verify_output.
    struct.pack_into('<4H',out,lay['faces'],0,1,2,0)
    struct.pack_into('<I',out,lay['faces']+core.F_TEX_PTR,texbase)
    struct.pack_into('<I',out,lay['tex']+core.T_NEXT,0)
    motion=bytes((i*13+7)&0xFF for i in range(motion_len))
    out[lay['rot']:lay['rot']+motion_len]=motion
    if physique:
        for i in range(nv):
            off=lay['physique']+i*32
            out[off:off+5]=b'Bone\0'
    return bytes(out),motion


def test_object_local_payload_helper_preserves_rot_pos_scale_and_prevrot_bytes():
    core=_load_core()
    for physique in (False,True):
        data,motion=_smd(core,physique=physique)
        infos=core.parse_file(data)
        obj=core.parse_object(data,infos,'Obj')
        assert core.object_local_blob(data,obj)==motion
        assert (obj['nr'],obj['np'],obj['ns'])==(1,1,1)


def test_common_output_verifier_accepts_static_and_rigid_layouts_with_object_local_payload():
    core=_load_core()
    static,_=_smd(core,physique=False)
    rigid,_=_smd(core,physique=True)
    _infos,sobj=core.verify_output(static,'Obj',3,1)
    assert sobj['phys'] is False and sobj['bones']==[]
    _infos,robj=core.verify_output(rigid,'Obj',3,1)
    assert robj['phys'] is True and robj['bones']==['Bone','Bone','Bone']
