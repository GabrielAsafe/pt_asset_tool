"""P0 real-corpus writer probes. Byte-surgical SMD material edits, SMB/INX existing writers.

Never writes to the game. Evidence proves targeted bytes changed and native reader
acceptance if --execute; it does *not* prove runtime/animation playback.
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import struct
import uuid
from typing import Any

from . import etervale_integration as bridge
from . import etervale_writer_cert as writer

FORMAT = 'PT_ASSET_ETERVALE_P0_BINARY_GATE_V1'
SMD_MODEL = b'SMD Model data Ver 0.62'
SMD_STAGE = b'SMD Stage data Ver 0.72'
STAGE_HEAD = 556 + 262260
GROUP_SIZE = 88
MATERIAL_SIZE = 320


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def material_offsets(raw: bytes) -> tuple[int, list[int], str]:
    """Calculate material record locations from known legacy serialized layouts."""
    if len(raw) < STAGE_HEAD and raw.startswith(SMD_STAGE):
        raise ValueError('TRUNCATED_STAGE_HEADER')
    if raw.startswith(SMD_STAGE):
        from .stage072_corpus import DFILE_HEADER_SIZE, STAGE_HEADER_SIZE
        count = struct.unpack_from('<i', raw, 28)[0]
        start = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE
        material_bytes = struct.unpack_from('<i', raw, 36)[0] - struct.unpack_from('<i', raw, 32)[0]
        kind = 'STAGE_072'
    elif raw.startswith(SMD_MODEL):
        from .static_roundtrip import _parse
        parsed = _parse(raw)
        count = parsed['mat_count']
        start = struct.unpack_from('<i', raw, 32)[0]
        material_bytes = len(parsed['mat_region'])
        kind = 'MODEL_062'
    else:
        raise ValueError('NOT_SMD_STAGE072_OR_MODEL062')
    if not 1 <= count <= 5000 or not 0 <= start <= len(raw) or material_bytes <= GROUP_SIZE:
        raise ValueError('SMD_MATERIAL_REGION_INVALID')
    end = start + material_bytes
    if end > len(raw) or struct.unpack_from('<i', raw, start+8)[0] != count:
        raise ValueError('SMD_MATERIAL_GROUP_HEADER_INVALID')
    off = start+GROUP_SIZE
    positions=[]
    for i in range(count):
        if off+MATERIAL_SIZE > end:
            raise ValueError('SMD_MATERIAL_RECORD_TRUNCATED')
        positions.append(off)
        in_use, tex_count = struct.unpack_from('<II', raw, off)
        anim_count = struct.unpack_from('<I', raw, off+304)[0]
        if tex_count > 8 or anim_count > 32:
            raise ValueError('SMD_MATERIAL_TEXTURE_COUNT_INVALID')
        off += MATERIAL_SIZE
        if in_use:
            if off+4 > end: raise ValueError('SMD_MATERIAL_NAME_COUNT_TRUNCATED')
            name_bytes = struct.unpack_from('<i',raw,off)[0]
            if not 0 <= name_bytes <= 4096 or off+4+name_bytes > end:
                raise ValueError('SMD_MATERIAL_NAME_BYTES_INVALID')
            off += 4+name_bytes
    if off != end:
        raise ValueError(f'SMD_MATERIAL_REGION_NOT_EXACT:{off}:{end}')
    return start,positions,kind


def patch_smd_material(source: pathlib.Path, output: pathlib.Path, material: int = 0, self_illum: float | None = None) -> dict[str, Any]:
    """Exercise a real-world *in-place* SMD writer, preserving every other byte.

    Choose SelfIllum which is a known 32-bit material field, not geometry/collision.
    A source already outside the safe scalar range is rejected.
    """
    raw=source.read_bytes()
    _start, locations, kind = material_offsets(raw)
    if not 0 <= material < len(locations): raise ValueError('SMD_MATERIAL_ID_OOB')
    pos=locations[material]+148
    old=struct.unpack_from('<f',raw,pos)[0]
    if not math.isfinite(old) or not -100 <= old <= 100:
        raise ValueError('SMD_SELF_ILLUM_NOT_SAFE_TO_PROBE')
    new=(old+0.125 if old <= 99.875 else old-0.125) if self_illum is None else float(self_illum)
    if not math.isfinite(new) or not -100 <= new <= 100 or new == old:
        raise ValueError('SMD_SELF_ILLUM_NEW_VALUE_UNSAFE_OR_NOOP')
    buf=bytearray(raw)
    struct.pack_into('<f',buf,pos,new)
    changed=[i for i,(a,b) in enumerate(zip(raw,buf)) if a!=b]
    if not changed or any(i not in range(pos,pos+4) for i in changed):
        raise ValueError('SMD_UNEXPECTED_CHANGED_BYTES')
    if material_offsets(bytes(buf))[1] != locations:
        raise ValueError('SMD_LAYOUT_CHANGED')
    if kind == 'MODEL_062':
        from .static_roundtrip import _parse
        before, after = _parse(raw), _parse(bytes(buf))
        if before['n']!=after['n'] or any(x['block']!=y['block'] for x,y in zip(before['object_list'],after['object_list'])):
            raise ValueError('MODEL_OBJECT_BLOCK_CHANGED')
    else:
        from .stage072_corpus import parse_stage072
        if parse_stage072(source)['full_parse']!='PASS':
            raise ValueError('STAGE_SOURCE_FULL_PARSE_FAILED')
        # Parse exact candidate with its stage area/collision payload.
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(bytes(buf))
        if parse_stage072(output)['full_parse']!='PASS':
            output.unlink(missing_ok=True)
            raise ValueError('STAGE_CANDIDATE_FULL_PARSE_FAILED')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(bytes(buf))
    return {'writer':'SMD_MATERIAL_SELFILLUM_SURGICAL_V1','kind':kind,
            'material':material,'old_self_illum':old,'new_self_illum':new,
            'changed_byte_count':len(changed),'allowed_offsets_only':True,
            'file_size_identical':len(raw)==len(buf),
            'source_sha256':sha(raw),'candidate_sha256':sha(bytes(buf)),
            'opaque_and_geometry_bytes_preserved':True,'status':'PASS'}


def probe(root: pathlib.Path, path: str, work: pathlib.Path, *, execute: bool=False, build: bool=False, material: int=0) -> dict:
    if build and not execute: raise ValueError('BUILD_REQUIRES_EXECUTE')
    rel=pathlib.PurePosixPath(path)
    if not path or rel.is_absolute() or '..' in rel.parts or '\\' in path or rel.suffix.lower() not in ('.smd','.smb','.inx'):
        raise ValueError('P0_BINARY_ASSET_MUST_BE_RELATIVE_SMD_SMB_INX')
    original=bridge._input_path(root, path, None, {rel.suffix.lower()})
    output=work/'p0_binary'/uuid.uuid4().hex/('candidate-'+original.name)
    output.parent.mkdir(parents=True,exist_ok=False)
    if rel.suffix.lower()=='.smd':
        witness=patch_smd_material(original,output,material)
    elif rel.suffix.lower()=='.inx':
        import pt_inx_motion_core_v2 as core
        from .inx_writer import patch_motion
        parsed=core.parse_inx(original)
        motions=[m for m in parsed.get('motions',[]) if not str(m.get('state_name','')).startswith('UNKNOWN_')
                 and int(m.get('end',0)) > int(m.get('start',0)) and int(m.get('repeat',-1)) in (0,1)]
        if not motions:raise ValueError('P0_INX_NO_ACTIVE_EDITABLE_MOTION')
        motion=motions[0]
        witness=patch_motion(original,output,motion=int(motion['index']),repeat=int(motion['repeat'])^1)
    else:
        dest,evidence=writer.generate('smb',root,path,output.parent)
        output=dest
        witness=evidence
        if witness.get('status')!='PASS' or not witness.get('allowed_offsets_only',True):
            raise ValueError('P0_NATIVE_WRITER_REJECTED')
    data=output.read_bytes()
    if sha(data)==sha(original.read_bytes()): raise ValueError('P0_BINARY_CANDIDATE_UNCHANGED')
    report={'format':FORMAT,'asset':path,'source':str(original),'source_sha256':bridge._hash_file(original),
            'candidate':str(output),'candidate_sha256':sha(data),'writer_evidence':witness,
            'writer_status':'PASS','reader_status':'NOT_RUN','probe_only':True,'game_assets_modified':False,
            'runtime_status':'NOT_CERTIFIED','status':'READY_FOR_NATIVE_READER'}
    if execute:
        result=bridge._run_game_tool(root,bridge._csproj(root,'inspect'),[str(output)],build=build)
        report['reader_result']=result
        report['reader_status']='READER_ACCEPTED' if result['exit_code']==0 and sha(output.read_bytes())==report['candidate_sha256'] else 'READER_REJECTED'
        report['status']='PASS_BINARY_WRITER_READER_NOT_RUNTIME_CERTIFIED' if report['reader_status']=='READER_ACCEPTED' else 'FAILED_NATIVE_READER'
    report['report_file']=bridge._write_report('writer_probes',report)
    return report


def run(a: Any)->int:
    res=probe(bridge._game_root(a),a.asset,bridge._work_root(),execute=a.execute,build=a.build,material=a.material)
    bridge._print(res)
    return 3 if res['status']=='FAILED_NATIVE_READER' else 0



def author(root: pathlib.Path, path: str, work: pathlib.Path, *, execute: bool=False, build: bool=False,
           material: int=0, self_illum: float | None=None, motion: str | None=None,
           repeat: int | None=None, bone: str | None=None, track: str | None=None,
           key_index: int=0, x: float | None=None, y: float | None=None,
           z: float | None=None, w: float | None=None)->dict:
    """Manually requested scalar edits; no implicit test/probe modifications."""
    if build and not execute:raise ValueError('BUILD_REQUIRES_EXECUTE')
    rel=pathlib.PurePosixPath(path)
    if not path or rel.is_absolute() or '..' in rel.parts or '\\' in path or rel.suffix.lower() not in ('.smd','.smb','.inx'):
        raise ValueError('P0_BINARY_ASSET_MUST_BE_RELATIVE_SMD_SMB_INX')
    src=bridge._input_path(root,path,None,{rel.suffix.lower()})
    out=work/'p0_binary'/uuid.uuid4().hex/('authored-'+src.name)
    out.parent.mkdir(parents=True,exist_ok=False)
    suffix=rel.suffix.lower()
    if suffix=='.smd':
        if self_illum is None or motion is not None or bone is not None or any(v is not None for v in (x,y,z,w,repeat)):
            raise ValueError('P0_SMD_EDIT_REQUIRES_ONLY_SELF_ILLUM')
        evidence=patch_smd_material(src,out,material,self_illum)
    elif suffix=='.inx':
        if motion is None or repeat is None or self_illum is not None or bone is not None or any(v is not None for v in (x,y,z,w)):
            raise ValueError('P0_INX_EDIT_REQUIRES_MOTION_AND_REPEAT_ONLY')
        from .inx_writer import patch_motion
        evidence=patch_motion(src,out,motion=motion,repeat=repeat)
    else:
        if not bone or not track or all(v is None for v in (x,y,z,w)) or self_illum is not None or motion is not None or repeat is not None:
            raise ValueError('P0_SMB_EDIT_REQUIRES_BONE_TRACK_AND_COMPONENT')
        from .smb_writer import patch_key
        from .runtime_paths import bundle_root
        evidence=patch_key(bundle_root(),src,out,bone=bone,track=track,key_index=key_index,x=x,y=y,z=z,w=w)
    if evidence.get('status')!='PASS' or evidence.get('allowed_offsets_only') is not True:
        raise ValueError('P0_MANUAL_WRITER_NOT_BYTE_SAFE')
    if bridge._hash_file(src)==bridge._hash_file(out):raise ValueError('P0_MANUAL_EDIT_NOOP')
    report={'format':FORMAT,'asset':path,'source':str(src),'source_sha256':bridge._hash_file(src),
            'candidate':str(out),'candidate_sha256':bridge._hash_file(out),
            'writer_evidence':evidence,'writer_status':'PASS',
            'reader_status':'NOT_RUN','probe_only':False,'authoring_intent':'USER_SCALAR_EDIT',
            'game_assets_modified':False,'runtime_status':'NOT_CERTIFIED',
            'status':'READY_FOR_NATIVE_READER'}
    if execute:
        result=bridge._run_game_tool(root,bridge._csproj(root,'inspect'),[str(out)],build=build)
        report['reader_result']=result
        report['reader_status']='READER_ACCEPTED' if result['exit_code']==0 and bridge._hash_file(out)==report['candidate_sha256'] else 'READER_REJECTED'
        report['status']='PASS_BINARY_WRITER_READER_NOT_RUNTIME_CERTIFIED' if report['reader_status']=='READER_ACCEPTED' else 'FAILED_NATIVE_READER'
    report['report_file']=bridge._write_report('writer_probes',report)
    return report


def edit_run(a:Any)->int:
    result=author(bridge._game_root(a),a.asset,bridge._work_root(),execute=a.execute,build=a.build,
                  material=a.material,self_illum=a.self_illum,motion=a.motion,repeat=a.repeat,
                  bone=a.bone,track=a.track,key_index=a.key_index,x=a.x,y=a.y,z=a.z,w=a.w)
    bridge._print(result)
    return 3 if result['status']=='FAILED_NATIVE_READER' else 0

def register(sp:Any)->None:
    p=sp.add_parser('p0-binary-probe',help='real SMD/SMB/INX surgical writer + optional C# reader; staging only')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--asset',required=True,help='relative to Etervale assets/')
    p.add_argument('--material',type=int,default=0,help='material ID for SMD-only SelfIllum probe')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--build',action='store_true')
    p.set_defaults(func=run)
    p=sp.add_parser('p0-binary-edit',help='manual SMD/SMB/INX scalar edit, strictly targeted and hash-preserving')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--asset',required=True)
    p.add_argument('--material',type=int,default=0)
    p.add_argument('--self-illum',type=float)
    p.add_argument('--motion',help='INX motion index or unique state')
    p.add_argument('--repeat',type=int)
    p.add_argument('--bone')
    p.add_argument('--track',choices=('pos','rot','scale'))
    p.add_argument('--key-index',type=int,default=0)
    for name in ('x','y','z','w'):p.add_argument('--'+name,type=float)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--build',action='store_true')
    p.set_defaults(func=edit_run)
