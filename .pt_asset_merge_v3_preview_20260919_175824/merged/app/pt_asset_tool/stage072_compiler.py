from __future__ import annotations

import hashlib
import math
import pathlib
import struct
import tempfile
from collections import defaultdict
from typing import Any

from .material_group_compiler import MATERIAL_SIZE, compile_material_group

FORMAT = "PT_STAGE072_SOURCE_NATIVE_COMPILER_V1"
MAGIC = b"SMD Stage data Ver 0.72"
DFILE_HEADER_SIZE = 556
STAGE_DISK_SIZE = 262260
MAP_SIZE = 256
STAGE_VERTEX_SIZE = 28
STAGE_FACE_SIZE = 28
TEXLINK_SIZE = 32
LIGHT_SIZE = 28
FIXED_SCALE = 256
MAX_TEXLINKS_PER_FACE = 9
MAX_VERTICES = 65536  # face indices are WORD
MAX_CELLS_PER_FACE = 4096
TEXLINK_BASE = 0x10000000
MATERIAL_BASE = 0x20000000
AREA_BASE = 0x30000000

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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _vec3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"STAGE072_{label}_VEC3_REQUIRED")
    out = tuple(float(x) for x in value)
    if not all(math.isfinite(x) for x in out):
        raise ValueError(f"STAGE072_{label}_FINITE_REQUIRED")
    return out  # type: ignore[return-value]


def _uv3(value: Any) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("STAGE072_UV_TRIANGLE_REQUIRED")
    out = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError("STAGE072_UV_PAIR_REQUIRED")
        u, v = float(row[0]), float(row[1])
        if not math.isfinite(u) or not math.isfinite(v):
            raise ValueError("STAGE072_UV_FINITE_REQUIRED")
        out.append((u, v))
    return tuple(out)  # type: ignore[return-value]


def _i16(value: Any, label: str) -> int:
    out = int(value)
    if not -32768 <= out <= 32767:
        raise ValueError(f"STAGE072_{label}_INT16_REQUIRED:{out}")
    return out


def _i32(value: Any, label: str) -> int:
    out = int(value)
    if not -(2**31) <= out < 2**31:
        raise ValueError(f"STAGE072_{label}_INT32_REQUIRED:{out}")
    return out


def _fixed_vertex(row: Any, scale: int, fixed_coordinates: bool) -> tuple[int, int, int, tuple[int, int, int, int]]:
    if isinstance(row, dict):
        pos = row.get("position", row.get("xyz"))
        color_raw = row.get("color", [255, 255, 255, 255])
    else:
        pos = row
        color_raw = [255, 255, 255, 255]
    x, y, z = _vec3(pos, "VERTEX")
    if fixed_coordinates:
        xyz = (int(round(x)), int(round(y)), int(round(z)))
    else:
        xyz = tuple(int(round(v * scale)) for v in (x, y, z))
    if any(v < -(2**31) or v >= 2**31 for v in xyz):
        raise ValueError("STAGE072_VERTEX_FIXED_OVERFLOW")
    if not isinstance(color_raw, (list, tuple)) or len(color_raw) != 4:
        raise ValueError("STAGE072_VERTEX_COLOR_RGBA_REQUIRED")
    color = tuple(_i16(v, "VERTEX_COLOR") for v in color_raw)
    return xyz[0], xyz[1], xyz[2], color  # type: ignore[return-value]


def _source_face_normal(vertices: list[tuple[int, int, int, tuple[int, int, int, int]]], inds: tuple[int, int, int]) -> tuple[int, int, int, int]:
    # StageLighting/legacy Light() first converts fixed-point coordinates using >> FLOATNS,
    # then SetNormal() normalizes the cross product to 32767.
    pts = [tuple(vertices[i][j] >> 8 for j in range(3)) for i in inds]
    p1, p2, p3 = pts
    i = float((p2[1] - p1[1]) * (p3[2] - p1[2]) - (p2[2] - p1[2]) * (p3[1] - p1[1]))
    j = float((p2[2] - p1[2]) * (p3[0] - p1[0]) - (p2[0] - p1[0]) * (p3[2] - p1[2]))
    k = float((p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0]))
    d = math.sqrt(i * i + j * j + k * k)
    if not math.isfinite(d) or d <= 0.0:
        raise ValueError(f"STAGE072_DEGENERATE_FACE:{inds}")
    return int(i / d * 32767.0), int(j / d * 32767.0), int(k / d * 32767.0), 0


