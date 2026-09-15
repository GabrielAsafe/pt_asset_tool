#!/usr/bin/env python3
# Priston Tale proprietary SMD Model data Ver 0.62 -> Blender
# V2: reconstruct Physique mesh into bind pose using bone.Tm from companion SMB.
# V1 scope:
#   - read-only on source/client assets
#   - geometry
#   - material IDs
#   - runtime UV -> Blender UV origin conversion
#   - serialized texture filenames
#   - protected 14-byte-prefixed BMP decoding to an external cache
#   - rigid Physique names -> Blender vertex groups weight 1.0
#   - saves a .blend
#
# Not V1:
#   - runtime armature / linked M5Bip skeleton
#   - animation
#   - exact smOBJ3D transform evaluation
#   - multi-layer material rendering (MfbC01 has exactly one TexLink per face)

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path, PureWindowsPath

try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None


SMD_HEADER_TEXT = b"SMD Model data Ver 0.62"

SIZE_DFILE_HEADER = 556
SIZE_DFILE_OBJINFO = 40

SIZE_MATERIAL_GROUP = 88
SIZE_MATERIAL = 320

SIZE_OBJ3D = 2236
SIZE_VERTEX = 24
SIZE_FACE = 36
SIZE_TEXLINK = 32
SIZE_TM_ROT = 20
SIZE_TM_POS = 16
SIZE_TM_SCALE = 16
SIZE_MATRIX = 64

MG_OFF_MATERIAL_COUNT = 8

M_OFF_INUSE = 0
M_OFF_TEXTURE_COUNTER = 4
M_OFF_TEXTURE_TYPE = 112
M_OFF_BLEND_TYPE = 116
M_OFF_SHADE = 120
M_OFF_TWO_SIDE = 124
M_OFF_TRANSPARENCY = 144
M_OFF_SELF_ILLUM = 148
M_OFF_ANIM_TEX_COUNTER = 304

O_OFF_TEXLINK_PTR = 12
O_OFF_PHYSIQUE_PTR = 16
O_OFF_NVERTEX = 84
O_OFF_NFACE = 88
O_OFF_NTEXLINK = 92
O_OFF_NODENAME = 172
O_OFF_NODEPARENT = 204
O_OFF_TM = 240
O_OFF_TMROTCNT = 684
O_OFF_TMPOSCNT = 688
O_OFF_TMSCALECNT = 692

BLEND_NAMES = {
    0: "NONE",
    1: "ALPHA",
    2: "COLOR",
    3: "SHADOW",
    4: "LAMP",
    5: "ADDCOLOR",
    6: "INVSHADOW",
}


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def i32(data, off):
    return struct.unpack_from("<i", data, off)[0]


def f32(data, off):
    return struct.unpack_from("<f", data, off)[0]


def cstr(raw):
    return raw.split(b"\0", 1)[0].decode("latin-1", errors="replace")


def decode_cstrings(block, expected_count):
    out = []
    pos = 0
    for _ in range(expected_count):
        end = block.find(b"\0", pos)
        if end < 0:
            raise ValueError("unterminated serialized material string")
        out.append(block[pos:end].decode("latin-1", errors="replace"))
        pos = end + 1
    if pos != len(block):
        # A small subset of physical Model0.62 files pads the serialized
        # string region with one or more NUL bytes.  Accept only pure NUL
        # padding; any non-zero suffix remains ambiguous and fail-closed.
        trailing = block[pos:]
        if not trailing or any(b != 0 for b in trailing):
            raise ValueError(
                f"serialized material string block mismatch: consumed={pos} size={len(block)}"
            )
    return out


def ptr_to_tex_index(ptr, old_base, count):
    if ptr == 0:
        return None
    if old_base == 0 or ptr < old_base:
        raise ValueError(
            f"invalid serialized TexLink pointer 0x{ptr:08X}, base=0x{old_base:08X}"
        )
    delta = ptr - old_base
    if delta % SIZE_TEXLINK:
        raise ValueError(
            f"unaligned TexLink pointer delta={delta}, stride={SIZE_TEXLINK}"
        )
    idx = delta // SIZE_TEXLINK
    if idx >= count:
        raise ValueError(f"TexLink index out of range: {idx}/{count}")
    return idx


def parse_header_and_infos(data):
    if len(data) < SIZE_DFILE_HEADER:
        raise ValueError("file smaller than smDFILE_HEADER")
    header = data[:SIZE_DFILE_HEADER]
    if not header.startswith(SMD_HEADER_TEXT):
        raise ValueError(f"unexpected SMD header: {cstr(header[:24])!r}")

    obj_counter = i32(header, 24)
    mat_counter = i32(header, 28)
    mat_file_point = i32(header, 32)
    first_obj_point = i32(header, 36)

    if not (0 <= obj_counter <= 128):
        raise ValueError(f"implausible ObjCounter={obj_counter}")
    if not (0 <= mat_counter <= 4096):
        raise ValueError(f"implausible MatCounter={mat_counter}")
    if not (SIZE_DFILE_HEADER <= mat_file_point <= first_obj_point <= len(data)):
        raise ValueError("invalid material/object region offsets")

    infos = []
    table_start = SIZE_DFILE_HEADER
    table_end = table_start + obj_counter * SIZE_DFILE_OBJINFO
    if table_end != mat_file_point:
        raise ValueError(
            f"object table end {table_end} != MatFilePoint {mat_file_point}"
        )

    for i in range(obj_counter):
        off = table_start + i * SIZE_DFILE_OBJINFO
        raw = data[off:off + SIZE_DFILE_OBJINFO]
        infos.append({
            "index": i,
            "name": cstr(raw[:32]),
            "length": i32(raw, 32),
            "start": i32(raw, 36),
        })

    return {
        "obj_counter": obj_counter,
        "mat_counter": mat_counter,
        "mat_file_point": mat_file_point,
        "first_obj_point": first_obj_point,
        "infos": infos,
    }


