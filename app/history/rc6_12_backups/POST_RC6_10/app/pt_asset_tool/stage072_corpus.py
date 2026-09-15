from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import struct
import zipfile

from .utils import norm_path

HEADER = b"SMD Stage data Ver 0.72"
DFILE_HEADER_SIZE = 556
STAGE_HEADER_SIZE = 262260
MAP_SIZE = 256
STAGE_AREA_PTR_OFFSET = 4
STAGE_AREA_PTR_COUNT = MAP_SIZE * MAP_SIZE

MAT_GROUP_SIZE = 88
MATERIAL_SIZE = 320
STAGE_VERTEX_SIZE = 28
STAGE_FACE_SIZE = 28
TEXLINK_SIZE = 32
LIGHT_SIZE = 28

# 32-bit smSTAGE3D offsets, proven from smStage3d.h field order.
S_AREA_LIST = 262148
S_AREA_LIST_CNT = 262152
S_MEM_MODE = 262156
S_SUM_COUNT = 262160
S_CALC_SUM_COUNT = 262164
S_VERTEX_PTR = 262168
S_FACE_PTR = 262172
S_TEXLINK_PTR = 262176
S_LIGHT_PTR = 262180
S_MATERIAL_GROUP_PTR = 262184
S_STAGE_OBJECT_PTR = 262188
S_MATERIAL_PTR = 262192
S_NVERTEX = 262196
S_NFACE = 262200
S_NTEXLINK = 262204
S_NLIGHT = 262208
S_NVERTCOLOR = 262212
S_CONTRAST = 262216
S_BRIGHT = 262220
S_VECTLIGHT = 262224
S_AREA_BUFF_PTR = 262236
S_WAREA_SIZE = 262240
S_STAGE_MAP_RECT = 262244

# smMATERIAL fields shared by Model0.62 and Stage0.72.
FORM_NAMES = {
    0: "FS_NONE", 1: "FS_FORMX", 2: "FS_FORMY", 3: "FS_FORMZ",
    4: "FS_SCROLL", 5: "FS_REFLEX", 6: "FS_SCROLL2", 7: "FS_SCROLL3",
    8: "FS_SCROLL4", 9: "FS_SCROLL5", 10: "FS_SCROLL6", 11: "FS_SCROLL7",
    12: "FS_SCROLL8", 13: "FS_SCROLL9", 14: "FS_SCROLL10",
    15: "FS_SCROLLSLOW1", 16: "FS_SCROLLSLOW2", 17: "FS_SCROLLSLOW3", 18: "FS_SCROLLSLOW4",
}
STAGE_OP_NAMES = {
    0: "DEFAULT", 1: "D3DTOP_DISABLE", 2: "D3DTOP_SELECTARG1", 3: "D3DTOP_SELECTARG2",
    4: "D3DTOP_MODULATE", 5: "D3DTOP_MODULATE2X", 6: "D3DTOP_MODULATE4X",
    7: "D3DTOP_ADD", 8: "D3DTOP_ADDSIGNED", 9: "D3DTOP_ADDSIGNED2X", 10: "D3DTOP_SUBTRACT",
}


def _i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin1", "replace")


def _split_nul_strings(block: bytes) -> list[str]:
    parts = block.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    return [x.decode("latin1", "replace") for x in parts]


def _parse_material_region(data: bytes, *, mat_count: int, start: int, end: int) -> list[dict]:
    if not (0 <= start <= end <= len(data)):
        raise ValueError(f"invalid material region {start}:{end}")
    if mat_count == 0:
        if start != end:
            raise ValueError(f"zero materials but material blob has {end-start} bytes")
        return []
    if start + MAT_GROUP_SIZE > end:
        raise ValueError("material group truncated")
    if _i32(data, start + 8) != mat_count:
        raise ValueError(f"material count mismatch: header={mat_count} group={_i32(data,start+8)}")

    cursor = start + MAT_GROUP_SIZE
    out = []
    for mid in range(mat_count):
        mend = cursor + MATERIAL_SIZE
        if mend > end:
            raise ValueError(f"material {mid} block truncated")
        raw = data[cursor:mend]
        tc = _i32(raw, 4)
        ac = _i32(raw, 304)
        if not 0 <= tc <= 8 or not 0 <= ac <= 32:
            raise ValueError(f"material {mid}: invalid texture counters {tc}/{ac}")
        row = {
            "id": mid,
            "InUse": _i32(raw, 0),
            "TextureCounter": tc,
            "TextureStageState": [_i32(raw, 40 + 4*i) for i in range(8)],
            "TextureFormState": [_i32(raw, 72 + 4*i) for i in range(8)],
            "ReformTexture": _i32(raw, 104),
            "TextureType": _i32(raw, 112),
            "BlendType": _i32(raw, 116),
            "Shade": _i32(raw, 120),
            "TwoSide": _i32(raw, 124),
            "Transparency": struct.unpack_from("<f", raw, 144)[0],
            "SelfIllum": struct.unpack_from("<f", raw, 148)[0],
            "UseState": _i32(raw, 164),
            "AnimTexCounter": ac,
            "textures": [],
            "anim_textures": [],
        }
        cursor = mend
        if row["InUse"]:
            if cursor + 4 > end:
                raise ValueError(f"material {mid}: missing string length")
            strlen = _i32(data, cursor)
            cursor += 4
            if strlen < 0 or cursor + strlen > end:
                raise ValueError(f"material {mid}: invalid string length {strlen}")
            strings = _split_nul_strings(data[cursor:cursor+strlen])
            cursor += strlen
            expected = 2 * (tc + ac)
            if len(strings) != expected:
                raise ValueError(f"material {mid}: string count {len(strings)} != {expected}")
            k = 0
            for _ in range(tc):
                row["textures"].append({"Name": strings[k], "NameA": strings[k+1]})
                k += 2
            for _ in range(ac):
                row["anim_textures"].append({"Name": strings[k], "NameA": strings[k+1]})
                k += 2
        out.append(row)
    if cursor != end:
        raise ValueError(f"material region did not close: {cursor} != {end}")
    return out