def _covered_cells(vertices: list[tuple[int, int, int, tuple[int, int, int, int]]], inds: tuple[int, int, int]) -> list[tuple[int, int]]:
    pts = [(vertices[i][0] >> 8, vertices[i][2] >> 8) for i in inds]
    left = min(x for x, _ in pts) >> 6
    right = (max(x for x, _ in pts) >> 6) + 1
    top = min(z for _, z in pts) >> 6
    bottom = (max(z for _, z in pts) >> 6) + 1
    width, height = right - left, bottom - top
    if width < 0 or height < 0 or width > MAX_CELLS_PER_FACE or height > MAX_CELLS_PER_FACE or width * height > MAX_CELLS_PER_FACE:
        raise ValueError(f"STAGE072_FACE_AREA_COVERAGE_LIMIT:{inds}:{width}x{height}")
    return [(x & 0xFF, y & 0xFF) for x in range(left, right) for y in range(top, bottom)]


def _auto_areas(vertices: list[tuple[int, int, int, tuple[int, int, int, int]]], faces: list[dict[str, Any]]) -> dict[tuple[int, int], list[int]]:
    out: dict[tuple[int, int], list[int]] = defaultdict(list)
    for fi, face in enumerate(faces):
        for cell in _covered_cells(vertices, face["vertices"]):
            out[cell].append(fi)
    return dict(out)


def _explicit_areas(value: Any, face_count: int) -> dict[tuple[int, int], list[int]]:
    if not isinstance(value, list):
        raise ValueError("STAGE072_AREAS_LIST_REQUIRED")
    out: dict[tuple[int, int], list[int]] = {}
    for idx, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"STAGE072_AREA_OBJECT_REQUIRED:{idx}")
        x, y = int(row.get("x")), int(row.get("y", row.get("z")))
        if not 0 <= x < MAP_SIZE or not 0 <= y < MAP_SIZE:
            raise ValueError(f"STAGE072_AREA_CELL_OOB:{x}:{y}")
        key = (x, y)
        if key in out:
            raise ValueError(f"STAGE072_AREA_DUPLICATE:{x}:{y}")
        refs = [int(v) for v in (row.get("faces") or [])]
        if not refs:
            raise ValueError(f"STAGE072_AREA_EMPTY:{x}:{y}")
        if any(v < 0 or v >= face_count for v in refs):
            raise ValueError(f"STAGE072_AREA_FACE_OOB:{x}:{y}")
        if len(set(refs)) != len(refs):
            raise ValueError(f"STAGE072_AREA_DUPLICATE_FACE:{x}:{y}")
        out[key] = refs
    return out


