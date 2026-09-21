from __future__ import annotations

import hashlib
import math
import struct
from typing import Any

from .material_group_compiler import compile_material_group

FORMAT = "PT_MODEL062_STATIC_COMPILER_V1"
MAGIC = b"SMD Model data Ver 0.62"
HEADER_SIZE = 556
OBJECT_INFO_SIZE = 40
OBJECT_HEADER_SIZE = 2236
VERTEX_SIZE = 24
FACE_SIZE = 36
TEXLINK_SIZE = 32
MATERIAL_GROUP_SIZE = 88
MATERIAL_SIZE = 320
TEXTURE_BASE = 0x10000000
HEAD_NEW_NORMAL = 0x41424344 | 0x80000000
FIXED_SCALE = 256
MAX_OBJECTS = 128
MAX_MATERIALS = 5000
MAX_VERTICES = 30000
MAX_FACES = 30000
MAX_TEXLINKS_PER_FACE = 9


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixed_name(value: str, capacity: int, encoding: str = "cp949") -> bytes:
    raw = str(value or "").encode(encoding)
    if not raw or len(raw) >= capacity:
        raise ValueError(f"MODEL062_FIXED_STRING_INVALID:{capacity}:{value}")
    return raw + b"\0" * (capacity - len(raw))


def _float3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"MODEL062_{label}_VEC3_REQUIRED")
    out = tuple(float(x) for x in value)
    if not all(math.isfinite(x) for x in out):
        raise ValueError(f"MODEL062_{label}_FINITE_REQUIRED")
    return out


def _uv3(value: Any) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("MODEL062_UV_TRIANGLE_REQUIRED")
    out = []
    for p in value:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("MODEL062_UV_PAIR_REQUIRED")
        u, v = float(p[0]), float(p[1])
        if not (math.isfinite(u) and math.isfinite(v)):
            raise ValueError("MODEL062_UV_FINITE_REQUIRED")
        out.append((u, v))
    return tuple(out)  # type: ignore[return-value]


def _identity_i32() -> bytes:
    values = [0] * 16
    for i in (0, 5, 10, 15):
        values[i] = FIXED_SCALE
    return struct.pack("<16i", *values)


def _identity_f32() -> bytes:
    values = [0.0] * 16
    for i in (0, 5, 10, 15):
        values[i] = 1.0
    return struct.pack("<16f", *values)


def _encode_material_group(materials: list[dict[str, Any]]) -> tuple[bytes, list[dict[str, Any]]]:
    data, meta = compile_material_group(materials)
    return data, list(meta.get("materials") or [])