def _ptr_index(ptr: int, base: int, count: int, stride: int, what: str) -> int:
    if ptr == 0:
        return -1
    if base == 0:
        raise ValueError(f"{what}: nonzero pointer with zero serialized base")
    delta = int(ptr) - int(base)
    if delta < 0 or delta % stride:
        raise ValueError(f"{what}: invalid pointer 0x{ptr:08X} base=0x{base:08X}")
    idx = delta // stride
    if not 0 <= idx < count:
        raise ValueError(f"{what}: pointer index {idx} outside 0..{count-1}")
    return idx


def _parse_area_payload(data: bytes, start: int, stage_ptrs: list[int], nface: int, w_area_size: int, *, width: int) -> dict:
    if width not in (2, 4):
        raise ValueError(width)
    cursor = start
    cells = 0
    slots = 0
    refs = 0
    errors = []
    max_slen = 0
    for y in range(MAP_SIZE):
        for x in range(MAP_SIZE):
            if stage_ptrs[x * MAP_SIZE + y] == 0:
                continue
            cells += 1
            if cursor + 4 > len(data):
                errors.append(f"cell {x},{y}: missing slen")
                return {"ok": False, "errors": errors, "cursor": cursor, "cells": cells, "slots": slots, "refs": refs}
            slen = _i32(data, cursor)
            cursor += 4
            if slen < 1 or slen > max(1, w_area_size + 1):
                errors.append(f"cell {x},{y}: invalid slen={slen}")
                return {"ok": False, "errors": errors, "cursor": cursor, "cells": cells, "slots": slots, "refs": refs}
            max_slen = max(max_slen, slen)
            need = slen * width
            if cursor + need > len(data):
                errors.append(f"cell {x},{y}: truncated payload slen={slen} width={width}")
                return {"ok": False, "errors": errors, "cursor": cursor, "cells": cells, "slots": slots, "refs": refs}
            if width == 2:
                vals = list(struct.unpack_from(f"<{slen}H", data, cursor))
            else:
                vals = list(struct.unpack_from(f"<{slen}I", data, cursor))
            cursor += need
            slots += slen
            declared = vals[0]
            if declared != slen - 1:
                errors.append(f"cell {x},{y}: first={declared} != slen-1={slen-1}")
                if len(errors) >= 8:
                    return {"ok": False, "errors": errors, "cursor": cursor, "cells": cells, "slots": slots, "refs": refs}
            for fi in vals[1:]:
                refs += 1
                if not 0 <= fi < nface:
                    errors.append(f"cell {x},{y}: face={fi} outside 0..{nface-1}")
                    if len(errors) >= 8:
                        return {"ok": False, "errors": errors, "cursor": cursor, "cells": cells, "slots": slots, "refs": refs}
    # Runtime LoadFile allocates DWORD[wAreaSize] and advances wbCnt by slen.
    # It requires only that the consumed slot count fit the capacity; shipped
    # files legitimately leave slack in wAreaSize. Equality is not a format
    # invariant.
    if slots > w_area_size:
        errors.append(f"area slots {slots} exceed wAreaSize capacity {w_area_size}")
    return {
        "ok": not errors,
        "errors": errors,
        "cursor": cursor,
        "cells": cells,
        "slots": slots,
        "refs": refs,
        "max_slen": max_slen,
        "capacity": w_area_size,
        "capacity_slack_slots": w_area_size - slots,
        "trailing_bytes": len(data) - cursor,
    }