def compile_stage072(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("STAGE072_PAYLOAD_OBJECT_REQUIRED")
    spec = payload.get("stage") if isinstance(payload.get("stage"), dict) else payload
    materials = spec.get("materials") or []
    material_blob, material_meta = compile_material_group(materials)
    mat_count = len(materials)

    raw_vertices = spec.get("vertices") or []
    raw_faces = spec.get("faces") or []
    if not isinstance(raw_vertices, list) or not isinstance(raw_faces, list):
        raise ValueError("STAGE072_VERTICES_FACES_LIST_REQUIRED")
    if len(raw_vertices) > MAX_VERTICES:
        raise ValueError(f"STAGE072_VERTEX_COUNT_LIMIT_{MAX_VERTICES}:{len(raw_vertices)}")
    if raw_faces and len(raw_vertices) < 3:
        raise ValueError("STAGE072_FACES_REQUIRE_VERTICES")
    scale = int(spec.get("coordinate_scale") or FIXED_SCALE)
    if scale <= 0 or scale > 1_000_000:
        raise ValueError("STAGE072_COORDINATE_SCALE_INVALID")
    fixed_coordinates = bool(spec.get("fixed_coordinates", False))
    vertices = [_fixed_vertex(row, scale, fixed_coordinates) for row in raw_vertices]

    faces: list[dict[str, Any]] = []
    tex_count = 0
    for fi, row in enumerate(raw_faces):
        if not isinstance(row, dict):
            raise ValueError(f"STAGE072_FACE_OBJECT_REQUIRED:{fi}")
        inds_raw = row.get("vertices")
        if not isinstance(inds_raw, (list, tuple)) or len(inds_raw) != 3:
            raise ValueError(f"STAGE072_FACE_TRIANGLE_REQUIRED:{fi}")
        inds = tuple(int(x) for x in inds_raw)
        if any(v < 0 or v >= len(vertices) for v in inds):
            raise ValueError(f"STAGE072_FACE_VERTEX_OOB:{fi}:{inds}")
        material = int(row.get("material") or 0)
        if mat_count:
            if not 0 <= material < mat_count:
                raise ValueError(f"STAGE072_FACE_MATERIAL_OOB:{fi}:{material}")
        elif material != 0:
            raise ValueError(f"STAGE072_FACE_MATERIAL_WITHOUT_GROUP:{fi}:{material}")
        layers_raw = row.get("uv_layers")
        if layers_raw is None and row.get("uv") is not None:
            layers_raw = [row.get("uv")]
        layers_raw = layers_raw or []
        if not isinstance(layers_raw, list) or len(layers_raw) > MAX_TEXLINKS_PER_FACE:
            raise ValueError(f"STAGE072_FACE_UV_LAYER_LIMIT_9:{fi}")
        layers = [_uv3(layer) for layer in layers_raw]
        if layers and not mat_count:
            raise ValueError(f"STAGE072_UV_REQUIRES_MATERIAL:{fi}")
        regular_texture_count = int((material_meta.get("materials") or [])[material].get("texture_count") or 0) if mat_count else 0
        if len(layers) > regular_texture_count:
            raise ValueError(f"STAGE072_FACE_UV_EXCEEDS_MATERIAL_TEXTURES:{fi}:{len(layers)}>{regular_texture_count}")
        normal_raw = row.get("normal")
        if normal_raw is None:
            normal = _source_face_normal(vertices, inds)
        else:
            if not isinstance(normal_raw, (list, tuple)) or len(normal_raw) not in (3, 4):
                raise ValueError(f"STAGE072_FACE_NORMAL_REQUIRED:{fi}")
            vals = [_i16(v, "FACE_NORMAL") for v in normal_raw]
            if len(vals) == 3:
                vals.append(0)
            normal = tuple(vals)
        faces.append({"vertices": inds, "material": material, "uv_layers": layers, "normal": normal})
        tex_count += len(layers)

    # Current source BuildAreaIndex is the safe default. Explicit NONE is useful for
    # visual-only fixtures, while EXPLICIT supports round-tripped authoring tools.
    area_mode = str(spec.get("area_mode") or "AUTO").strip().upper()
    if area_mode == "AUTO":
        areas = _auto_areas(vertices, faces)
    elif area_mode == "NONE":
        areas = {}
    elif area_mode == "EXPLICIT":
        areas = _explicit_areas(spec.get("areas") or [], len(faces))
    else:
        raise ValueError("STAGE072_AREA_MODE_MUST_BE_AUTO_NONE_OR_EXPLICIT")
    area_words = sum(1 + len(refs) for refs in areas.values())

    raw_lights = spec.get("lights") or []
    if not isinstance(raw_lights, list):
        raise ValueError("STAGE072_LIGHTS_LIST_REQUIRED")
    lights: list[tuple[int, int, int, int, int, int, int, int]] = []
    for li, row in enumerate(raw_lights):
        if not isinstance(row, dict):
            raise ValueError(f"STAGE072_LIGHT_OBJECT_REQUIRED:{li}")
        if isinstance(row.get("position"), (list, tuple)):
            px, py, pz = _vec3(row["position"], "LIGHT_POSITION")
        else:
            px, py, pz = float(row.get("x", 0)), float(row.get("y", 0)), float(row.get("z", 0))
        if not fixed_coordinates:
            px, py, pz = px * scale, py * scale, pz * scale
        color = row.get("color") or [row.get("r", 255), row.get("g", 255), row.get("b", 255)]
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            raise ValueError(f"STAGE072_LIGHT_COLOR_RGB_REQUIRED:{li}")
        lights.append((
            _i32(row.get("type") or 0, "LIGHT_TYPE"), _i32(round(px), "LIGHT_X"), _i32(round(py), "LIGHT_Y"), _i32(round(pz), "LIGHT_Z"),
            _i32(row.get("range") or 0, "LIGHT_RANGE"), _i16(color[0], "LIGHT_R"), _i16(color[1], "LIGHT_G"), _i16(color[2], "LIGHT_B"),
        ))

    file_header = bytearray(DFILE_HEADER_SIZE)
    file_header[:len(MAGIC)] = MAGIC
    struct.pack_into("<i", file_header, 28, mat_count)
    struct.pack_into("<i", file_header, 32, DFILE_HEADER_SIZE)
    struct.pack_into("<i", file_header, 36, DFILE_HEADER_SIZE + len(material_blob))

    stage = bytearray(STAGE_DISK_SIZE)
    # StageArea memory is x-major: StageArea[x][y]. Stream order is y-major then x-major.
    offset_words = 0
    for y in range(MAP_SIZE):
        for x in range(MAP_SIZE):
            refs = areas.get((x, y))
            if refs:
                struct.pack_into("<I", stage, 4 + (x * MAP_SIZE + y) * 4, AREA_BASE + offset_words * 4)
                offset_words += 1 + len(refs)
    if offset_words != area_words:
        raise AssertionError("STAGE072_AREA_WORD_COUNT_INTERNAL")
    struct.pack_into("<i", stage, S_MEM_MODE, _i32(spec.get("mem_mode") or 0, "MEM_MODE"))
    struct.pack_into("<I", stage, S_SUM_COUNT, int(spec.get("sum_count") or 0) & 0xFFFFFFFF)
    struct.pack_into("<i", stage, S_CALC_SUM_COUNT, _i32(spec.get("calc_sum_count") or 0, "CALC_SUM_COUNT"))
    struct.pack_into("<I", stage, S_TEXLINK_PTR, TEXLINK_BASE if tex_count else 0)
    struct.pack_into("<I", stage, S_MATERIAL_PTR, MATERIAL_BASE if mat_count else 0)
    struct.pack_into("<4i", stage, S_NVERTEX, len(vertices), len(faces), tex_count, len(lights))
    custom_colors = sum(1 for row in vertices if row[3] != (255, 255, 255, 255))
    struct.pack_into("<i", stage, S_NVERTCOLOR, custom_colors)
    struct.pack_into("<i", stage, S_CONTRAST, _i32(spec.get("contrast") or 0, "CONTRAST"))
    struct.pack_into("<i", stage, S_BRIGHT, _i32(spec.get("bright") or 0, "BRIGHT"))
    vect_light = spec.get("vect_light") or [0, 0, 0]
    if not isinstance(vect_light, (list, tuple)) or len(vect_light) != 3:
        raise ValueError("STAGE072_VECT_LIGHT_VEC3_REQUIRED")
    struct.pack_into("<3i", stage, S_VECTLIGHT, *[_i32(v, "VECT_LIGHT") for v in vect_light])
    struct.pack_into("<I", stage, S_AREA_BUFF_PTR, AREA_BASE if area_words else 0)
    struct.pack_into("<i", stage, S_WAREA_SIZE, area_words)
    if vertices:
        rect = [min(v[0] for v in vertices), min(v[2] for v in vertices), max(v[0] for v in vertices), max(v[2] for v in vertices)]
    else:
        rect = [0, 0, 0, 0]
    explicit_rect = spec.get("stage_map_rect")
    if explicit_rect is not None:
        if not isinstance(explicit_rect, (list, tuple)) or len(explicit_rect) != 4:
            raise ValueError("STAGE072_STAGE_MAP_RECT_REQUIRED")
        rect = [_i32(v, "STAGE_MAP_RECT") for v in explicit_rect]
    struct.pack_into("<4i", stage, S_STAGE_MAP_RECT, *rect)

    vb = bytearray()
    for x, y, z, color in vertices:
        vb += struct.pack("<IIiii4h", 0, 0, x, y, z, *color)
    fb = bytearray()
    tb = bytearray()
    next_link = 0
    for face in faces:
        layers = face["uv_layers"]
        first_token = TEXLINK_BASE + next_link * TEXLINK_SIZE if layers else 0
        a, b, c = face["vertices"]
        fb += struct.pack("<Ii4HI4h", 0, 0, a, b, c, face["material"], first_token, *face["normal"])
        for stage_idx, layer in enumerate(layers):
            us = [p[0] for p in layer]; vs = [p[1] for p in layer]
            next_token = TEXLINK_BASE + (next_link + 1) * TEXLINK_SIZE if stage_idx + 1 < len(layers) else 0
            htex = MATERIAL_BASE + face["material"] * MATERIAL_SIZE + 8 + stage_idx * 4
            tb += struct.pack("<3f3fII", *us, *vs, htex & 0xFFFFFFFF, next_token & 0xFFFFFFFF)
            next_link += 1
    if next_link != tex_count:
        raise AssertionError("STAGE072_TEXLINK_COUNT_INTERNAL")
    lb = bytearray()
    for light in lights:
        lb += struct.pack("<5i3h2x", *light)
    ab = bytearray()
    for y in range(MAP_SIZE):
        for x in range(MAP_SIZE):
            refs = areas.get((x, y))
            if refs:
                values = [len(refs), *refs]
                ab += struct.pack("<i", len(values))
                ab += struct.pack(f"<{len(values)}I", *values)

    data = bytes(file_header + stage + material_blob + vb + fb + tb + lb + ab)
    # Reuse the independent corpus parser as a semantic oracle for the exact bytes.
    with tempfile.TemporaryDirectory(prefix="pt_stage072_") as td:
        path = pathlib.Path(td) / "compiled.smd"
        path.write_bytes(data)
        from .stage072_corpus import parse_stage072
        parsed = parse_stage072(path, include_payload=False)
    if parsed.get("full_parse") != "PASS":
        raise AssertionError(f"STAGE072_INTERNAL_ROUNDTRIP_FAILED:{parsed.get('errors')}")
    used_materials = {int(k) for k, value in (parsed.get("material_face_counts") or {}).items() if int(value or 0) > 0}
    required_textures: list[str] = []
    seen_textures: set[str] = set()
    for mid, mat in enumerate(material_meta.get("materials") or []):
        if mid not in used_materials:
            continue
        for tex in list(mat.get("textures") or []) + list(mat.get("animated_textures") or []):
            name = str(tex.get("name") or "").strip().replace("\\", "/").lstrip("/")
            if name and name.casefold() not in seen_textures:
                seen_textures.add(name.casefold())
                required_textures.append(name)
    structural_validation = {
        "status": "PASS",
        "format": "SMD_STAGE_072",
        "counts": parsed.get("counts"),
        "full_parse": parsed.get("full_parse"),
        "used_material_ids": sorted(used_materials),
        "required_textures": required_textures,
        "profile": parsed.get("profile"),
        "area_encoding": (parsed.get("area") or {}).get("encoding"),
    }
    return data, {
        "writer": "SMD_STAGE_072_SOURCE_NATIVE_FROM_ZERO",
        "format": FORMAT,
        "byte_size": len(data),
        "sha256": _sha(data),
        "counts": parsed.get("counts"),
        "profile": parsed.get("profile"),
        "area_encoding": (parsed.get("area") or {}).get("encoding"),
        "area_mode": area_mode,
        "material_compiler": material_meta.get("writer"),
        "material_sha256": material_meta.get("sha256"),
        "semantic_roundtrip_valid": True,
        "structural_validation": structural_validation,
        "fixed_coordinate_scale": scale,
        "source_evidence": [
            "Shared/rendering/legacy_3d/stage/StageMeshBuilder.h",
            "Shared/rendering/legacy_3d/stage/StageAreaBuilder.h",
            "Shared/rendering/legacy_3d/stage/StageLighting.h",
            "Shared/rendering/legacy_3d/stage/LegacyStageDiskLayout.h",
            "Shared/rendering/legacy_3d/stage/LegacyStageSerialization.h",
            "Shared/rendering/legacy_3d/SmMap3dLegacyCommon.inl",
        ],
    }
