from __future__ import annotations

import json
import pathlib
import struct
from typing import Any

from .mixed_authoring_candidate import analyze_mixed_source, validate_mixed_candidate_output
from .static_roundtrip import _parse as parse_model062_bytes

FORMAT = "PT_MIXED_PHYSIQUE_SYNTHETIC_DEVTEST_V1"
SH, SI, SO, SV, SF, ST = 556, 40, 2236, 24, 36, 32


def _object_block(name: str, *, physique: bool) -> bytes:
    nv, nf, nt = 3, 1, 1
    length = SO + nv * SV + nf * SF + nt * ST + (nv * 32 if physique else 0)
    b = bytearray(length); texbase = 0x100000
    struct.pack_into('<I', b, 12, texbase)
    struct.pack_into('<I', b, 16, 1 if physique else 0)
    struct.pack_into('<iii', b, 84, nv, nf, nt)
    b[172:172+len(name)] = name.encode('ascii')
    vo = SO
    for i, xyz in enumerate(((0,0,0),(256,0,0),(0,256,0))):
        struct.pack_into('<6i', b, vo+i*SV, *(xyz+(0,0,256)))
    fo = vo + nv*SV
    struct.pack_into('<4H', b, fo, 0,1,2,0); struct.pack_into('<I', b, fo+32, texbase)
    to = fo + SF
    struct.pack_into('<3f', b, to, 0.0,1.0,0.0); struct.pack_into('<3f', b, to+12, 0.0,0.0,1.0)
    struct.pack_into('<I', b, to+28, 0)
    return bytes(b)


def _write_mixed(path: pathlib.Path) -> pathlib.Path:
    blocks=[('rigid',_object_block('rigid',physique=True)),('static',_object_block('static',physique=False)),('untouched',_object_block('untouched',physique=False))]
    first=SH+len(blocks)*SI; total=first+sum(len(x[1]) for x in blocks)
    out=bytearray(total); out[:23]=b'SMD Model data Ver 0.62'
    struct.pack_into('<i',out,24,len(blocks)); struct.pack_into('<i',out,28,0)
    struct.pack_into('<i',out,32,first); struct.pack_into('<i',out,36,first)
    cur=first
    for i,(name,block) in enumerate(blocks):
        info=SH+i*SI; out[info:info+len(name)]=name.encode('ascii')
        struct.pack_into('<i',out,info+32,len(block)); struct.pack_into('<i',out,info+36,cur)
        out[cur:cur+len(block)]=block; cur+=len(block)
    path.write_bytes(out); return path


def _edit_vertex(path: pathlib.Path, object_name: str, component: int, delta: int) -> None:
    data=bytearray(path.read_bytes()); parsed=parse_model062_bytes(bytes(data)); obj=parsed['objects'][object_name]
    off=int(obj['vertex_offset'])+int(component)*4
    old=struct.unpack_from('<i',data,off)[0]; struct.pack_into('<i',data,off,old+int(delta)); path.write_bytes(data)


def run_mixed_physique_synthetic_devtest(project_root) -> dict[str, Any]:
    root=pathlib.Path(project_root).resolve()
    work=root/'pt_build'/'devtest'/'release_1_auto'/'mixed_synthetic'
    work.mkdir(parents=True,exist_ok=True)
    source=_write_mixed(work/'source_mixed.smd')
    candidate=work/'candidate_mixed.smd'; candidate.write_bytes(source.read_bytes())
    analysis=analyze_mixed_source(source)
    _edit_vertex(candidate,'rigid',0,1)
    _edit_vertex(candidate,'static',1,2)
    verification=validate_mixed_candidate_output(source,candidate,target_objects=['rigid','static'])
    status='PASS' if (
        analysis.get('status')=='PASS' and analysis.get('mode')=='MIXED'
        and verification.get('status')=='PASS'
        and verification.get('all_target_edits_observed') is True
        and verification.get('non_target_changed')==[]
        and verification.get('mixed_modes_preserved') is True
    ) else 'FAIL'
    result={
        'format':FORMAT,'status':status,'source':str(source),'candidate':str(candidate),
        'analysis':analysis,'verification':verification,
        'scope':'SYNTHETIC_CONTAINER_AND_COMBINED_ADAPTER_VERIFICATION_ONLY',
        'real_corpus_certified':False,'runtime_authorized':False,'production_authorized':False,
        'client_write_authorized':False,'client_modified':False,
    }
    report=work/'result.json'; result['report']=str(report)
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result
