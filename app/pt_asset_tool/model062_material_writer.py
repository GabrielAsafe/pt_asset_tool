from __future__ import annotations

import hashlib
import math
import pathlib
import struct
from typing import Any

FORMAT = "PT_MODEL062_MATERIAL_CANDIDATE_V1"
VERIFY_FORMAT = "PT_MODEL062_MATERIAL_CANDIDATE_VERIFY_V1"
HEADER = b"SMD Model data Ver 0.62"
SH = 556
SIZE_MATERIAL_GROUP = 88
MG_OFF_MATERIAL_COUNT = 8
SIZE_MATERIAL = 320
FIELDS = {
    "texture_type": (112, "I"),
    "blend_type": (116, "I"),
    "shade": (120, "I"),
    "two_side": (124, "I"),
    "transparency": (144, "f"),
    "self_illum": (148, "f"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def locate_materials(data: bytes) -> dict[str, Any]:
    if len(data) < SH or not data.startswith(HEADER):
        raise ValueError("not SMD Model data Ver 0.62")
    mat_count = _i32(data, 28)
    mat_point = _i32(data, 32)
    first_obj = _i32(data, 36)
    if mat_count < 0 or mat_point < SH or first_obj < mat_point + SIZE_MATERIAL_GROUP or first_obj > len(data):
        raise ValueError("invalid material region bounds")
    group_count = _u32(data, mat_point + MG_OFF_MATERIAL_COUNT)
    if group_count != mat_count:
        raise ValueError(f"material group count mismatch: {group_count}/{mat_count}")
    cursor = mat_point + SIZE_MATERIAL_GROUP
    rows=[]
    for idx in range(mat_count):
        raw_start=cursor; raw_end=raw_start+SIZE_MATERIAL
        if raw_end > first_obj: raise ValueError(f"material {idx} truncated")
        in_use=_u32(data,raw_start)
        texture_counter=_u32(data,raw_start+4)
        anim_count=_u32(data,raw_start+304)
        if texture_counter > 8 or anim_count > 32: raise ValueError(f"material {idx} counters out of range")
        cursor=raw_end
        string_start=string_end=cursor
        strlen=0
        if in_use:
            if cursor+4 > first_obj: raise ValueError(f"material {idx} missing string length")
            strlen=_i32(data,cursor); string_start=cursor
            if strlen < 0 or cursor+4+strlen > first_obj: raise ValueError(f"material {idx} invalid string length")
            cursor += 4+strlen; string_end=cursor
        values={}
        for name,(off,fmt) in FIELDS.items():
            values[name]=struct.unpack_from("<"+fmt,data,raw_start+off)[0]
        rows.append({
            "index":idx,"raw_start":raw_start,"raw_end":raw_end,"in_use":bool(in_use),
            "string_start":string_start,"string_end":string_end,"string_length":strlen,
            "values":values,
        })
    if cursor != first_obj:
        raise ValueError(f"material region did not close: {cursor}/{first_obj}")
    return {"material_count":mat_count,"mat_point":mat_point,"first_obj":first_obj,"materials":rows}


def _normalized_value(name: str, value: Any) -> int | float:
    if name not in FIELDS: raise ValueError(f"unsupported material field: {name}")
    _off,fmt=FIELDS[name]
    if fmt == "I":
        v=int(value)
        if not 0 <= v <= 0xFFFFFFFF: raise ValueError(f"{name} out of uint32 range")
        if name == "two_side" and v not in (0,1): raise ValueError("two_side must be 0 or 1")
        return v
    v=float(value)
    if not math.isfinite(v): raise ValueError(f"{name} must be finite")
    if name == "transparency" and not 0.0 <= v <= 1.0: raise ValueError("transparency must be within 0..1")
    return v


def rebuild_material_fields(source: pathlib.Path | str | bytes, *, material_index: int, edits: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if isinstance(source,(str,pathlib.Path)):
        source_path=pathlib.Path(source).resolve(); before=source_path.read_bytes()
    else:
        source_path=None; before=bytes(source)
    layout=locate_materials(before)
    idx=int(material_index)
    if not 0 <= idx < int(layout["material_count"]): raise IndexError(f"material_index={idx}")
    if not edits: raise ValueError("material edits must not be empty")
    row=layout["materials"][idx]; out=bytearray(before); changed=[]
    for name,value in edits.items():
        value=_normalized_value(str(name),value); off,fmt=FIELDS[str(name)]; absolute=int(row["raw_start"])+off
        old=struct.unpack_from("<"+fmt,before,absolute)[0]
        struct.pack_into("<"+fmt,out,absolute,value)
        new=struct.unpack_from("<"+fmt,out,absolute)[0]
        changed.append({"field":str(name),"offset":absolute,"before":old,"after":new,"byte_size":4})
    rebuilt=bytes(out)
    report={
        "format":FORMAT,"status":"PASS","source":str(source_path) if source_path else None,
        "source_sha256":_sha(before),"output_sha256":_sha(rebuilt),"material_index":idx,
        "edits":changed,"edit_observed":rebuilt!=before,"file_size_preserved":len(rebuilt)==len(before),
        "candidate_only":True,"production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
    return rebuilt,report


def verify_material_candidate(source: pathlib.Path | str | bytes, output: pathlib.Path | str | bytes, *, material_index: int, edits: dict[str, Any]) -> dict[str, Any]:
    def rb(x):
        return pathlib.Path(x).read_bytes() if isinstance(x,(str,pathlib.Path)) else bytes(x)
    before=rb(source); after=rb(output); errors=[]
    try:
        src=locate_materials(before); dst=locate_materials(after)
    except Exception as exc:
        return {"format":VERIFY_FORMAT,"status":"FAIL","errors":[f"PARSE:{type(exc).__name__}:{exc}"],"production_authorized":False,"client_write_authorized":False,"client_modified":False}
    if len(before)!=len(after): errors.append("FILE_SIZE")
    if src["material_count"]!=dst["material_count"]: errors.append("MATERIAL_COUNT")
    idx=int(material_index)
    if not 0<=idx<len(src["materials"]): errors.append("MATERIAL_INDEX")
    allowed=set(); expected={}
    if not errors:
        row=src["materials"][idx]
        for name,value in edits.items():
            value=_normalized_value(str(name),value); off,fmt=FIELDS[str(name)]; absolute=int(row["raw_start"])+off
            allowed.update(range(absolute,absolute+4)); expected[str(name)]=value
            actual=struct.unpack_from("<"+fmt,after,absolute)[0]
            if fmt=='f':
                if abs(float(actual)-float(value))>1e-6: errors.append(f"FIELD_VALUE:{name}")
            elif int(actual)!=int(value): errors.append(f"FIELD_VALUE:{name}")
    diff=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
    outside=[i for i in diff if i not in allowed]
    if outside: errors.append("BYTES_OUTSIDE_AUTHORIZED_FIELDS")
    if before==after: errors.append("EDIT_NOT_OBSERVED")
    return {
        "format":VERIFY_FORMAT,"status":"PASS" if not errors else "FAIL","material_index":idx,
        "expected":expected,"diff_byte_count":len(diff),"diff_outside_authorized_fields":outside,
        "errors":errors,"candidate_only":True,"production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