def parse_stage072(path: pathlib.Path, *, include_payload: bool = False) -> dict:
    p = pathlib.Path(path)
    data = p.read_bytes()
    min_head = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE
    if len(data) < min_head:
        raise ValueError(f"Stage0.72 file too small: {len(data)} < {min_head}")
    if not data.startswith(HEADER):
        raise ValueError("not SMD Stage data Ver 0.72")

    file_header = {
        "ObjCounter_raw": _i32(data, 24),
        "MatCounter": _i32(data, 28),
        "MatFilePoint": _i32(data, 32),
        "First_ObjInfoPoint": _i32(data, 36),
        "TmFrameCounter_raw": _i32(data, 40),
    }
    mat_count = file_header["MatCounter"]
    mat_file = file_header["MatFilePoint"]
    first_obj = file_header["First_ObjInfoPoint"]
    if mat_count < 0 or mat_count > 100000:
        raise ValueError(f"invalid MatCounter={mat_count}")
    if not (0 <= mat_file <= first_obj):
        raise ValueError(f"invalid legacy material offsets {mat_file}:{first_obj}")
    # SaveFile computes these offsets as if the raw smSTAGE3D header were not
    # present, then physically writes smSTAGE3D before the material group.
    # The material blob length remains exact: First_ObjInfoPoint-MatFilePoint.
    material_blob_size = first_obj - mat_file

    sh = DFILE_HEADER_SIZE
    stage = data[sh:sh+STAGE_HEADER_SIZE]
    nvertex = _i32(stage, S_NVERTEX)
    nface = _i32(stage, S_NFACE)
    ntex = _i32(stage, S_NTEXLINK)
    nlight = _i32(stage, S_NLIGHT)
    w_area_size = _i32(stage, S_WAREA_SIZE)
    for name, value, cap in (
        ("nVertex", nvertex, 5_000_000), ("nFace", nface, 5_000_000),
        ("nTexLink", ntex, 20_000_000), ("nLight", nlight, 1_000_000),
        ("wAreaSize", w_area_size, 50_000_000),
    ):
        if value < 0 or value > cap:
            raise ValueError(f"invalid {name}={value}")

    stage_ptrs = list(struct.unpack_from(f"<{STAGE_AREA_PTR_COUNT}I", stage, STAGE_AREA_PTR_OFFSET))
    active_area_cells = sum(1 for x in stage_ptrs if x)
    tex_runtime_base = _u32(stage, S_TEXLINK_PTR)
    material_runtime_base = _u32(stage, S_MATERIAL_PTR)

    mat_start = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE
    mat_end = mat_start + material_blob_size
    if mat_end > len(data):
        raise ValueError(f"material blob beyond EOF: {mat_end}>{len(data)}")
    materials = _parse_material_region(data, mat_count=mat_count, start=mat_start, end=mat_end)

    vertex_base = mat_end
    face_base = vertex_base + nvertex * STAGE_VERTEX_SIZE
    tex_base = face_base + nface * STAGE_FACE_SIZE
    light_base = tex_base + ntex * TEXLINK_SIZE
    area_base = light_base + nlight * LIGHT_SIZE
    if area_base > len(data):
        raise ValueError(f"fixed payload beyond EOF: {area_base}>{len(data)}")

    custom_color_vertices = 0
    vertex_payload = [] if include_payload else None
    min_xyz = [None, None, None]
    max_xyz = [None, None, None]
    for vi in range(nvertex):
        o = vertex_base + vi * STAGE_VERTEX_SIZE
        x, y, z = struct.unpack_from("<iii", data, o + 8)
        cols = struct.unpack_from("<4h", data, o + 20)
        if include_payload:
            vertex_payload.append({"x": x, "y": y, "z": z, "color": list(cols)})
        if cols != (255, 255, 255, 255):
            custom_color_vertices += 1
        for j, v in enumerate((x, y, z)):
            min_xyz[j] = v if min_xyz[j] is None else min(min_xyz[j], v)
            max_xyz[j] = v if max_xyz[j] is None else max(max_xyz[j], v)

    faces = []
    face_payload = [] if include_payload else None
    material_face_counts = collections.Counter()
    first_ptr_errors = []
    invalid_vertex_faces = []
    for fi in range(nface):
        o = face_base + fi * STAGE_FACE_SIZE
        verts4 = struct.unpack_from("<4H", data, o + 8)
        verts = list(verts4[:3])
        mid = int(verts4[3])
        ptr = _u32(data, o + 16)
        badv = [v for v in verts if v >= nvertex]
        if badv:
            invalid_vertex_faces.append({"face": fi, "vertices": verts})
        if not 0 <= mid < mat_count:
            if not (mat_count == 0 and mid == 0):
                raise ValueError(f"face {fi}: material {mid} outside 0..{mat_count-1}")
        material_face_counts[mid] += 1
        try:
            first_idx = _ptr_index(ptr, tex_runtime_base, ntex, TEXLINK_SIZE, f"face {fi} lpTexLink") if ptr else -1
        except ValueError as exc:
            first_ptr_errors.append(str(exc))
            first_idx = -2
        faces.append((verts, mid, ptr, first_idx))
        if include_payload:
            face_payload.append({"vertices": verts, "material": mid, "first_texlink": first_idx, "vect_normal": list(struct.unpack_from("<4h", data, o + 20))})

    texlinks = []
    next_ptr_errors = []
    for ti in range(ntex):
        o = tex_base + ti * TEXLINK_SIZE
        us = struct.unpack_from("<3f", data, o)
        vs = struct.unpack_from("<3f", data, o + 12)
        htex = _u32(data, o + 24)
        nxt = _u32(data, o + 28)
        try:
            next_idx = _ptr_index(nxt, tex_runtime_base, ntex, TEXLINK_SIZE, f"TexLink {ti} NextTex") if nxt else -1
        except ValueError as exc:
            next_ptr_errors.append(str(exc))
            next_idx = -2
        texlinks.append({"u": us, "v": vs, "hTexture": htex, "next_idx": next_idx})

    depth_counts = collections.Counter()
    htexture_mapping_errors = []
    stage_overrun_errors = []
    cycles = []
    textureless_placeholder_faces = 0
    inert_zero_texture_handle_usage = collections.Counter()
    uv_distinct_multilayer_faces = 0
    uv_distinct_stage_pair_faces = collections.Counter()
    multilayer_faces = 0
    max_depth = 0
    stage_state_usage = collections.Counter()
    form_state_usage = collections.Counter()

    face_chains = [[] for _ in faces] if include_payload else None
    for fi, (_verts, mid, ptr, first_idx) in enumerate(faces):
        if first_idx < 0:
            if ptr == 0:
                depth_counts[0] += 1
                continue
            continue
        chain = []
        seen = set()
        ti = first_idx
        while ti >= 0:
            if ti in seen:
                cycles.append({"face": fi, "at": ti})
                break
            if not 0 <= ti < ntex:
                break
            seen.add(ti)
            chain.append(ti)
            ni = texlinks[ti]["next_idx"]
            if ni == -2:
                break
            ti = ni
            if len(chain) > 16:
                cycles.append({"face": fi, "at": ti, "reason": "depth>16"})
                break

        if include_payload:
            face_chains[fi] = list(chain)
        depth = len(chain)
        depth_counts[depth] += 1
        max_depth = max(max_depth, depth)
        if depth > 1:
            multilayer_faces += 1
            for sa in range(depth):
                for sb in range(sa + 1, depth):
                    a, b = texlinks[chain[sa]], texlinks[chain[sb]]
                    distinct = any(
                        abs(a["u"][j]-b["u"][j]) > 1e-7 or
                        abs(a["v"][j]-b["v"][j]) > 1e-7
                        for j in range(3)
                    )
                    if distinct:
                        uv_distinct_stage_pair_faces[(sa, sb)] += 1
                        if sa == 0 and sb == 1:
                            uv_distinct_multilayer_faces += 1

        mat = materials[mid] if 0 <= mid < len(materials) else None
        tc = int(mat.get("TextureCounter") or 0) if mat else 0
        ac = int(mat.get("AnimTexCounter") or 0) if mat else 0

        # Runtime RenderD3D returns before drawing materials with no base or
        # animated textures. Physical Stage0.72 files contain depth-1 TexLinks
        # on such faces in two forms: hTexture=NULL and hTexture pointing at
        # smMaterial[mid].smTexture[0]. Both are inert to the renderer. Keep
        # the acceptance narrow: exactly one link, and only NULL or the exact
        # slot-0 address.
        if mat is not None and tc == 0 and ac == 0 and depth == 1:
            link = texlinks[chain[0]]
            htex = int(link["hTexture"])
            slot0 = (material_runtime_base + mid * MATERIAL_SIZE + 8) & 0xFFFFFFFF
            if htex in (0, slot0):
                textureless_placeholder_faces += 1
                inert_zero_texture_handle_usage["NULL" if htex == 0 else "MATERIAL_SLOT0"] += 1
                continue
            htexture_mapping_errors.append({
                "face": fi, "material": mid, "stage": 0,
                "hTexture": htex, "expected_inert": [0, slot0],
                "reason": "zero-texture material uses unexpected TexLink handle",
            })
            continue

        for stage_idx, link_idx in enumerate(chain):
            link = texlinks[link_idx]
            htex = int(link["hTexture"])
            if mat is None:
                htexture_mapping_errors.append({"face": fi, "material": mid, "stage": stage_idx, "hTexture": htex, "reason": "no material"})
                continue
            if stage_idx >= tc:
                stage_overrun_errors.append({"face": fi, "material": mid, "stage": stage_idx, "TextureCounter": tc, "AnimTexCounter": ac})
                continue
            expected = (material_runtime_base + mid * MATERIAL_SIZE + 8 + stage_idx * 4) & 0xFFFFFFFF
            if htex != expected:
                htexture_mapping_errors.append({
                    "face": fi, "material": mid, "stage": stage_idx,
                    "hTexture": htex, "expected": expected,
                })
            op = int(mat["TextureStageState"][stage_idx])
            form = int(mat["TextureFormState"][stage_idx])
            stage_state_usage[(stage_idx, op)] += 1
            form_state_usage[(stage_idx, form)] += 1

    light_payload = [] if include_payload else None
    if include_payload:
        for li in range(nlight):
            o = light_base + li * LIGHT_SIZE
            ltype, lx, ly, lz, lrange = struct.unpack_from("<5i", data, o)
            lr, lg, lb = struct.unpack_from("<3h", data, o + 20)
            light_payload.append({"type": ltype, "x": lx, "y": ly, "z": lz, "range": lrange, "r": lr, "g": lg, "b": lb})

    area_word = _parse_area_payload(data, area_base, stage_ptrs, nface, w_area_size, width=2)
    area_dword = _parse_area_payload(data, area_base, stage_ptrs, nface, w_area_size, width=4)
    word_valid = bool(area_word.get("ok"))
    dword_valid = bool(area_dword.get("ok"))
    word_closes = word_valid and int(area_word.get("trailing_bytes", -1)) == 0
    dword_closes = dword_valid and int(area_dword.get("trailing_bytes", -1)) == 0
    opaque_trailing_bytes = 0
    if active_area_cells == 0 and w_area_size == 0:
        area_encoding = "NONE"
        opaque_trailing_bytes = max(0, len(data) - area_base)
        area_ok = True
    elif word_closes and not dword_valid:
        area_encoding = "WORD16"
        area_ok = True
    elif dword_closes and not word_valid:
        area_encoding = "DWORD32"
        area_ok = True
    elif word_closes and dword_closes:
        area_encoding = "AMBIGUOUS_BOTH"
        area_ok = True
    elif dword_valid and not word_valid:
        # The runtime consumes exactly the lists referenced by StageArea and
        # closes the file without an EOF check. Three shipped login/select
        # maps carry an opaque suffix after that runtime-consumed core.
        area_encoding = "DWORD32_TRAILING_OPAQUE"
        opaque_trailing_bytes = int(area_dword.get("trailing_bytes") or 0)
        area_ok = opaque_trailing_bytes > 0
    elif word_valid and not dword_valid:
        area_encoding = "WORD16_TRAILING_OPAQUE"
        opaque_trailing_bytes = int(area_word.get("trailing_bytes") or 0)
        area_ok = opaque_trailing_bytes > 0
    else:
        area_encoding = "UNRESOLVED"
        area_ok = False

    pointer_ok = not first_ptr_errors and not next_ptr_errors and not cycles
    geometry_ok = not invalid_vertex_faces
    tex_semantics_ok = not htexture_mapping_errors and not stage_overrun_errors

    flags = []
    if max_depth > 1: flags.append("MULTILAYER")
    else: flags.append("SINGLE_LAYER_OR_NONE")
    if nlight: flags.append("LIGHTS")
    if custom_color_vertices: flags.append("VERTEX_COLOR")
    if textureless_placeholder_faces: flags.append("INERT_ZERO_TEXTURE")
    if uv_distinct_multilayer_faces: flags.append("DISTINCT_UV_STAGE")
    flags.append(f"AREA_{area_encoding}")
    profile = "+".join(flags)

    return {
        "format": "PT_STAGE072_FILE_PARSE_V1",
        "path": str(p),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "file_header": file_header,
        "material_blob_size": material_blob_size,
        "stage_header_size": STAGE_HEADER_SIZE,
        "runtime_pointers": {
            "Vertex": _u32(stage, S_VERTEX_PTR), "Face": _u32(stage, S_FACE_PTR),
            "TexLink": tex_runtime_base, "smLight": _u32(stage, S_LIGHT_PTR),
            "smMaterialGroup": _u32(stage, S_MATERIAL_GROUP_PTR),
            "StageObject": _u32(stage, S_STAGE_OBJECT_PTR), "smMaterial": material_runtime_base,
            "lpwAreaBuff": _u32(stage, S_AREA_BUFF_PTR),
        },
        "counts": {
            "materials": mat_count, "vertices": nvertex, "faces": nface,
            "texlinks": ntex, "lights": nlight, "nVertColor": _i32(stage, S_NVERTCOLOR),
            "active_area_cells": active_area_cells, "wAreaSize": w_area_size,
        },
        "lighting": {
            "Contrast": _i32(stage, S_CONTRAST), "Bright": _i32(stage, S_BRIGHT),
            "VectLight": list(struct.unpack_from("<3i", stage, S_VECTLIGHT)),
        },
        "stage_map_rect": list(struct.unpack_from("<4i", stage, S_STAGE_MAP_RECT)),
        "bbox_fixed": {"min": min_xyz, "max": max_xyz},
        "custom_vertex_color_vertices": custom_color_vertices,
        "material_face_counts": {str(k): v for k, v in sorted(material_face_counts.items())},
        "texlink_depth_face_counts": {str(k): v for k, v in sorted(depth_counts.items())},
        "max_texlink_depth": max_depth,
        "multilayer_faces": multilayer_faces,
        "uv_distinct_multilayer_faces": uv_distinct_multilayer_faces,
        "uv_distinct_stage_pair_faces": {
            f"{a}-{b}": n for (a, b), n in sorted(uv_distinct_stage_pair_faces.items())
        },
        "textureless_placeholder_faces": textureless_placeholder_faces,
        "inert_zero_texture_texlink_faces": textureless_placeholder_faces,
        "inert_zero_texture_handle_usage": dict(sorted(inert_zero_texture_handle_usage.items())),
        "stage_state_usage": [
            {"stage_index": s, "code": c, "name": STAGE_OP_NAMES.get(c, f"UNKNOWN_{c}"), "face_uses": n}
            for (s, c), n in sorted(stage_state_usage.items())
        ],
        "form_state_usage": [
            {"stage_index": s, "code": c, "name": FORM_NAMES.get(c, f"UNKNOWN_{c}"), "face_uses": n}
            for (s, c), n in sorted(form_state_usage.items())
        ],
        "errors": {
            "invalid_vertex_faces": invalid_vertex_faces[:20],
            "first_texlink_pointer": first_ptr_errors[:20],
            "next_texlink_pointer": next_ptr_errors[:20],
            "cycles": cycles[:20],
            "htexture_mapping": htexture_mapping_errors[:20],
            "stage_overrun": stage_overrun_errors[:20],
        },
        "area": {
            "encoding": area_encoding,
            "ok": area_ok,
            "word16": area_word,
            "dword32": area_dword,
            "payload_offset": area_base,
            "opaque_trailing_bytes": opaque_trailing_bytes,
        },
        "checks": {
            "geometry": "PASS" if geometry_ok else "FAIL",
            "texlink_pointers": "PASS" if pointer_ok else "FAIL",
            "htexture_stage_mapping": "PASS" if tex_semantics_ok else "FAIL",
            "area_payload": "PASS" if area_ok else "FAIL",
        },
        "profile": profile,
        "full_parse": "PASS" if geometry_ok and pointer_ok and tex_semantics_ok and area_ok else "FAIL",
        "materials": materials,
        "payload": ({
            "vertices": vertex_payload,
            "faces": [dict(face_payload[i], texlink_chain=face_chains[i]) for i in range(len(face_payload))],
            "texlinks": texlinks,
            "lights": light_payload,
        } if include_payload else None),
    }


