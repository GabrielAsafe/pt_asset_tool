#!/usr/bin/env python3
"""
PT Pikeman SMD Material Audit V1

Read-only decoder for the serialized smMATERIAL_GROUP in SMD Model 0.62.

ABI/source facts used:
  sizeof(smDFILE_HEADER)   = 556
  sizeof(smMATERIAL_GROUP) = 88
  sizeof(smMATERIAL)       = 320

smDFILE_HEADER:
  char szHeader[24]         @ 0
  int ObjCounter            @ 24
  int MatCounter            @ 28
  int MatFilePoint          @ 32
  int First_ObjInfoPoint    @ 36
  int TmFrameCounter        @ 40

smMATERIAL_GROUP:
  MaterialCount @ 8
  ReformTexture @ 12
  MaxMaterial @ 16
  LastSearchMaterial @ 20
  szLastSearchName[64] @ 24

smMATERIAL offsets:
  InUse 0
  TextureCounter 4
  smTexture[8] 8                 (historic pointers; not used as filenames)
  TextureStageState[8] 40
  TextureFormState[8] 72
  ReformTexture 104
  MapOpacity 108
  TextureType 112
  BlendType 116
  Shade 120
  TwoSide 124
  SerialNum 128
  Diffuse[12 raw bytes] 132
  Transparency 144
  SelfIllum 148
  TextureSwap 152
  MatFrame 156
  TextureClip 160
  UseState 164
  MeshState 168
  WindMeshBottom 172
  smAnimTexture[32] 176          (historic pointers)
  AnimTexCounter 304
  FrameMask 308
  Shift_FrameSpeed 312
  AnimationFrame 316

For each InUse material, SaveFile serializes:
  int StrLen
  string_block[StrLen]
where string_block contains Name\0 NameA\0 pairs for TextureCounter,
followed by Name\0 NameA\0 pairs for AnimTexCounter.

No client file is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import struct


HEADER_SIZE = 556
MAT_GROUP_SIZE = 88
MATERIAL_SIZE = 320


def sha256_file(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def i32(data, off):
    return struct.unpack_from("<i", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def f32(data, off):
    return struct.unpack_from("<f", data, off)[0]


def cstr_fixed(data, off, n):
    raw = data[off:off+n].split(b"\0", 1)[0]
    return raw.decode("latin1", "replace")


def split_nul_strings(block):
    # Preserve empty NameA strings; terminal NUL does not create an extra field.
    parts = block.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    return [p.decode("latin1", "replace") for p in parts]


def decode_expected_cstrings(block, expected_count, *, allow_final_length_delimited=False):
    """Decode declared Name/NameA fields, preserving a narrow legacy final-field form.

    Normal fields remain NUL-terminated and only NUL padding may follow.  When
    explicitly enabled, the *last* declared field may consume the remaining
    StrLen-bounded bytes without a terminal NUL.  Material serialization is
    Name/NameA pairs, so this can only relax the final NameA field; it never
    invents bytes or repairs/truncates the primary runtime texture Name.
    """
    out=[]; pos=0; expected=int(expected_count)
    for idx in range(expected):
        end=block.find(b"\0",pos)
        if end < 0:
            if allow_final_length_delimited and idx == expected - 1 and pos < len(block):
                out.append(block[pos:].decode("latin1","replace"))
                pos=len(block)
                break
            raise ValueError("unterminated serialized material string")
        out.append(block[pos:end].decode("latin1","replace"))
        pos=end+1
    trailing=block[pos:]
    if any(x != 0 for x in trailing):
        raise ValueError(
            f"serialized material string block has non-NUL suffix: consumed={pos} size={len(block)}"
        )
    return out, len(trailing)


def parse_material(raw, mat_id):
    if len(raw) != MATERIAL_SIZE:
        raise ValueError("bad material block size")

    tc = i32(raw, 4)
    ac = i32(raw, 304)
    if not 0 <= tc <= 8:
        raise ValueError(f"material {mat_id}: TextureCounter={tc} outside 0..8")
    if not 0 <= ac <= 32:
        raise ValueError(f"material {mat_id}: AnimTexCounter={ac} outside 0..32")

    return {
        "id": mat_id,
        "InUse": i32(raw, 0),
        "TextureCounter": tc,
        "historic_smTexture_ptrs": [u32(raw, 8 + 4*i) for i in range(8)],
        "TextureStageState": [i32(raw, 40 + 4*i) for i in range(8)],
        "TextureFormState": [i32(raw, 72 + 4*i) for i in range(8)],
        "ReformTexture": i32(raw, 104),
        "MapOpacity_raw_i32": i32(raw, 108),
        "MapOpacity_raw_f32": f32(raw, 108),
        "TextureType": i32(raw, 112),
        "BlendType": i32(raw, 116),
        "Shade": i32(raw, 120),
        "TwoSide": i32(raw, 124),
        "SerialNum": i32(raw, 128),
        "Diffuse_raw_hex": raw[132:144].hex(),
        "Diffuse_as_3f_diagnostic": list(struct.unpack_from("<3f", raw, 132)),
        "Transparency_raw_i32": i32(raw, 144),
        "Transparency_raw_f32": f32(raw, 144),
        "SelfIllum_raw_i32": i32(raw, 148),
        "SelfIllum_raw_f32": f32(raw, 148),
        "TextureSwap": i32(raw, 152),
        "MatFrame": i32(raw, 156),
        "TextureClip": i32(raw, 160),
        "UseState": i32(raw, 164),
        "MeshState": i32(raw, 168),
        "WindMeshBottom": i32(raw, 172),
        "historic_smAnimTexture_ptrs": [u32(raw, 176 + 4*i) for i in range(32)],
        "AnimTexCounter": ac,
        "FrameMask": i32(raw, 308),
        "Shift_FrameSpeed": i32(raw, 312),
        "AnimationFrame": i32(raw, 316),
        "textures": [],
        "anim_textures": [],
        "StrLen": None,
        "string_block_hex": None,
    }


def parse_smd(path):
    p = pathlib.Path(path).expanduser().resolve()
    data = p.read_bytes()

    if len(data) < HEADER_SIZE:
        raise ValueError(f"{p}: too small for smDFILE_HEADER")

    header = cstr_fixed(data, 0, 24)
    if not header.startswith("SMD Model data Ver 0.62"):
        raise ValueError(f"{p}: unexpected header {header!r}")

    obj_count = i32(data, 24)
    mat_count = i32(data, 28)
    mat_file_point = i32(data, 32)
    first_obj_info = i32(data, 36)
    tm_frame_count = i32(data, 40)

    if obj_count < 0 or mat_count < 0:
        raise ValueError("negative object/material count")
    if not HEADER_SIZE <= mat_file_point <= len(data):
        raise ValueError(f"MatFilePoint out of range: {mat_file_point}")
    if not mat_file_point <= first_obj_info <= len(data):
        raise ValueError(f"First_ObjInfoPoint out of range: {first_obj_info}")

    if mat_count == 0:
        if mat_file_point != first_obj_info:
            raise ValueError("zero materials but non-empty material region")
        materials = []
        group = None
        cursor = mat_file_point
    else:
        if mat_file_point + MAT_GROUP_SIZE > first_obj_info:
            raise ValueError("material group header overruns material region")

        g = data[mat_file_point:mat_file_point+MAT_GROUP_SIZE]
        group_count = i32(g, 8)
        if group_count != mat_count:
            raise ValueError(
                f"MaterialCount mismatch: group={group_count} header={mat_count}"
            )

        group = {
            "MaterialCount": group_count,
            "ReformTexture": i32(g, 12),
            "MaxMaterial": i32(g, 16),
            "LastSearchMaterial": i32(g, 20),
            "szLastSearchName": cstr_fixed(g, 24, 64),
            "historic_smMaterial_ptr": u32(g, 4),
        }

        cursor = mat_file_point + MAT_GROUP_SIZE
        materials = []
        for mat_id in range(mat_count):
            end = cursor + MATERIAL_SIZE
            if end > first_obj_info:
                raise ValueError(f"material {mat_id} fixed block overruns region")
            mat = parse_material(data[cursor:end], mat_id)
            cursor = end

            if mat["InUse"]:
                if cursor + 4 > first_obj_info:
                    raise ValueError(f"material {mat_id}: missing StrLen")
                strlen = i32(data, cursor)
                cursor += 4
                if strlen < 0 or cursor + strlen > first_obj_info:
                    raise ValueError(
                        f"material {mat_id}: invalid StrLen={strlen}"
                    )
                block = data[cursor:cursor+strlen]
                cursor += strlen

                expected = 2 * (mat["TextureCounter"] + mat["AnimTexCounter"])
                final_length_delimited = bool(expected and not block.endswith(b"\0"))
                strings, nul_padding = decode_expected_cstrings(
                    block, expected, allow_final_length_delimited=True
                )

                mat["StrLen"] = strlen
                mat["string_block_hex"] = block.hex()
                mat["string_nul_padding_bytes"] = nul_padding
                mat["legacy_final_namea_length_delimited"] = final_length_delimited

                k = 0
                for _ in range(mat["TextureCounter"]):
                    mat["textures"].append({
                        "Name": strings[k],
                        "NameA": strings[k+1],
                    })
                    k += 2
                for _ in range(mat["AnimTexCounter"]):
                    mat["anim_textures"].append({
                        "Name": strings[k],
                        "NameA": strings[k+1],
                    })
                    k += 2

            materials.append(mat)

    if cursor != first_obj_info:
        raise ValueError(
            f"material region did not close exactly: cursor={cursor} "
            f"First_ObjInfoPoint={first_obj_info} remaining={first_obj_info-cursor}"
        )

    return {
        "path": str(p),
        "size": len(data),
        "sha256": sha256_file(p),
        "header": header,
        "ObjCounter": obj_count,
        "MatCounter": mat_count,
        "MatFilePoint": mat_file_point,
        "First_ObjInfoPoint": first_obj_info,
        "TmFrameCounter": tm_frame_count,
        "material_region_size": first_obj_info - mat_file_point,
        "material_group": group,
        "materials": materials,
        "material_cursor": cursor,
        "remaining_material_bytes": first_obj_info - cursor,
        "material_region_end_check": "PASS",
    }


def compact_material(m):
    return {
        "id": m["id"],
        "InUse": m["InUse"],
        "TextureCounter": m["TextureCounter"],
        "textures": m["textures"],
        "AnimTexCounter": m["AnimTexCounter"],
        "anim_textures": m["anim_textures"],
        "TextureStageState": m["TextureStageState"],
        "TextureFormState": m["TextureFormState"],
        "ReformTexture": m["ReformTexture"],
        "MapOpacity_raw_i32": m["MapOpacity_raw_i32"],
        "MapOpacity_raw_f32": m["MapOpacity_raw_f32"],
        "TextureType": m["TextureType"],
        "BlendType": m["BlendType"],
        "Shade": m["Shade"],
        "TwoSide": m["TwoSide"],
        "Diffuse_raw_hex": m["Diffuse_raw_hex"],
        "Diffuse_as_3f_diagnostic": m["Diffuse_as_3f_diagnostic"],
        "Transparency_raw_i32": m["Transparency_raw_i32"],
        "Transparency_raw_f32": m["Transparency_raw_f32"],
        "SelfIllum_raw_i32": m["SelfIllum_raw_i32"],
        "SelfIllum_raw_f32": m["SelfIllum_raw_f32"],
        "TextureSwap": m["TextureSwap"],
        "MatFrame": m["MatFrame"],
        "TextureClip": m["TextureClip"],
        "UseState": m["UseState"],
        "MeshState": m["MeshState"],
        "WindMeshBottom": m["WindMeshBottom"],
        "FrameMask": m["FrameMask"],
        "Shift_FrameSpeed": m["Shift_FrameSpeed"],
        "AnimationFrame": m["AnimationFrame"],
        "StrLen": m["StrLen"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smd", action="append", required=True)
    ap.add_argument("--report", default="logs/pikeman_smd_material_audit_v1.json")
    args = ap.parse_args()

    decoded = [parse_smd(x) for x in args.smd]

    result = {
        "tool": "PT_PIKEMAN_SMD_MATERIAL_AUDIT_V1",
        "abi": {
            "smDFILE_HEADER": HEADER_SIZE,
            "smMATERIAL_GROUP": MAT_GROUP_SIZE,
            "smMATERIAL": MATERIAL_SIZE,
            "pointer_size": 4,
        },
        "models": decoded,
        "client_modified": False,
        "material_audit_check": "PASS",
    }

    rp = pathlib.Path(args.report).expanduser()
    if not rp.is_absolute():
        rp = pathlib.Path.cwd() / rp
    rp = rp.resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("PT_PIKEMAN_SMD_MATERIAL_AUDIT_V1")
    for model in decoded:
        print(f"MODEL {pathlib.Path(model['path']).name}")
        print(f"  sha256={model['sha256']}")
        print(f"  objects={model['ObjCounter']}")
        print(f"  materials={model['MatCounter']}")
        print(f"  material_region_size={model['material_region_size']}")
        print(f"  material_region_end_check={model['material_region_end_check']}")
        if model["material_group"]:
            print(f"  group.ReformTexture={model['material_group']['ReformTexture']}")
        for m in model["materials"]:
            c = compact_material(m)
            print(f"  MATERIAL {c['id']}")
            print(f"    InUse={c['InUse']}")
            print(f"    TextureCounter={c['TextureCounter']}")
            print(f"    textures={c['textures']}")
            print(f"    AnimTexCounter={c['AnimTexCounter']}")
            print(f"    anim_textures={c['anim_textures']}")
            print(f"    TextureStageState={c['TextureStageState']}")
            print(f"    TextureFormState={c['TextureFormState']}")
            print(
                f"    ReformTexture={c['ReformTexture']} "
                f"TextureType={c['TextureType']} "
                f"BlendType={c['BlendType']} "
                f"Shade={c['Shade']} TwoSide={c['TwoSide']}"
            )
            print(
                f"    MapOpacity_raw_i32={c['MapOpacity_raw_i32']} "
                f"Transparency_raw_i32={c['Transparency_raw_i32']} "
                f"SelfIllum_raw_i32={c['SelfIllum_raw_i32']}"
            )
            print(f"    Diffuse_raw_hex={c['Diffuse_raw_hex']}")
            print(
                f"    TextureSwap={c['TextureSwap']} MatFrame={c['MatFrame']} "
                f"TextureClip={c['TextureClip']} UseState={c['UseState']} "
                f"MeshState={c['MeshState']} WindMeshBottom={c['WindMeshBottom']}"
            )
            print(
                f"    FrameMask={c['FrameMask']} "
                f"Shift_FrameSpeed={c['Shift_FrameSpeed']} "
                f"AnimationFrame={c['AnimationFrame']}"
            )
    print(f"report={rp}")
    print("client_modified=False")
    print("material_audit_check=PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"material_audit_check=FAIL: {type(exc).__name__}: {exc}")
        raise
