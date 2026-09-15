#!/usr/bin/env python3
"""
Strict static Model0.62 witness writer.

Certification scope:
- no Physique;
- object-local animation arrays may exist but are preserved byte-identically;
- unchanged topology/material/UV/TexLink data;
- only vertex XYZ positions named by the witness manifest may change.

The source SMD is copied byte-for-byte except for the 12-byte XYZ fields of
verified witness vertices. The client/source SMD is never overwritten.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, struct, sys
import bpy
from mathutils import Matrix

HEADER = b"SMD Model data Ver 0.62"
SH, SI, SO, SV = 556, 40, 2236, 24
O_PHYS, O_NV, O_NF, O_NT, O_NAME, O_NR, O_NP, O_NS = 16,84,88,92,172,684,688,692


def _i32(b,o): return struct.unpack_from('<i', b, o)[0]
def _u32(b,o): return struct.unpack_from('<I', b, o)[0]
def _cs(b): return b.split(b'\0',1)[0].decode('latin1','replace')
def _sha(b): return hashlib.sha256(b).hexdigest()


def _args(argv):
    p=argparse.ArgumentParser()
    p.add_argument('--smd', required=True)
    p.add_argument('--object', required=True)
    p.add_argument('--witness', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--report')
    p.add_argument('--expected-source-sha256')
    return p.parse_args(argv)


def _find_object(data: bytes, name: str):
    if len(data)<SH or not data.startswith(HEADER):
        raise ValueError('not SMD Model data Ver 0.62')
    n=_i32(data,24)
    for i in range(n):
        off=SH+i*SI
        nm=_cs(data[off:off+32])
        length=_i32(data,off+32); start=_i32(data,off+36)
        if nm != name:
            continue
        raw=data[start:start+SO]
        node=_cs(raw[O_NAME:O_NAME+32])
        if node != name:
            raise ValueError(f'NodeName mismatch {name!r}/{node!r}')
        nv,nf,nt=[_i32(raw,o) for o in (O_NV,O_NF,O_NT)]
        nr,np,ns=[_i32(raw,o) for o in (O_NR,O_NP,O_NS)]
        phys=_u32(raw,O_PHYS)!=0
        return {'index':i,'name':name,'start':start,'length':length,'nv':nv,'nf':nf,'nt':nt,
                'nr':nr,'np':np,'ns':ns,'phys':phys,'vertex_start':start+SO}
    raise ValueError(f'object {name!r} missing from source SMD')


def _matrix_identity(obj, eps=1e-7):
    ident=Matrix.Identity(4)
    return all(abs(float(obj.matrix_world[r][c]-ident[r][c])) <= eps for r in range(4) for c in range(4))


def _sync(obj):
    if obj.mode == 'EDIT':
        bpy.context.view_layer.objects.active=obj
        obj.select_set(True)
        result=bpy.ops.object.mode_set(mode='OBJECT')
        if 'FINISHED' not in result:
            raise ValueError(f'failed to synchronize Edit Mode: {result}')
    obj.data.update()


def main(argv):
    a=_args(argv)
    srcp=pathlib.Path(a.smd).expanduser().resolve()
    outp=pathlib.Path(a.out).expanduser().resolve()
    wp=pathlib.Path(a.witness).expanduser().resolve()
    src=srcp.read_bytes(); source_sha=_sha(src)
    if a.expected_source_sha256 and source_sha.lower()!=a.expected_source_sha256.lower():
        raise ValueError('source SHA mismatch')
    info=_find_object(src,a.object)
    if info['phys']:
        raise ValueError(f"{a.object}: Physique object is outside static witness writer")

    witness=json.loads(wp.read_text(encoding='utf-8'))
    if str(witness.get('object') or '').lower()!=a.object.lower():
        raise ValueError(f"witness object mismatch: {witness.get('object')!r} != {a.object!r}")
    rows=list(witness.get('changed_vertices') or [])
    if not rows:
        raise ValueError('witness has no changed vertices')

    obj=bpy.data.objects.get(a.object)
    if obj is None or obj.type!='MESH':
        raise ValueError(f'{a.object}: Blender mesh missing')
    _sync(obj)
    if not _matrix_identity(obj):
        raise ValueError('object transform is not identity')
    mesh=obj.data
    if len(mesh.vertices)!=info['nv']:
        raise ValueError(f"vertex count drift: blender={len(mesh.vertices)} source={info['nv']}")

    source_positions=[]
    for vi in range(info['nv']):
        off=info['vertex_start']+vi*SV
        source_positions.append(struct.unpack_from('<3i',src,off))
    blender_fixed=[tuple(int(round(float(c)*256.0)) for c in v.co) for v in mesh.vertices]

    expected={}
    before_errors=[]
    for row in rows:
        vi=int(row['vertex'])
        if not 0<=vi<info['nv']:
            raise ValueError(f'witness vertex OOB: {vi}')
        before=tuple(int(round(float(c)*256.0)) for c in row['before'])
        after=tuple(int(round(float(c)*256.0)) for c in row['after'])
        if before != source_positions[vi]:
            before_errors.append({'vertex':vi,'witness_before':before,'source':source_positions[vi]})
        expected[vi]=after
    if before_errors:
        raise ValueError(f'witness source mismatch: {before_errors[:3]}')

    effective={vi:p for vi,p in expected.items() if p!=source_positions[vi]}
    if not effective:
        raise ValueError('witness edit quantized away')
    actual_changed={vi for vi,(s,b) in enumerate(zip(source_positions,blender_fixed)) if s!=b}
    if actual_changed != set(effective):
        extra=sorted(actual_changed-set(effective)); missing=sorted(set(effective)-actual_changed)
        raise ValueError(f'Blender changed vertex set differs from witness: extra={extra} missing={missing}')
    bad=[{'vertex':vi,'expected':p,'blender':blender_fixed[vi]} for vi,p in effective.items() if blender_fixed[vi]!=p]
    if bad:
        raise ValueError(f'Blender witness position mismatch: {bad[:3]}')

    out=bytearray(src)
    byte_ranges=[]
    for vi,p in sorted(effective.items()):
        off=info['vertex_start']+vi*SV
        struct.pack_into('<3i',out,off,*p)
        byte_ranges.append([off,off+12])
    out=bytes(out)
    if out==src:
        raise ValueError('output unexpectedly byte-identical')

    # Strong invariant: reverting the allowed XYZ byte ranges must recover source exactly.
    restored=bytearray(out)
    for vi in effective:
        off=info['vertex_start']+vi*SV
        restored[off:off+12]=src[off:off+12]
    if bytes(restored)!=src:
        raise ValueError('non-XYZ bytes changed unexpectedly')

    outp.parent.mkdir(parents=True,exist_ok=True)
    outp.write_bytes(out)
    result={
        'tool':'PT_STATIC_WITNESS_WRITER_V1', 'source_smd':str(srcp), 'source_sha256':source_sha,
        'object':a.object, 'source_counts':{'vertices':info['nv'],'faces':info['nf'],'texlinks':info['nt']},
        'changed_vertices':sorted(effective), 'changed_xyz_byte_ranges':byte_ranges,
        'non_xyz_bytes_byte_identical':True, 'normals_preserved_byte_identical':True,
        'faces_uv_material_texlink_preserved_byte_identical':True,
        'object_local_animation_keys':[info['nr'],info['np'],info['ns']],
        'object_local_animation_preserved_byte_identical':True,
        'output':str(outp), 'output_sha256':_sha(out), 'client_modified':False,
        'static_writer_check':'PASS'
    }
    rp=pathlib.Path(a.report).expanduser().resolve() if a.report else outp.with_suffix('.json')
    rp.parent.mkdir(parents=True,exist_ok=True)
    rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PT_STATIC_WITNESS_WRITER_V1')
    print(f"object={a.object}")
    print(f"changed_vertices={sorted(effective)}")
    print('non_xyz_bytes_byte_identical=True')
    print(f"output={outp}")
    print(f"output_sha256={_sha(out)}")
    print('client_modified=False')
    print('static_writer_check=PASS')

if __name__=='__main__':
    try:
        argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
        main(argv)
    except Exception as exc:
        print(f'static_writer_check=FAIL: {type(exc).__name__}: {exc}')
        raise