def _candidate_rows(records: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    for r in records:
        if str(r.get("kind") or "") != "SMD_STAGE_072":
            continue
        rel = norm_path(r.get("relative_path") or r.get("path") or "")
        if not rel or rel.lower() in seen:
            continue
        seen.add(rel.lower())
        rows.append({"relative_path": rel, "record": r})
    rows.sort(key=lambda x: x["relative_path"].lower())
    return rows


def _choose_representatives(rows: list[dict], per_profile: int) -> list[dict]:
    good = [r for r in rows if r.get("full_parse") == "PASS"]
    chosen: dict[str, dict] = {}
    by_profile: dict[str, list[dict]] = collections.defaultdict(list)
    for r in good:
        by_profile[r.get("profile") or "UNKNOWN"].append(r)
    for profile, rs in sorted(by_profile.items()):
        rs.sort(key=lambda x: (x.get("size", 0), x.get("relative_path", "").lower()))
        picks = []
        if rs:
            picks.append(rs[0])
        if len(rs) > 1 and per_profile > 1:
            picks.append(rs[-1])
        for x in rs[1:-1][:max(0, per_profile-len(picks))]:
            picks.append(x)
        for x in picks:
            chosen[x["relative_path"].lower()] = x

    # Always include capability/extreme witnesses if they exist.
    selectors = [
        lambda r: r.get("counts", {}).get("faces", 0),
        lambda r: r.get("counts", {}).get("vertices", 0),
        lambda r: r.get("counts", {}).get("materials", 0),
        lambda r: r.get("max_texlink_depth", 0),
        lambda r: r.get("counts", {}).get("lights", 0),
        lambda r: r.get("custom_vertex_color_vertices", 0),
        lambda r: r.get("textureless_placeholder_faces", 0),
        lambda r: r.get("uv_distinct_multilayer_faces", 0),
    ]
    for f in selectors:
        if good:
            x = max(good, key=lambda r: (f(r), r.get("size", 0)))
            if f(x) > 0:
                chosen[x["relative_path"].lower()] = x
    # Format-boundary witnesses are mandatory even when they parse cleanly.
    for r in good:
        enc = (r.get("area") or {}).get("encoding")
        if int(r.get("max_texlink_depth") or 0) >= 3:
            chosen[r["relative_path"].lower()] = r
        if enc not in ("DWORD32", "NONE"):
            chosen[r["relative_path"].lower()] = r
        if int((r.get("area") or {}).get("opaque_trailing_bytes") or 0) > 0:
            chosen[r["relative_path"].lower()] = r
        if int(r.get("inert_zero_texture_texlink_faces") or 0) > 0:
            chosen[r["relative_path"].lower()] = r

    # Parse failures are mandatory evidence.
    for r in rows:
        if r.get("full_parse") != "PASS":
            chosen[r["relative_path"].lower()] = r
    return sorted(chosen.values(), key=lambda x: x["relative_path"].lower())


def audit_stage072_physical_corpus(records: list[dict], resolver, *, bundle: str | None = None, per_profile: int = 2) -> dict:
    candidates = _candidate_rows(records)
    rows = []
    scan_errors = []
    for item in candidates:
        rel = item["relative_path"]
        try:
            physical = resolver.resolve(rel)
            parsed = parse_stage072(physical)
            row = {"relative_path": rel, **{k: v for k, v in parsed.items() if k not in {"path", "materials", "payload"}}}
            row["material_texture_counts"] = [int(m.get("TextureCounter") or 0) for m in parsed.get("materials", [])]
            rows.append(row)
        except Exception as exc:
            scan_errors.append({"relative_path": rel, "error": f"{type(exc).__name__}: {exc}"})
            rows.append({"relative_path": rel, "full_parse": "FAIL", "profile": "PARSE_FAILURE", "error": f"{type(exc).__name__}: {exc}"})

    full_pass = sum(r.get("full_parse") == "PASS" for r in rows)
    profile_counts = collections.Counter(r.get("profile") or "UNKNOWN" for r in rows)
    depth_file_counts = collections.Counter(str(r.get("max_texlink_depth", -1)) for r in rows if r.get("full_parse") == "PASS")
    area_encoding_counts = collections.Counter(r.get("area", {}).get("encoding", "UNKNOWN") for r in rows if r.get("full_parse") == "PASS")
    stage_state_totals = collections.Counter()
    form_state_totals = collections.Counter()
    for r in rows:
        for x in r.get("stage_state_usage") or []:
            stage_state_totals[(int(x.get("stage_index") or 0), int(x.get("code") or 0), str(x.get("name") or ""))] += int(x.get("face_uses") or 0)
        for x in r.get("form_state_usage") or []:
            form_state_totals[(int(x.get("stage_index") or 0), int(x.get("code") or 0), str(x.get("name") or ""))] += int(x.get("face_uses") or 0)
    totals = collections.Counter()
    for r in rows:
        c = r.get("counts") or {}
        totals["materials"] += int(c.get("materials") or 0)
        totals["vertices"] += int(c.get("vertices") or 0)
        totals["faces"] += int(c.get("faces") or 0)
        totals["texlinks"] += int(c.get("texlinks") or 0)
        totals["lights"] += int(c.get("lights") or 0)
        totals["active_area_cells"] += int(c.get("active_area_cells") or 0)
        totals["wAreaSize"] += int(c.get("wAreaSize") or 0)
        totals["multilayer_faces"] += int(r.get("multilayer_faces") or 0)
        totals["uv_distinct_multilayer_faces"] += int(r.get("uv_distinct_multilayer_faces") or 0)
        totals["custom_vertex_color_vertices"] += int(r.get("custom_vertex_color_vertices") or 0)
        totals["textureless_placeholder_faces"] += int(r.get("textureless_placeholder_faces") or 0)
        totals["inert_zero_texture_texlink_faces"] += int(r.get("inert_zero_texture_texlink_faces") or 0)
        totals["opaque_trailing_bytes"] += int((r.get("area") or {}).get("opaque_trailing_bytes") or 0)

    reps = _choose_representatives(rows, max(1, int(per_profile)))
    bundle_path = None
    if bundle:
        bp = pathlib.Path(bundle).expanduser()
        if not bp.is_absolute():
            bp = pathlib.Path.cwd() / bp
        bp = bp.resolve(); bp.parent.mkdir(parents=True, exist_ok=True)
        manifest = []
        with zipfile.ZipFile(bp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for r in reps:
                rel = r["relative_path"]
                physical = resolver.resolve(rel, required=False)
                if physical is None:
                    continue
                zf.write(physical, arcname=f"client/{rel}")
                manifest.append({
                    "relative_path": rel, "profile": r.get("profile"), "full_parse": r.get("full_parse"),
                    "size": r.get("size"), "sha256": r.get("sha256"), "counts": r.get("counts"),
                    "max_texlink_depth": r.get("max_texlink_depth"), "area_encoding": (r.get("area") or {}).get("encoding"),
                })
            zf.writestr("STAGE072_REPRESENTATIVES.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        bundle_path = str(bp)

    structural_fail_files = sum(r.get("full_parse") != "PASS" for r in rows)
    expected = len(candidates)
    audited = len(rows)
    status = "PASS" if expected == audited and expected > 0 and not scan_errors and structural_fail_files == 0 else "FAIL"
    complete_candidate = bool(status == "PASS" and expected == 63 and full_pass == 63)

    result = {
        "format": "PT_STAGE072_PHYSICAL_CORPUS_AUDIT_V1",
        "status": status,
        "candidate_files_expected": expected,
        "physical_files_audited": audited,
        "full_parse_pass_files": full_pass,
        "structural_fail_files": structural_fail_files,
        "scan_errors": scan_errors,
        "profile_file_counts": dict(sorted(profile_counts.items())),
        "max_texlink_depth_file_counts": dict(sorted(depth_file_counts.items())),
        "area_encoding_file_counts": dict(sorted(area_encoding_counts.items())),
        "stage_state_usage": [
            {"stage_index": st, "code": code, "name": name, "face_uses": count}
            for (st, code, name), count in sorted(stage_state_totals.items())
        ],
        "form_state_usage": [
            {"stage_index": st, "code": code, "name": name, "face_uses": count}
            for (st, code, name), count in sorted(form_state_totals.items())
        ],
        "max_texlink_depth": max([int(r.get("max_texlink_depth") or 0) for r in rows] or [0]),
        "files_with_depth3": sum(int(r.get("max_texlink_depth") or 0) >= 3 for r in rows),
        "files_with_opaque_trailing": sum(int((r.get("area") or {}).get("opaque_trailing_bytes") or 0) > 0 for r in rows),
        "files_with_multilayer": sum(int(r.get("max_texlink_depth") or 0) > 1 for r in rows),
        "files_with_lights": sum(int((r.get("counts") or {}).get("lights") or 0) > 0 for r in rows),
        "files_with_custom_vertex_colors": sum(int(r.get("custom_vertex_color_vertices") or 0) > 0 for r in rows),
        "files_with_textureless_placeholders": sum(int(r.get("textureless_placeholder_faces") or 0) > 0 for r in rows),
        "files_with_distinct_multilayer_uv": sum(int(r.get("uv_distinct_multilayer_faces") or 0) > 0 for r in rows),
        "totals": dict(totals),
        "representatives": [r["relative_path"] for r in reps],
        "stage072_physical_complete_candidate": complete_candidate,
        "sourcecode_serialization_notes": {
            "header": "SMD Stage data Ver 0.72",
            "serialized_smSTAGE3D_size_32bit": STAGE_HEADER_SIZE,
            "smSTAGE3D_size_derivation": "4-byte Head + 65536 32-bit StageArea pointers + remaining 32-bit fields + POINT3D + RECT = 262260 bytes",
            "zero_texture_render_rule": "RenderD3D returns before drawing when TextureCounter==0 and AnimTexCounter==0",
            "stage_area_save_payload": "SaveFile source writes slen DWORD then slen WORD entries",
            "runtime_area_load_payload": "LoadFile reads slen DWORD then slen DWORD entries and uses wAreaSize as allocation capacity",
            "physical_area_policy": "accept the encoding proven by valid referenced cells; wAreaSize is a capacity upper bound; preserve any runtime-ignored trailing suffix byte-identically",
        },
        "bundle": bundle_path,
        "rows": rows,
    }
    return result
