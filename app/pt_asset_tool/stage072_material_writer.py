from __future__ import annotations

import hashlib
import math
import pathlib
import struct
from typing import Any

from .stage072_corpus import DFILE_HEADER_SIZE, STAGE_HEADER_SIZE, MAT_GROUP_SIZE, MATERIAL_SIZE

FORMAT = "PT_STAGE072_MATERIAL_CANDIDATE_V1"
VERIFY_FORMAT = "PT_STAGE072_MATERIAL_CANDIDATE_VERIFY_V1"
HEADER = b"SMD Stage data Ver 0.72"
FIELDS = {
    "texture_type": (112, "i"),
    "blend_type": (116, "i"),
    "shade": (120, "i"),
    "two_side": (124, "i"),
    "transparency": (144, "f"),
    "self_illum": (148, "f"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def locate_stage_materials(data: bytes) -> dict[str, Any]:
    if len(data) < DFILE_HEADER_SIZE + STAGE_HEADER_SIZE or not data.startswith(HEADER):
        raise ValueError("not SMD Stage data Ver 0.72")
    mat_count = _i32(data, 28)
    mat_file = _i32(data, 32)
    first_obj = _i32(data, 36)
    if mat_count < 0 or not (0 <= mat_file <= first_obj):
        raise ValueError("invalid Stage0.72 material header")
    blob_size = first_obj - mat_file
    start = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE
    end = start + blob_size
    if end > len(data):
        raise ValueError("Stage0.72 material blob beyond EOF")
    if mat_count == 0:
        if start != end:
            raise ValueError("zero materials with non-empty material blob")
        return {"material_count":0,"material_start":start,"material_end":end,"materials":[]}
    if start + MAT_GROUP_SIZE > end or _i32(data, start + 8) != mat_count:
        raise ValueError("Stage0.72 material group mismatch")
    cursor = start + MAT_GROUP_SIZE
    rows=[]
    for idx in range(mat_count):
        raw_start=cursor; raw_end=raw_start+MATERIAL_SIZE
        if raw_end > end:
            raise ValueError(f"Stage0.72 material {idx} truncated")
        in_use=_i32(data,raw_start)
        texture_count=_i32(data,raw_start+4)
        anim_count=_i32(data,raw_start+304)
        if not 0 <= texture_count <= 8 or not 0 <= anim_count <= 32:
            raise ValueError(f"Stage0.72 material {idx} counters out of range")
        values={name:struct.unpack_from("<"+fmt,data,raw_start+off)[0] for name,(off,fmt) in FIELDS.items()}
        cursor=raw_end
        string_start=string_end=cursor
        if in_use:
            if cursor+4 > end: raise ValueError(f"Stage0.72 material {idx} missing string length")
            strlen=_i32(data,cursor)
            if strlen < 0 or cursor+4+strlen > end: raise ValueError(f"Stage0.72 material {idx} invalid string length")
            string_start=cursor; cursor += 4+strlen; string_end=cursor
        rows.append({"index":idx,"raw_start":raw_start,"raw_end":raw_end,"in_use":bool(in_use),"string_start":string_start,"string_end":string_end,"values":values})
    if cursor != end:
        raise ValueError(f"Stage0.72 material region did not close: {cursor}/{end}")
    return {"material_count":mat_count,"material_start":start,"material_end":end,"materials":rows}


def _value(name: str, value: Any) -> int | float:
    if name not in FIELDS: raise ValueError(f"unsupported Stage0.72 material field: {name}")
    _off,fmt=FIELDS[name]
    if fmt == "i":
        v=int(value)
        if not -(2**31) <= v < 2**31: raise ValueError(f"{name} out of int32 range")
        if name == "two_side" and v not in (0,1): raise ValueError("two_side must be 0 or 1")
        return v
    v=float(value)
    if not math.isfinite(v): raise ValueError(f"{name} must be finite")
    if name == "transparency" and not 0.0 <= v <= 1.0: raise ValueError("transparency must be within 0..1")
    return v


def rebuild_stage_material_fields(source: pathlib.Path | str | bytes, *, material_index: int, edits: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if isinstance(source,(str,pathlib.Path)):
        path=pathlib.Path(source).resolve(); before=path.read_bytes()
    else:
        path=None; before=bytes(source)
    layout=locate_stage_materials(before); idx=int(material_index)
    if not 0 <= idx < int(layout["material_count"]): raise IndexError(f"material_index={idx}")
    if not edits: raise ValueError("material edits must not be empty")
    row=layout["materials"][idx]; out=bytearray(before); changed=[]
    for name,raw_value in edits.items():
        value=_value(str(name),raw_value); off,fmt=FIELDS[str(name)]; absolute=int(row["raw_start"])+off
        old=struct.unpack_from("<"+fmt,before,absolute)[0]
        struct.pack_into("<"+fmt,out,absolute,value)
        new=struct.unpack_from("<"+fmt,out,absolute)[0]
        changed.append({"field":str(name),"offset":absolute,"before":old,"after":new,"byte_size":4})
    rebuilt=bytes(out)
    return rebuilt,{"format":FORMAT,"status":"PASS","source":str(path) if path else None,"source_sha256":_sha(before),"output_sha256":_sha(rebuilt),"material_index":idx,"edits":changed,"edit_observed":rebuilt!=before,"file_size_preserved":len(before)==len(rebuilt),"candidate_only":True,"production_authorized":False,"client_write_authorized":False,"client_modified":False}


def verify_stage_material_candidate(source: pathlib.Path | str | bytes, output: pathlib.Path | str | bytes, *, material_index: int, edits: dict[str, Any]) -> dict[str, Any]:
    def rb(x): return pathlib.Path(x).read_bytes() if isinstance(x,(str,pathlib.Path)) else bytes(x)
    before=rb(source); after=rb(output); errors=[]
    try:
        src=locate_stage_materials(before); dst=locate_stage_materials(after)
    except Exception as exc:
        return {"format":VERIFY_FORMAT,"status":"FAIL","errors":[f"PARSE:{type(exc).__name__}:{exc}"],"production_authorized":False,"client_write_authorized":False,"client_modified":False}
    if len(before)!=len(after): errors.append("FILE_SIZE")
    if src["material_count"]!=dst["material_count"]: errors.append("MATERIAL_COUNT")
    idx=int(material_index); allowed=set(); expected={}
    if not 0 <= idx < len(src["materials"]): errors.append("MATERIAL_INDEX")
    else:
        row=src["materials"][idx]
        for name,raw_value in edits.items():
            value=_value(str(name),raw_value); off,fmt=FIELDS[str(name)]; absolute=int(row["raw_start"])+off
            allowed.update(range(absolute,absolute+4)); expected[str(name)]=value
            actual=struct.unpack_from("<"+fmt,after,absolute)[0]
            if fmt=='f':
                if abs(float(actual)-float(value))>1e-6: errors.append(f"FIELD_VALUE:{name}")
            elif int(actual)!=int(value): errors.append(f"FIELD_VALUE:{name}")
    diff=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
    outside=[i for i in diff if i not in allowed]
    if outside: errors.append("BYTES_OUTSIDE_AUTHORIZED_FIELDS")
    if before==after: errors.append("EDIT_NOT_OBSERVED")
    return {"format":VERIFY_FORMAT,"status":"PASS" if not errors else "FAIL","material_index":idx,"expected":expected,"diff_byte_count":len(diff),"diff_outside_authorized_fields":outside,"errors":errors,"candidate_only":True,"production_authorized":False,"client_write_authorized":False,"client_modified":False}