def parse_materials(data, meta):
    start = meta["mat_file_point"]
    end = meta["first_obj_point"]

    group = data[start:start + SIZE_MATERIAL_GROUP]
    if len(group) != SIZE_MATERIAL_GROUP:
        raise ValueError("truncated smMATERIAL_GROUP")

    material_count = u32(group, MG_OFF_MATERIAL_COUNT)
    if material_count != meta["mat_counter"]:
        raise ValueError(
            f"MaterialCount {material_count} != header MatCounter {meta['mat_counter']}"
        )

    cursor = start + SIZE_MATERIAL_GROUP
    materials = []

    for idx in range(material_count):
        raw = data[cursor:cursor + SIZE_MATERIAL]
        if len(raw) != SIZE_MATERIAL:
            raise ValueError(f"truncated smMATERIAL[{idx}]")
        cursor += SIZE_MATERIAL

        in_use = u32(raw, M_OFF_INUSE)
        texture_counter = u32(raw, M_OFF_TEXTURE_COUNTER)
        texture_type = u32(raw, M_OFF_TEXTURE_TYPE)
        blend_type = u32(raw, M_OFF_BLEND_TYPE)
        shade = u32(raw, M_OFF_SHADE)
        two_side = u32(raw, M_OFF_TWO_SIDE)
        transparency = f32(raw, M_OFF_TRANSPARENCY)
        self_illum = f32(raw, M_OFF_SELF_ILLUM)
        anim_count = u32(raw, M_OFF_ANIM_TEX_COUNTER)

        if texture_counter > 8:
            raise ValueError(f"material {idx}: TextureCounter={texture_counter} > 8")
        if anim_count > 32:
            raise ValueError(f"material {idx}: AnimTexCounter={anim_count} > 32")

        textures = []
        anim_textures = []

        if in_use:
            if cursor + 4 > end:
                raise ValueError(f"material {idx}: missing StrLen")
            strlen = i32(data, cursor)
            cursor += 4
            if strlen < 0 or cursor + strlen > end:
                raise ValueError(f"material {idx}: invalid StrLen={strlen}")

            block = data[cursor:cursor + strlen]
            cursor += strlen
            strings = decode_cstrings(
                block, 2 * (texture_counter + anim_count)
            )

            p = 0
            for _ in range(texture_counter):
                textures.append((strings[p], strings[p + 1]))
                p += 2
            for _ in range(anim_count):
                anim_textures.append((strings[p], strings[p + 1]))
                p += 2

        materials.append({
            "index": idx,
            "in_use": in_use,
            "texture_counter": texture_counter,
            "texture_type": texture_type,
            "blend_type": blend_type,
            "shade": shade,
            "two_side": two_side,
            "transparency": transparency,
            "self_illum": self_illum,
            "anim_count": anim_count,
            "textures": textures,
            "anim_textures": anim_textures,
        })

    if cursor != end:
        raise ValueError(
            f"material region did not close: cursor={cursor}, expected={end}"
        )

    return materials


def object_layout(obj_start, nv, nf, nt, nr, np, ns, has_physique):
    vertices = obj_start + SIZE_OBJ3D
    faces = vertices + SIZE_VERTEX * nv
    texlinks = faces + SIZE_FACE * nf
    tmrot = texlinks + SIZE_TEXLINK * nt
    tmpos = tmrot + SIZE_TM_ROT * nr
    tmscale = tmpos + SIZE_TM_POS * np
    prevrot = tmscale + SIZE_TM_SCALE * ns
    physique = prevrot + SIZE_MATRIX * nr if has_physique else None
    end = physique + 32 * nv if has_physique else prevrot + SIZE_MATRIX * nr
    return {
        "vertices": vertices,
        "faces": faces,
        "texlinks": texlinks,
        "physique": physique,
        "end": end,
    }