def _compute_normals(vertices: list[tuple[int, int, int]], faces: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int]]:
    sums = [[0, 0, 0, 0] for _ in vertices]
    for a, b, c, _mat in faces:
        p1, p2, p3 = vertices[a], vertices[b], vertices[c]
        i = float(p2[1] - p1[1]) * (p3[2] - p1[2]) - float(p2[2] - p1[2]) * (p3[1] - p1[1])
        j = float(p2[2] - p1[2]) * (p3[0] - p1[0]) - float(p2[0] - p1[0]) * (p3[2] - p1[2])
        k = float(p2[0] - p1[0]) * (p3[1] - p1[1]) - float(p2[1] - p1[1]) * (p3[0] - p1[0])
        length = math.sqrt(i * i + j * j + k * k)
        if length <= 0.0 or not math.isfinite(length):
            continue
        n = (int(i / length * 32767.0), int(j / length * 32767.0), int(k / length * 32767.0))
        for vi in (a, b, c):
            sums[vi][0] += n[0]; sums[vi][1] += n[1]; sums[vi][2] += n[2]; sums[vi][3] += 1
    out = []
    for idx, (x, y, z) in enumerate(vertices):
        sx, sy, sz, cnt = sums[idx]
        if cnt:
            out.append((x + sx // cnt, y + sy // cnt, z + sz // cnt))
        else:
            out.append((x, y, z))
    return out


def _object_blob(spec: dict[str, Any], material_meta: list[dict[str, Any]], coordinate_scale: int) -> tuple[bytes, dict[str, Any]]:
    material_count = len(material_meta)
    name = str(spec.get("name") or "").strip()
    parent = str(spec.get("parent") or "").strip()
    name_bytes = _fixed_name(name, 32)
    parent_bytes = b"\0" * 32 if not parent else _fixed_name(parent, 32)
    raw_vertices = spec.get("vertices") or []
    raw_faces = spec.get("faces") or []
    if not isinstance(raw_vertices, list) or not isinstance(raw_faces, list):
        raise ValueError(f"MODEL062_OBJECT_GEOMETRY_LISTS_REQUIRED:{name}")
    if not 0 < len(raw_vertices) <= MAX_VERTICES:
        raise ValueError(f"MODEL062_VERTEX_COUNT_INVALID:{name}:{len(raw_vertices)}")
    if not 0 < len(raw_faces) <= MAX_FACES:
        raise ValueError(f"MODEL062_FACE_COUNT_INVALID:{name}:{len(raw_faces)}")
    vertices: list[tuple[int, int, int]] = []
    for value in raw_vertices:
        x, y, z = _float3(value, "VERTEX")
        fixed = tuple(int(round(v * coordinate_scale)) for v in (x, y, z))
        if any(v < -0x80000000 or v > 0x7FFFFFFF for v in fixed):
            raise ValueError(f"MODEL062_VERTEX_FIXED_OVERFLOW:{name}")
        vertices.append(fixed)  # type: ignore[arg-type]
    faces: list[tuple[int, int, int, int]] = []
    uv_layers_by_face: list[list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]] = []
    texlink_count = 0
    for fidx, row in enumerate(raw_faces):
        if not isinstance(row, dict):
            raise ValueError(f"MODEL062_FACE_OBJECT_REQUIRED:{name}:{fidx}")
        inds = row.get("vertices")
        if not isinstance(inds, (list, tuple)) or len(inds) != 3:
            raise ValueError(f"MODEL062_FACE_TRIANGLE_REQUIRED:{name}:{fidx}")
        a, b, c = (int(x) for x in inds)
        if any(x < 0 or x >= len(vertices) for x in (a, b, c)):
            raise ValueError(f"MODEL062_FACE_VERTEX_OOB:{name}:{fidx}")
        material = int(row.get("material") or 0)
        if material < 0 or material >= material_count:
            raise ValueError(f"MODEL062_FACE_MATERIAL_OOB:{name}:{fidx}:{material}")
        layers_raw = row.get("uv_layers")
        if layers_raw is None and row.get("uv") is not None:
            layers_raw = [row.get("uv")]
        layers_raw = layers_raw or []
        if not isinstance(layers_raw, list) or len(layers_raw) > MAX_TEXLINKS_PER_FACE:
            raise ValueError(f"MODEL062_FACE_UV_LAYER_LIMIT_9:{name}:{fidx}")
        layers = [_uv3(layer) for layer in layers_raw]
        regular_texture_count = len(material_meta[material].get("textures") or [])
        if len(layers) > regular_texture_count:
            raise ValueError(f"MODEL062_FACE_UV_EXCEEDS_MATERIAL_TEXTURES:{name}:{fidx}:{len(layers)}>{regular_texture_count}")
        faces.append((a, b, c, material))
        uv_layers_by_face.append(layers)
        texlink_count += len(layers)
    if texlink_count > len(faces) * MAX_TEXLINKS_PER_FACE:
        raise AssertionError("MODEL062_TEXLINK_COUNT_INTERNAL")

    raw_bones = spec.get("vertex_bones")
    vertex_bones: list[str] = []
    if raw_bones is not None:
        if not isinstance(raw_bones, list) or len(raw_bones) != len(vertices):
            raise ValueError(f"MODEL062_VERTEX_BONES_COUNT_MUST_MATCH_VERTICES:{name}")
        for bone in raw_bones:
            bone_name = str(bone or "").strip()
            _fixed_name(bone_name, 32)
            vertex_bones.append(bone_name)

    normals = _compute_normals(vertices, faces)
    max_x = max(abs(x) for x, _, _ in vertices)
    max_z = max(abs(y) for _, y, _ in vertices)
    max_y = max(abs(z) for _, _, z in vertices)
    dbound = max((x >> 8) ** 2 + (y >> 8) ** 2 + (z >> 8) ** 2 for x, y, z in vertices)
    dbound = min(dbound, 0x7FFFFFFF)
    bound = int(math.sqrt(dbound))

    hdr = bytearray(OBJECT_HEADER_SIZE)
    struct.pack_into("<I", hdr, 0, HEAD_NEW_NORMAL)
    struct.pack_into("<I", hdr, 4, 1)  # deterministic presence sentinels
    struct.pack_into("<I", hdr, 8, 1)
    struct.pack_into("<I", hdr, 12, TEXTURE_BASE if texlink_count else 0)
    struct.pack_into("<I", hdr, 16, 1 if vertex_bones else 0)
    struct.pack_into("<6i", hdr, 44, max_z, 0, max_y, 0, max_x, 0)
    struct.pack_into("<ii", hdr, 68, dbound, bound)
    struct.pack_into("<iiiii", hdr, 76, len(vertices), len(faces), len(vertices), len(faces), texlink_count)
    struct.pack_into("<I", hdr, 96, 1)
    struct.pack_into("<I", hdr, 100, 0x01 | 0x04 | 0x08 | 0x10 | 0x20)
    hdr[172:204] = name_bytes
    hdr[204:236] = parent_bytes
    # pParent is zero.  Source initializes all transform matrices to identity.
    hdr[240:304] = _identity_i32()
    hdr[304:368] = _identity_i32()
    hdr[368:432] = _identity_f32()
    hdr[432:496] = _identity_i32()
    hdr[496:560] = _identity_i32()
    hdr[560:624] = _identity_i32()
    struct.pack_into("<4f", hdr, 628, 0.0, 0.0, 0.0, 1.0)
    struct.pack_into("<6i", hdr, 644, FIXED_SCALE, FIXED_SCALE, FIXED_SCALE, 0, 0, 0)

    vb = bytearray()
    for (x, y, z), (nx, ny, nz) in zip(vertices, normals):
        vb += struct.pack("<6i", x, y, z, nx, ny, nz)
    fb = bytearray()
    tb = bytearray()
    next_link_index = 0
    for (a, b, c, material), layers in zip(faces, uv_layers_by_face):
        token = TEXTURE_BASE + next_link_index * TEXLINK_SIZE if layers else 0
        fb += struct.pack("<4H", a, b, c, material)
        fb += b"\0" * 24  # historical smFACE.t[3], not texture-authority after TexLink load
        fb += struct.pack("<I", token)
        for lidx, layer in enumerate(layers):
            us = [p[0] for p in layer]
            vs = [p[1] for p in layer]
            next_token = TEXTURE_BASE + (next_link_index + 1) * TEXLINK_SIZE if lidx + 1 < len(layers) else 0
            tb += struct.pack("<3f3fII", *us, *vs, 0, next_token)
            next_link_index += 1
    physique = bytearray()
    for bone_name in vertex_bones:
        physique += _fixed_name(bone_name, 32)
    blob = bytes(hdr + vb + fb + tb + physique)
    expected = OBJECT_HEADER_SIZE + len(vertices) * VERTEX_SIZE + len(faces) * FACE_SIZE + texlink_count * TEXLINK_SIZE + len(vertex_bones) * 32
    if len(blob) != expected:
        raise AssertionError("MODEL062_OBJECT_SIZE_INTERNAL")
    return blob, {
        "name": name, "parent": parent or None, "vertex_count": len(vertices), "face_count": len(faces),
        "texlink_count": texlink_count, "bound": bound, "d_bound": dbound,
        "physique": bool(vertex_bones), "bone_bindings": sorted(set(vertex_bones), key=str.casefold),
    }


def compile_static_model062(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    mesh = payload.get("mesh") if isinstance(payload.get("mesh"), dict) else payload
    objects = mesh.get("objects") or []
    materials = mesh.get("materials") or []
    if not isinstance(objects, list) or not 1 <= len(objects) <= MAX_OBJECTS:
        raise ValueError("MODEL062_OBJECT_COUNT_1_TO_128_REQUIRED")
    if not isinstance(materials, list) or not 1 <= len(materials) <= MAX_MATERIALS:
        raise ValueError("MODEL062_STATIC_REQUIRES_1_TO_5000_MATERIALS")
    coordinate_scale = int(mesh.get("coordinate_scale") or FIXED_SCALE)
    if coordinate_scale <= 0 or coordinate_scale > 1_000_000:
        raise ValueError("MODEL062_COORDINATE_SCALE_INVALID")
    material_bytes, material_meta = _encode_material_group(materials)
    object_blobs: list[bytes] = []
    object_meta: list[dict[str, Any]] = []
    names: set[str] = set()
    for spec in objects:
        if not isinstance(spec, dict):
            raise ValueError("MODEL062_OBJECT_REQUIRED")
        name = str(spec.get("name") or "").casefold()
        if not name or name in names:
            raise ValueError(f"MODEL062_OBJECT_NAME_DUPLICATE_OR_EMPTY:{name}")
        names.add(name)
        blob, meta = _object_blob(spec, material_meta, coordinate_scale)
        object_blobs.append(blob); object_meta.append(meta)

    mat_point = HEADER_SIZE + OBJECT_INFO_SIZE * len(objects)
    first_obj = mat_point + len(material_bytes)
    header = bytearray(HEADER_SIZE)
    header[:len(MAGIC)] = MAGIC
    struct.pack_into("<iiii", header, 24, len(objects), len(materials), mat_point, first_obj)
    # TmFrameCounter and TmFrame[] remain zero for STATIC_V1.
    infos = bytearray()
    offset = first_obj
    for meta, blob in zip(object_meta, object_blobs):
        infos += _fixed_name(str(meta["name"]), 32)
        infos += struct.pack("<ii", len(blob), offset)
        offset += len(blob)
    data = bytes(header + infos + material_bytes + b"".join(object_blobs))
    if offset != len(data):
        raise AssertionError("MODEL062_PATTERN_SIZE_INTERNAL")
    return data, {
        "writer": "MODEL062_SOURCE_NATIVE_STATIC_V1",
        "format": FORMAT,
        "magic": MAGIC.decode("ascii"),
        "object_count": len(objects),
        "material_count": len(materials),
        "objects": object_meta,
        "materials": material_meta,
        "material_compiler": "LEGACY_MATERIAL_GROUP_WIN32_SOURCE_NATIVE",
        "coordinate_scale": coordinate_scale,
        "supports_animation": False,
        "supports_physique": True,
        "deterministic_pointer_policy": True,
        "sha256": _sha(data),
        "source_evidence": [
            "Shared/rendering/legacy_3d/object/LegacyPatternSerialization.h",
            "Shared/rendering/legacy_3d/object/LegacyObjectDiskLayout.h",
            "Shared/rendering/legacy_3d/object/LegacyObjectSerialization.h",
            "Shared/rendering/legacy_3d/material/LegacyMaterialSerialization.h",
            "Shared/rendering/legacy_3d/object/ObjectNormals.h",
        ],
    }