def parse_objects(data, meta):
    objects = []

    for info in meta["infos"]:
        start = info["start"]
        raw = data[start:start + SIZE_OBJ3D]
        if len(raw) != SIZE_OBJ3D:
            raise ValueError(f"{info['name']}: truncated smOBJ3D")

        old_tex_base = u32(raw, O_OFF_TEXLINK_PTR)
        physique_ptr = u32(raw, O_OFF_PHYSIQUE_PTR)

        nv = i32(raw, O_OFF_NVERTEX)
        nf = i32(raw, O_OFF_NFACE)
        nt = i32(raw, O_OFF_NTEXLINK)
        nr = i32(raw, O_OFF_TMROTCNT)
        np = i32(raw, O_OFF_TMPOSCNT)
        ns = i32(raw, O_OFF_TMSCALECNT)

        node_name = cstr(raw[O_OFF_NODENAME:O_OFF_NODENAME + 32])
        node_parent = cstr(raw[O_OFF_NODEPARENT:O_OFF_NODEPARENT + 32])

        if min(nv, nf, nt, nr, np, ns) < 0:
            raise ValueError(f"{node_name}: negative serialized count")

        has_physique = physique_ptr != 0
        layout = object_layout(start, nv, nf, nt, nr, np, ns, has_physique)

        if layout["end"] != start + info["length"]:
            raise ValueError(
                f"{node_name}: length mismatch "
                f"{layout['end'] - start} != {info['length']}"
            )

        vertices = []
        raw_vertices = []
        for i in range(nv):
            off = layout["vertices"] + i * SIZE_VERTEX
            x, y, z, nx, ny, nz = struct.unpack_from("<6i", data, off)
            raw_vertices.append((x, y, z))
            vertices.append((x / 256.0, y / 256.0, z / 256.0))

        texlinks = []
        for i in range(nt):
            off = layout["texlinks"] + i * SIZE_TEXLINK
            u = struct.unpack_from("<3f", data, off)
            v = struct.unpack_from("<3f", data, off + 12)
            htexture = u32(data, off + 24)
            next_ptr = u32(data, off + 28)
            texlinks.append({
                "u": u,
                "v": v,
                "htexture": htexture,
                "next_ptr": next_ptr,
            })

        faces = []
        for i in range(nf):
            off = layout["faces"] + i * SIZE_FACE
            a, b, c, mat = struct.unpack_from("<4H", data, off)
            if a >= nv or b >= nv or c >= nv:
                raise ValueError(f"{node_name}: invalid face vertex at {i}")
            if mat >= meta["mat_counter"]:
                raise ValueError(f"{node_name}: invalid material ID {mat}")

            face_ptr = u32(data, off + 32)
            first = ptr_to_tex_index(face_ptr, old_tex_base, nt)

            chain = []
            seen = set()
            cur = first
            while cur is not None:
                if cur in seen:
                    raise ValueError(f"{node_name}: TexLink loop at face {i}")
                seen.add(cur)
                chain.append(cur)
                next_ptr = texlinks[cur]["next_ptr"]
                cur = ptr_to_tex_index(next_ptr, old_tex_base, nt) if next_ptr else None
                if len(chain) > 64:
                    raise ValueError(f"{node_name}: unreasonable TexLink chain")

            faces.append({
                "verts": (a, b, c),
                "material": mat,
                "texlinks": chain,
            })

        bones = None
        if has_physique:
            bones = []
            p = layout["physique"]
            for i in range(nv):
                bones.append(cstr(data[p + i * 32:p + (i + 1) * 32]))

        objects.append({
            "name": node_name or info["name"],
            "parent": node_parent,
            "vertices": vertices,
            "raw_vertices": raw_vertices,
            "faces": faces,
            "texlinks": texlinks,
            "bones": bones,
            "has_physique": has_physique,
        })

    return objects



def read_matrix_i32(data, off):
    return list(struct.unpack_from("<16i", data, off))


def matrix_value(m, row, col):
    return m[(row - 1) * 4 + (col - 1)]


def transform_point_fixed(v, m):
    # Exact convention used by ReformPhysique/WorldForm:
    # row-vector style, fixed point with FLOATNS=8.
    x, y, z = v

    rx = (
        x * matrix_value(m, 1, 1)
        + y * matrix_value(m, 2, 1)
        + z * matrix_value(m, 3, 1)
    )
    ry = (
        x * matrix_value(m, 1, 2)
        + y * matrix_value(m, 2, 2)
        + z * matrix_value(m, 3, 2)
    )
    rz = (
        x * matrix_value(m, 1, 3)
        + y * matrix_value(m, 2, 3)
        + z * matrix_value(m, 3, 3)
    )

    return (
        (rx >> 8) + matrix_value(m, 4, 1),
        (ry >> 8) + matrix_value(m, 4, 2),
        (rz >> 8) + matrix_value(m, 4, 3),
    )


def parse_skeleton_tms(data):
    meta = parse_header_and_infos(data)

    if meta["mat_counter"] != 0:
        raise ValueError(
            f"unexpected skeleton MatCounter={meta['mat_counter']}; expected 0"
        )

    bones = {}

    for info in meta["infos"]:
        start = info["start"]
        raw = data[start:start + SIZE_OBJ3D]
        if len(raw) != SIZE_OBJ3D:
            raise ValueError(
                f"skeleton object {info['index']}: truncated smOBJ3D"
            )

        name = cstr(raw[O_OFF_NODENAME:O_OFF_NODENAME + 32])
        parent = cstr(raw[O_OFF_NODEPARENT:O_OFF_NODEPARENT + 32])

        if name != info["name"]:
            raise ValueError(
                f"skeleton object {info['index']}: "
                f"table name {info['name']!r} != NodeName {name!r}"
            )
        tm = read_matrix_i32(raw, O_OFF_TM)
        if name in bones:
            existing = bones[name]
            if existing.get("parent") == parent and tuple(existing.get("tm") or ()) == tuple(tm):
                # Collapse only a semantically identical legacy duplicate.
                continue
            raise ValueError(f"duplicate skeleton NodeName {name!r} with conflicting transform/parent")

        bones[name] = {
            "parent": parent,
            "tm": tm,
            "pos": (
                matrix_value(tm, 4, 1) / 256.0,
                matrix_value(tm, 4, 2) / 256.0,
                matrix_value(tm, 4, 3) / 256.0,
            ),
            "rows": {
                "X": Vector((
                    matrix_value(tm, 1, 1) / 256.0,
                    matrix_value(tm, 1, 2) / 256.0,
                    matrix_value(tm, 1, 3) / 256.0,
                )),
                "Y": Vector((
                    matrix_value(tm, 2, 1) / 256.0,
                    matrix_value(tm, 2, 2) / 256.0,
                    matrix_value(tm, 2, 3) / 256.0,
                )),
                "Z": Vector((
                    matrix_value(tm, 3, 1) / 256.0,
                    matrix_value(tm, 3, 2) / 256.0,
                    matrix_value(tm, 3, 3) / 256.0,
                )),
            },
        }

    return meta, bones


def bbox_points(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (
        min(xs), max(xs),
        min(ys), max(ys),
        min(zs), max(zs),
    )


def reconstruct_bind_pose(objects, bones):
    all_fixed = []
    used_bones = set()

    for obj in objects:
        if obj["bones"] is None:
            continue

        if len(obj["raw_vertices"]) != len(obj["bones"]):
            raise ValueError(
                f"{obj['name']}: vertex/Physique count mismatch"
            )

        reconstructed = []

        for vidx, (local, bone_name) in enumerate(
            zip(obj["raw_vertices"], obj["bones"])
        ):
            if not bone_name:
                raise ValueError(
                    f"{obj['name']} vertex {vidx}: empty Physique bone"
                )
            bone = bones.get(bone_name)
            if bone is None:
                raise ValueError(
                    f"{obj['name']} vertex {vidx}: "
                    f"bone {bone_name!r} absent from skeleton"
                )

            world = transform_point_fixed(local, bone["tm"])
            reconstructed.append(
                (world[0] / 256.0, world[1] / 256.0, world[2] / 256.0)
            )
            all_fixed.append(world)
            used_bones.add(bone_name)

        obj["vertices"] = reconstructed
        obj["bind_pose_reconstructed"] = True

    if not all_fixed:
        raise ValueError("no Physique vertices reconstructed")

    return {
        "vertices": len(all_fixed),
        "bones_used": len(used_bones),
        "bbox_fixed": bbox_points(all_fixed),
    }


MODEL_GROUPS = {
    "high": 0x0C0,
    "default": 0x104,
    "low": 0x148,
}


def parse_inx_model_groups(path):
    data = Path(path).read_bytes()
    groups = {}

    for key, off in MODEL_GROUPS.items():
        if off + 68 > len(data):
            raise ValueError(
                f"INX too small for {key} group at 0x{off:04X}"
            )

        count = struct.unpack_from("<i", data, off)[0]
        if count < 0 or count > 4:
            raise ValueError(
                f"invalid {key} ModelNameCnt={count} at 0x{off:04X}"
            )

        names = []
        base = off + 4
        for i in range(4):
            raw = data[base + i * 16:base + (i + 1) * 16]
            names.append(cstr(raw))

        groups[key] = {
            "count": count,
            "names": names,
            "active": names[:count],
        }

    return groups


def _smd_logical_node_name(obj):
    # Blender makes duplicate object datablock names unique by appending .001,
    # .002, ... .  The runtime does not use those Blender names: INX model
    # groups are matched against the serialized SMD NodeName with lstrcmpi().
    # Preserve/use the original logical name so every duplicate chunk selected
    # by the same INX NodeName remains visible.
    try:
        logical = obj.get("pt_smd_node_name")
    except Exception:
        logical = None
    return str(logical or obj.name)


def _inx_model_name_matches_node_name(inx_name, node_name):
    # INX model-group slots are 16 serialized bytes; SMD NodeName is 32.
    # Full INX slots therefore address the first 16 serialized NodeName bytes.
    # Shorter values remain exact case-insensitive keys.  This is fixed-width
    # matching only, never fuzzy aliasing.
    ikey = str(inx_name).encode("latin-1", errors="replace").lower()
    nkey = str(node_name).encode("latin-1", errors="replace").lower()
    return nkey[:16] == ikey if len(ikey) == 16 else nkey == ikey


def apply_lod_visibility(blender_objects, groups, lod):
    group = groups[lod]
    active_names = [str(name) for name in group["active"] if str(name)]

    logical_rows = [(obj, _smd_logical_node_name(obj)) for obj in blender_objects]
    matched_by_slot = {
        name: [logical for _, logical in logical_rows if _inx_model_name_matches_node_name(name, logical)]
        for name in active_names
    }
    missing = [name for name, matched in matched_by_slot.items() if not matched]
    if missing:
        raise ValueError(
            f"INX {lod} group references missing SMD objects: {missing!r}"
        )

    visible = []
    hidden = []
    for obj, logical_name in logical_rows:
        is_visible = any(_inx_model_name_matches_node_name(name, logical_name) for name in active_names)
        obj.hide_render = not is_visible
        try:
            obj.hide_set(not is_visible)
        except Exception:
            obj.hide_viewport = not is_visible

        obj["pt_inx_lod"] = lod
        obj["pt_inx_match_semantics"] = "SERIALIZED_MODEL_KEY_16_OR_EXACT"
        if is_visible:
            visible.append(logical_name)
        else:
            hidden.append(logical_name)

    return visible, hidden


def choose_tail_direction_and_length(name, bones, children):
    bone = bones[name]
    head = Vector(bone["pos"])
    kids = children.get(name, [])

    preferred_child = {
        "Bip01": "Bip01 Pelvis",
        "Bip01 Pelvis": "Bip01 Spine",
        "Bip01 Spine": "Bip01 Spine1",
        "Bip01 Spine1": "Bip01 Neck",
        "Bip01 Neck": "Bip01 Head",
    }.get(name)

    if preferred_child in kids:
        vec = Vector(bones[preferred_child]["pos"]) - head
        if vec.length > 1e-8:
            return vec.normalized(), vec.length, preferred_child

    if len(kids) == 1:
        child_name = kids[0]
        vec = Vector(bones[child_name]["pos"]) - head
        if vec.length > 1e-8:
            return vec.normalized(), vec.length, child_name

    if len(kids) > 1:
        acc = Vector((0.0, 0.0, 0.0))
        lengths = []
        valid = []

        for child_name in kids:
            vec = Vector(bones[child_name]["pos"]) - head
            if vec.length <= 1e-8:
                continue

            acc += vec.normalized()
            lengths.append(vec.length)
            valid.append(child_name)

        if lengths:
            if acc.length <= 1e-8:
                child_name = valid[0]
                vec = Vector(bones[child_name]["pos"]) - head
                direction = vec.normalized()
            else:
                direction = acc.normalized()

            lengths_sorted = sorted(lengths)
            length = lengths_sorted[len(lengths_sorted) // 2]
            return direction, length, "<branch-average>"

    parent = bone["parent"]
    if parent and parent in bones:
        p = Vector(bones[parent]["pos"])
        vec = head - p

        if vec.length > 1e-8:
            length = max(0.35, min(1.50, vec.length * 0.35))
            return vec.normalized(), length, "<leaf-parent-extension>"

    row_name, row = max(
        bone["rows"].items(),
        key=lambda kv: kv[1].length
    )

    if row.length <= 1e-8:
        row = Vector((0.0, 0.0, 1.0))

    return row.normalized(), 0.75, f"<fallback-row-{row_name}>"


def best_source_row_for_direction(bone, direction):
    d = direction.normalized()

    best_name = ""
    best_abs = -1.0
    best_signed = 0.0

    for axis_name in ("X", "Y", "Z"):
        axis = bone["rows"][axis_name]

        if axis.length <= 1e-8:
            continue

        signed = axis.normalized().dot(d)
        score = abs(signed)

        if score > best_abs:
            best_name = axis_name
            best_abs = score
            best_signed = signed

    return best_name, best_abs, best_signed


def choose_roll_reference(bone, primary_axis, direction):
    d = direction.normalized()
    candidates = []

    for axis_name in ("X", "Y", "Z"):
        if axis_name == primary_axis:
            continue

        axis = bone["rows"][axis_name]

        if axis.length <= 1e-8:
            continue

        n = axis.normalized()
        perpendicular = n - d * n.dot(d)

        if perpendicular.length > 1e-8:
            candidates.append(
                (perpendicular.length, axis_name, n)
            )

    if not candidates:
        return "", None

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, axis_name, ref = candidates[0]
    return axis_name, ref


def create_static_armature(bones, mesh_objects, collection):
    arm_data = bpy.data.armatures.new("PT_m5_Armature")
    arm_obj = bpy.data.objects.new("PT_m5_Armature", arm_data)
    collection.objects.link(arm_obj)

    arm_obj.show_in_front = True
    arm_data.display_type = 'STICK'

    arm_obj["pt_source"] = "m5.smb"
    arm_obj["pt_rest_head_rule"] = "head = Tm._41,_42,_43 / 256"
    arm_obj["pt_parent_rule"] = "NodeParent"
    arm_obj["pt_roll_rule"] = "source Tm row basis"

    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    children = {}
    for name, bone in bones.items():
        parent = bone["parent"]
        if parent:
            children.setdefault(parent, []).append(name)

    edit_bones = {}
    metadata = {}

    for name, bone in bones.items():
        eb = arm_data.edit_bones.new(name)

        head = Vector(bone["pos"])
        direction, length, tail_rule = choose_tail_direction_and_length(
            name, bones, children
        )

        display_length = max(length, 0.10)
        tail = head + direction * display_length

        eb.head = head
        eb.tail = tail
        eb.use_connect = False

        primary_axis, primary_absdot, primary_signed = (
            best_source_row_for_direction(bone, direction)
        )

        roll_axis, roll_ref = choose_roll_reference(
            bone, primary_axis, direction
        )

        if roll_ref is not None:
            eb.align_roll(roll_ref)

        edit_bones[name] = eb

        metadata[name] = {
            "tail_rule": tail_rule,
            "primary_axis": primary_axis,
            "primary_absdot": float(primary_absdot),
            "primary_signed": float(primary_signed),
            "roll_axis": roll_axis,
            "display_length": float(display_length),
        }

    external_parents=[]
    for name, bone in bones.items():
        parent = bone["parent"]

        if parent and parent in edit_bones:
            edit_bones[name].parent = edit_bones[parent]
            edit_bones[name].use_connect = False
        elif parent:
            # Rigid bind reconstruction uses the serialized absolute Tm.  A
            # legacy external parent is representable as a local root for
            # rigid authoring, while pt_parent preserves the original name.
            # This is explicitly NOT animation-pose certification.
            external_parents.append({"bone": name, "parent": parent})

    bpy.ops.object.mode_set(mode='OBJECT')
    arm_obj["pt_external_parent_support"] = json.dumps(external_parents, sort_keys=True)
    arm_obj["pt_external_parent_count"] = len(external_parents)
    arm_obj["pt_animation_pose_certified"] = not bool(external_parents)

    for name, bone in bones.items():
        b = arm_data.bones[name]
        meta = metadata[name]

        b["pt_parent"] = bone["parent"]
        b["pt_tm_i32"] = list(bone["tm"])
        b["pt_primary_axis"] = meta["primary_axis"]
        b["pt_primary_absdot"] = meta["primary_absdot"]
        b["pt_primary_signed_dot"] = meta["primary_signed"]
        b["pt_roll_reference_axis"] = meta["roll_axis"]
        b["pt_tail_rule"] = meta["tail_rule"]
        b["pt_display_length"] = meta["display_length"]

    modifier_count = 0

    for obj in mesh_objects:
        if obj.type != 'MESH':
            continue

        mod = obj.modifiers.new(
            name="PT_m5_Armature",
            type='ARMATURE'
        )
        mod.object = arm_obj
        modifier_count += 1

    roots = [
        name for name, bone in bones.items()
        if not bone["parent"]
    ]

    arm_obj.select_set(False)

    return {
        "object": arm_obj,
        "bones": len(bones),
        "roots": roots,
        "modifiers": modifier_count,
        "metadata": metadata,
    }

def resolve_case_insensitive(root, relative_windows_name):
    if not relative_windows_name:
        return None

    p = PureWindowsPath(relative_windows_name)
    parts = list(p.parts)

    if p.drive:
        parts = parts[1:]

    cur = root
    for part in parts:
        exact = cur / part
        if exact.exists():
            cur = exact
            continue

        if not cur.is_dir():
            return None

        target = part.lower()
        matches = [x for x in cur.iterdir() if x.name.lower() == target]
        if not matches:
            return None
        matches.sort(key=lambda x: x.name)
        cur = matches[0]

    return cur if cur.exists() else None


def decoded_cache_name(src, cache_dir):
    key = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:10]
    return cache_dir / f"{src.stem}.{key}.decoded{src.suffix.lower()}"


def prepare_bmp(src, cache_dir):
    data = bytearray(src.read_bytes())

    if data[:2] == b"BM":
        return src, "BMP_STANDARD"

    if len(data) < 54:
        return src, "BMP_UNKNOWN_SHORT"

    dib = int.from_bytes(data[14:18], "little")
    if dib < 40 or dib > 124:
        return src, "BMP_UNKNOWN_HEADER"

    w = int.from_bytes(data[18:22], "little", signed=True)
    h = int.from_bytes(data[22:26], "little", signed=True)
    planes = int.from_bytes(data[26:28], "little")
    bpp = int.from_bytes(data[28:30], "little")
    compression = int.from_bytes(data[30:34], "little")

    if not (1 <= abs(w) <= 16384 and 1 <= abs(h) <= 16384):
        return src, "BMP_UNKNOWN_DIMENSIONS"
    if planes != 1 or bpp not in (1, 4, 8, 16, 24, 32):
        return src, "BMP_UNKNOWN_FORMAT"

    pixel_offset = 14 + dib
    if dib == 40 and compression == 3 and bpp in (16, 32):
        pixel_offset += 12
    if bpp <= 8:
        clr_used = int.from_bytes(data[46:50], "little") if len(data) >= 50 else 0
        palette_entries = clr_used if clr_used else (1 << bpp)
        pixel_offset += palette_entries * 4

    data[:14] = struct.pack(
        "<2sIHHI", b"BM", len(data), 0, 0, pixel_offset
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    out = decoded_cache_name(src, cache_dir)
    out.write_bytes(data)
    return out, f"BMP_PRISTON_PREFIX14_{w}x{h}_{bpp}bpp"


def prepare_texture(src, cache_dir):
    if src is None:
        return None, "NOT_FOUND"
    if src.suffix.lower() == ".bmp":
        return prepare_bmp(src, cache_dir)
    return src, "AS_IS"


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def ensure_collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def safe_name(s):
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "Material")
    return s[:100]


def create_blender_materials(materials, client_root, cache_dir, pack_images=True):
    out = []

    for m in materials:
        tex_name = m["textures"][0][0] if m["textures"] else ""
        src = resolve_case_insensitive(client_root, tex_name) if tex_name else None
        prepared, decode_tag = prepare_texture(src, cache_dir)

        label = PureWindowsPath(tex_name).name if tex_name else "NO_TEXTURE"
        mat = bpy.data.materials.new(
            name=f"SMD_MAT_{m['index']:02d}_{safe_name(label)}"
        )
        mat.use_nodes = True

        mat["pt_smd_material_id"] = m["index"]
        mat["pt_smd_in_use"] = int(m["in_use"])
        mat["pt_smd_texture_name"] = tex_name
        mat["pt_smd_texture_decode"] = decode_tag
        mat["pt_smd_blend_type"] = int(m["blend_type"])
        mat["pt_smd_blend_name"] = BLEND_NAMES.get(m["blend_type"], "UNKNOWN")
        mat["pt_smd_two_side"] = int(m["two_side"])
        mat["pt_smd_shade"] = int(m["shade"])
        mat["pt_smd_transparency"] = float(m["transparency"])
        mat["pt_smd_self_illum"] = float(m["self_illum"])

        if hasattr(mat, "use_backface_culling"):
            try:
                mat.use_backface_culling = not bool(m["two_side"])
            except Exception:
                pass

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")

        if bsdf:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.7
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = max(
                    0.0, min(1.0, 1.0 - m["transparency"])
                )

        load_status = "NO_TEXTURE"

        if prepared is not None:
            try:
                image = bpy.data.images.load(str(prepared), check_existing=False)
                image.reload()
                if int(image.size[0]) <= 0 or int(image.size[1]) <= 0:
                    raise RuntimeError(f"invalid image size {tuple(image.size)}")
                if len(image.pixels) > 0:
                    _ = image.pixels[0]

                try:
                    image.colorspace_settings.name = "sRGB"
                except Exception:
                    pass

                tex = nodes.new("ShaderNodeTexImage")
                tex.name = "PT_SMD_DIFFUSE"
                tex.label = Path(prepared).name
                tex.image = image

                if bsdf:
                    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
                    if "Alpha" in tex.outputs and "Alpha" in bsdf.inputs:
                        links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])

                if pack_images:
                    try:
                        image.pack()
                    except Exception as exc:
                        print(f"WARN image.pack failed: {prepared}: {exc}")

                load_status = "LOADED"
            except Exception as exc:
                load_status = f"LOAD_ERROR:{type(exc).__name__}:{exc}"

        mat["pt_smd_texture_load"] = load_status
        print(
            f"MATERIAL {m['index']}: tex={tex_name!r} "
            f"resolved={str(src) if src else None!r} "
            f"prepared={str(prepared) if prepared else None!r} "
            f"decode={decode_tag} load={load_status}"
        )

        out.append(mat)

    return out


def create_mesh_object(src_obj, collection, blender_materials):
    verts = src_obj["vertices"]
    face_defs = src_obj["faces"]
    faces = [x["verts"] for x in face_defs]

    mesh = bpy.data.meshes.new(f"{src_obj['name']}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update(calc_edges=True)

    obj = bpy.data.objects.new(src_obj["name"], mesh)
    collection.objects.link(obj)

    for mat in blender_materials:
        mesh.materials.append(mat)

    for poly_index, fd in enumerate(face_defs):
        mesh.polygons[poly_index].material_index = fd["material"]

    uv_layer = mesh.uv_layers.new(name="SMD_UV")
    uv_faces = 0
    max_layers = 0

    for poly_index, fd in enumerate(face_defs):
        chain = fd["texlinks"]
        max_layers = max(max_layers, len(chain))
        if not chain:
            continue

        tl = src_obj["texlinks"][chain[0]]
        coords = [
            (float(tl["u"][i]), 1.0 - float(tl["v"][i]))
            for i in range(3)
        ]

        poly = mesh.polygons[poly_index]
        for loop_idx, uv in zip(poly.loop_indices, coords):
            uv_layer.data[loop_idx].uv = uv
        uv_faces += 1

    groups = {}
    if src_obj["bones"] is not None:
        for vidx, bone_name in enumerate(src_obj["bones"]):
            if not bone_name:
                continue
            group = groups.get(bone_name)
            if group is None:
                group = obj.vertex_groups.new(name=bone_name)
                groups[bone_name] = group
            group.add([vidx], 1.0, "REPLACE")

    # Keep the serialized SMD logical NodeName separate from Blender's unique
    # datablock name.  This is required for runtime-faithful INX LOD matching
    # when one SMD contains multiple chunks with the same NodeName.
    obj["pt_smd_node_name"] = src_obj["name"]
    obj["pt_smd_node_parent"] = src_obj["parent"]
    obj["pt_smd_vertex_count"] = len(verts)
    obj["pt_smd_face_count"] = len(faces)
    obj["pt_smd_texlink_count"] = len(src_obj["texlinks"])
    obj["pt_smd_uv_faces"] = uv_faces
    obj["pt_smd_max_tex_layers"] = max_layers
    obj["pt_smd_has_physique"] = int(src_obj["has_physique"])
    obj["pt_smd_vertex_group_count"] = len(groups)
    obj["pt_smd_coordinate_rule"] = "XYZ=int(ASE_XYZ*256); Blender=XYZ/256"
    obj["pt_smd_uv_rule"] = "Blender_U=SMD_U; Blender_V=1-SMD_V"

    return obj, {
        "name": src_obj["name"],
        "vertices": len(verts),
        "faces": len(faces),
        "uv_faces": uv_faces,
        "max_layers": max_layers,
        "vertex_groups": len(groups),
    }


def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--skeleton", required=True)
    p.add_argument("--model-info")
    p.add_argument("--lod", choices=("high", "default", "low"), default="default")
    p.add_argument("--single-tier-full-container", action="store_true", help="legacy single-tier INX: keep every SMD chunk visible without alias matching")
    p.add_argument("--client-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cache")
    p.add_argument("--no-pack", action="store_true")
    return p.parse_args(argv)


def main(argv):
    if bpy is None:
        raise RuntimeError("This script must run inside Blender")

    args = parse_args(argv)
    smd_path = Path(args.smd).resolve()
    skeleton_path = Path(args.skeleton).resolve()
    model_info_path = Path(args.model_info).resolve() if args.model_info else None
    client_root = Path(args.client_root).resolve()
    out_path = Path(args.out).resolve()
    cache_dir = (
        Path(args.cache).resolve()
        if args.cache
        else out_path.parent / "_pt_smd_texture_cache"
    )

    data = smd_path.read_bytes()
    skeleton_data = skeleton_path.read_bytes()
    meta = parse_header_and_infos(data)
    materials = parse_materials(data, meta)
    objects = parse_objects(data, meta)
    skeleton_meta, skeleton_bones = parse_skeleton_tms(skeleton_data)
    bind_stats = reconstruct_bind_pose(objects, skeleton_bones)
    if model_info_path is not None:
        model_groups = parse_inx_model_groups(model_info_path)
    else:
        # Standalone rigid Model0.62 assets (notably effect/map animated props)
        # can have a sibling SMB but no INX model-info. In that mode the
        # skeleton still proves Physique binding, while every SMD object is
        # visible because there is no serialized LOD selection to apply.
        names = [str(x.get("name") or "") for x in objects if str(x.get("name") or "")]
        model_groups = {
            "high": {"count": 0, "active": []},
            "default": {"count": len(names), "active": names},
            "low": {"count": 0, "active": []},
        }

    print("PT_SMD_BLENDER_IMPORT_V3_STATIC_ARMATURE")
    print("SMD        :", smd_path)
    print("Skeleton   :", skeleton_path)
    print("Model info :", model_info_path if model_info_path is not None else "<standalone:no-inx>")
    print("LOD        :", args.lod)
    print("Client root:", client_root)
    print("Output     :", out_path)
    print("Objects    :", len(objects))
    print("Materials  :", len(materials))
    print("Skeleton objects:", skeleton_meta["obj_counter"])
    print("Bind vertices   :", bind_stats["vertices"])
    print("Bind bones used :", bind_stats["bones_used"])
    b = bind_stats["bbox_fixed"]
    print(
        "Bind bbox       : "
        f"x=[{b[0]/256.0:.3f},{b[1]/256.0:.3f}] "
        f"y=[{b[2]/256.0:.3f},{b[3]/256.0:.3f}] "
        f"z=[{b[4]/256.0:.3f},{b[5]/256.0:.3f}]"
    )

    clear_scene()
    collection = ensure_collection("PT_SMD_IMPORT_V3_STATIC_ARMATURE")

    blender_materials = create_blender_materials(
        materials,
        client_root,
        cache_dir,
        pack_images=not args.no_pack,
    )

    stats = []
    blender_objects = []
    for src_obj in objects:
        obj, info = create_mesh_object(
            src_obj, collection, blender_materials
        )
        blender_objects.append(obj)
        stats.append(info)
        print(
            f"OBJECT {info['name']}: "
            f"V={info['vertices']} F={info['faces']} "
            f"UV={info['uv_faces']} layers={info['max_layers']} "
            f"groups={info['vertex_groups']}"
        )

    if model_info_path is None or args.single_tier_full_container:
        visible_objects = [obj.name for obj in blender_objects]
        hidden_objects = []
        for obj in blender_objects:
            obj.hide_viewport = False
            obj.hide_render = False
    else:
        visible_objects, hidden_objects = apply_lod_visibility(
            blender_objects, model_groups, args.lod
        )

    armature_stats = create_static_armature(
        skeleton_bones,
        blender_objects,
        collection,
    )

    print()
    print("STATIC_ARMATURE")
    print(f"bones={armature_stats['bones']}")
    print(f"roots={armature_stats['roots']!r}")
    print(f"mesh_armature_modifiers={armature_stats['modifiers']}")

    primary_hist = {}
    tail_rule_hist = {}

    for meta in armature_stats["metadata"].values():
        axis = meta["primary_axis"]
        primary_hist[axis] = primary_hist.get(axis, 0) + 1

        rule = meta["tail_rule"]
        tail_rule_hist[rule] = tail_rule_hist.get(rule, 0) + 1

    print(f"primary_axis_histogram={primary_hist!r}")
    print(f"tail_rule_histogram={tail_rule_hist!r}")

    print()
    print("INX_MODEL_GROUPS")
    for key in ("high", "default", "low"):
        group = model_groups[key]
        print(
            f"{key}: count={group['count']} "
            f"active={group['active']!r}"
        )
    print(f"selected_lod={args.lod}")
    print(f"visible_objects={visible_objects!r}")
    print(f"hidden_objects={hidden_objects!r}")

    total_v = sum(x["vertices"] for x in stats)
    total_f = sum(x["faces"] for x in stats)
    total_uv = sum(x["uv_faces"] for x in stats)

    bpy.context.scene["pt_smd_source"] = str(smd_path)
    bpy.context.scene["pt_smb_skeleton_source"] = str(skeleton_path)
    bpy.context.scene["pt_inx_model_info_source"] = str(model_info_path) if model_info_path is not None else ""
    bpy.context.scene["pt_inx_lod"] = args.lod
    bpy.context.scene["pt_inx_visible_nodes"] = ",".join(visible_objects)
    bpy.context.scene["pt_static_armature"] = "PT_m5_Armature"
    bpy.context.scene["pt_static_armature_bones"] = armature_stats["bones"]
    bpy.context.scene["pt_smd_bind_pose_rule"] = "world = SMD_local * bone.Tm"
    bpy.context.scene["pt_smd_version"] = "SMD Model data Ver 0.62"
    bpy.context.scene["pt_smd_object_count"] = len(objects)
    bpy.context.scene["pt_smd_material_count"] = len(materials)
    bpy.context.scene["pt_smd_total_vertices"] = total_v
    bpy.context.scene["pt_smd_total_faces"] = total_f
    bpy.context.scene["pt_smd_total_uv_faces"] = total_uv

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path))

    print("SUMMARY")
    print(f"objects={len(objects)}")
    print(f"materials={len(materials)}")
    print(f"vertices={total_v}")
    print(f"faces={total_f}")
    print(f"uv_faces={total_uv}")
    print(f"bind_vertices={bind_stats['vertices']}")
    print(f"bind_bones_used={bind_stats['bones_used']}")
    print(f"model_info={model_info_path if model_info_path is not None else '<standalone:no-inx>'}")
    print(f"lod={args.lod}")
    print(f"visible_count={len(visible_objects)}")
    print(f"visible_objects={visible_objects!r}")
    print(f"hidden_count={len(hidden_objects)}")
    print(f"armature_bones={armature_stats['bones']}")
    print(f"armature_roots={armature_stats['roots']!r}")
    print(f"mesh_armature_modifiers={armature_stats['modifiers']}")
    print(f"blend={out_path}")
    print("static_armature_import_check=PASS")


if __name__ == "__main__":
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    main(argv)
