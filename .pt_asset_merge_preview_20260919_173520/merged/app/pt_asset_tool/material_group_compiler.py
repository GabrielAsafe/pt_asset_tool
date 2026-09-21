from __future__ import annotations

import hashlib
import math
import struct
from typing import Any

FORMAT = "PT_LEGACY_MATERIAL_GROUP_WIN32_COMPILER_V1"
GROUP_SIZE = 88
MATERIAL_SIZE = 320
MAX_MATERIALS = 5000
MAX_TEXTURES = 8
MAX_ANIM_TEXTURES = 32
MAX_TEXTURE_NAME_BYTES = 63
SCHEMA_MAX_SERIALIZED_NAME_BYTES = (MAX_TEXTURES + MAX_ANIM_TEXTURES) * 2 * 64  # 5120
# Both active legacy client and server LoadFile() implementations use a fixed
# char szNameBuff[4096].  Authoring must stay within the runtime consumer, even
# though the modern serialization helper can describe the theoretical 5120 max.
RUNTIME_MAX_SERIALIZED_NAME_BYTES = 4096


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _float3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"MATERIAL_{label}_VEC3_REQUIRED")
    out = tuple(float(x) for x in value)
    if not all(math.isfinite(x) for x in out):
        raise ValueError(f"MATERIAL_{label}_FINITE_REQUIRED")
    return out  # type: ignore[return-value]


def _u32(value: Any, label: str) -> int:
    out = int(value)
    if not 0 <= out <= 0xFFFFFFFF:
        raise ValueError(f"MATERIAL_{label}_UINT32_REQUIRED:{out}")
    return out


def _i32(value: Any, label: str) -> int:
    out = int(value)
    if not -(2**31) <= out < 2**31:
        raise ValueError(f"MATERIAL_{label}_INT32_REQUIRED:{out}")
    return out


def _texture_pair(row: Any, material_index: int) -> tuple[str, str]:
    if isinstance(row, str):
        name, alpha = row, ""
    elif isinstance(row, dict):
        name, alpha = str(row.get("name") or ""), str(row.get("alpha") or "")
    else:
        raise ValueError(f"MATERIAL_TEXTURE_OBJECT_OR_STRING:{material_index}")
    name_raw = name.encode("cp949")
    alpha_raw = alpha.encode("cp949")
    if not name_raw or len(name_raw) > MAX_TEXTURE_NAME_BYTES or len(alpha_raw) > MAX_TEXTURE_NAME_BYTES:
        raise ValueError(f"MATERIAL_TEXTURE_NAME_INVALID:{material_index}:{name}")
    return name, alpha


def compile_material_group(materials: list[dict[str, Any]]) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(materials, list) or not 0 <= len(materials) <= MAX_MATERIALS:
        raise ValueError("MATERIAL_COUNT_0_TO_5000_REQUIRED")
    if not materials:
        return b"", {
            "writer": "LEGACY_MATERIAL_GROUP_WIN32_SOURCE_NATIVE",
            "format": FORMAT,
            "material_count": 0,
            "byte_size": 0,
            "semantic_roundtrip_valid": True,
            "runtime_name_buffer_limit": RUNTIME_MAX_SERIALIZED_NAME_BYTES,
            "materials": [],
            "sha256": _sha(b""),
        }

    group = bytearray(GROUP_SIZE)
    struct.pack_into("<I", group, 0, 0)  # Head
    struct.pack_into("<I", group, 4, 0)  # smMaterial runtime pointer, never disk authority
    struct.pack_into("<I", group, 8, len(materials))
    struct.pack_into("<i", group, 12, 0)  # ReformTexture patched after rows
    struct.pack_into("<i", group, 16, len(materials))
    struct.pack_into("<i", group, 20, 0)
    out = bytearray(group)
    reform_count = 0
    meta_rows: list[dict[str, Any]] = []

    for idx, spec in enumerate(materials):
        if not isinstance(spec, dict):
            raise ValueError(f"MATERIAL_OBJECT_REQUIRED:{idx}")
        textures = spec.get("textures") or []
        animated = spec.get("animated_textures") or []
        if not isinstance(textures, list) or len(textures) > MAX_TEXTURES:
            raise ValueError(f"MATERIAL_TEXTURE_LIMIT_8:{idx}")
        if not isinstance(animated, list) or len(animated) > MAX_ANIM_TEXTURES:
            raise ValueError(f"MATERIAL_ANIM_TEXTURE_LIMIT_32:{idx}")

        in_use = bool(spec.get("in_use", True))
        if (textures or animated) and not in_use:
            raise ValueError(f"MATERIAL_TEXTURE_REQUIRES_IN_USE:{idx}")

        rec = bytearray(MATERIAL_SIZE)
        struct.pack_into("<I", rec, 0, 1 if in_use else 0)
        struct.pack_into("<I", rec, 4, len(textures))
        # smTexture[8] and smAnimTexture[32] remain zero deterministically.
        stage_states = list(spec.get("texture_stage_state") or [])
        form_states = list(spec.get("texture_form_state") or [])
        if len(stage_states) > MAX_TEXTURES:
            raise ValueError(f"MATERIAL_TEXTURE_STAGE_STATE_LIMIT_8:{idx}")
        if len(form_states) > MAX_TEXTURES:
            raise ValueError(f"MATERIAL_TEXTURE_FORM_STATE_LIMIT_8:{idx}")
        for stage_idx, value in enumerate(stage_states):
            struct.pack_into("<i", rec, 40 + stage_idx * 4, _i32(value, "TEXTURE_STAGE_STATE"))
        for stage_idx, value in enumerate(form_states):
            struct.pack_into("<i", rec, 72 + stage_idx * 4, _i32(value, "TEXTURE_FORM_STATE"))
        reform = _i32(spec.get("reform_texture") or 0, "REFORM_TEXTURE")
        struct.pack_into("<i", rec, 104, reform)
        struct.pack_into("<i", rec, 108, _i32(spec.get("map_opacity") or 0, "MAP_OPACITY"))
        struct.pack_into("<I", rec, 112, _u32(spec.get("texture_type") or 0, "TEXTURE_TYPE"))
        blend = spec.get("blend_type") if spec.get("blend_type") is not None else 1
        struct.pack_into("<I", rec, 116, _u32(blend, "BLEND_TYPE"))
        struct.pack_into("<I", rec, 120, 1 if bool(spec.get("shade", True)) else 0)
        struct.pack_into("<I", rec, 124, 1 if bool(spec.get("two_side", False)) else 0)
        struct.pack_into("<I", rec, 128, _u32(spec.get("serial") if spec.get("serial") is not None else idx, "SERIAL"))
        diffuse = _float3(spec.get("diffuse") or [1.0, 1.0, 1.0], "DIFFUSE")
        struct.pack_into("<3f", rec, 132, *diffuse)
        transparency = float(spec.get("transparency") or 0.0)
        self_illum = float(spec.get("self_illum") or 0.0)
        if not math.isfinite(transparency) or not 0.0 <= transparency <= 1.0:
            raise ValueError(f"MATERIAL_TRANSPARENCY_INVALID:{idx}")
        if not math.isfinite(self_illum):
            raise ValueError(f"MATERIAL_SELF_ILLUM_INVALID:{idx}")
        struct.pack_into("<f", rec, 144, transparency)
        struct.pack_into("<f", rec, 148, self_illum)
        struct.pack_into("<i", rec, 152, _i32(spec.get("texture_swap") or 0, "TEXTURE_SWAP"))
        struct.pack_into("<i", rec, 156, _i32(spec.get("mat_frame") or 0, "MAT_FRAME"))
        struct.pack_into("<i", rec, 160, _i32(spec.get("texture_clip") or 0, "TEXTURE_CLIP"))
        struct.pack_into("<i", rec, 164, _i32(spec.get("use_state") or 0, "USE_STATE"))
        struct.pack_into("<i", rec, 168, _i32(spec.get("mesh_state") or 0, "MESH_STATE"))
        struct.pack_into("<i", rec, 172, _i32(spec.get("wind_mesh_bottom") or 0, "WIND_MESH_BOTTOM"))
        struct.pack_into("<I", rec, 304, len(animated))
        struct.pack_into("<I", rec, 308, _u32(spec.get("frame_mask") or 0, "FRAME_MASK"))
        struct.pack_into("<I", rec, 312, _u32(spec.get("shift_frame_speed") or 0, "SHIFT_FRAME_SPEED"))
        struct.pack_into("<I", rec, 316, _u32(spec.get("animation_frame") or 0, "ANIMATION_FRAME"))
        out += rec

        names = bytearray()
        normalized_regular: list[dict[str, str]] = []
        normalized_animated: list[dict[str, str]] = []
        if in_use:
            for target, row in [(normalized_regular, x) for x in textures] + [(normalized_animated, x) for x in animated]:
                name, alpha = _texture_pair(row, idx)
                names += name.encode("cp949") + b"\0" + alpha.encode("cp949") + b"\0"
                target.append({"name": name.replace("\\", "/"), "alpha": alpha.replace("\\", "/")})
            if len(names) > RUNTIME_MAX_SERIALIZED_NAME_BYTES:
                raise ValueError(
                    f"MATERIAL_NAME_PAYLOAD_RUNTIME_LIMIT_{RUNTIME_MAX_SERIALIZED_NAME_BYTES}:{idx}:{len(names)}"
                )
            out += struct.pack("<i", len(names)) + names

        if reform:
            reform_count += 1
        meta_rows.append({
            "index": idx,
            "in_use": in_use,
            "texture_count": len(textures),
            "animated_texture_count": len(animated),
            "textures": normalized_regular,
            "animated_textures": normalized_animated,
            "serialized_name_bytes": len(names),
            "reform_texture": reform,
            "texture_stage_state": [int(x) for x in stage_states],
            "texture_form_state": [int(x) for x in form_states],
        })

    struct.pack_into("<i", out, 12, reform_count)
    data = bytes(out)
    inspected = inspect_material_group(data, expected_count=len(materials))
    if not inspected["valid"]:
        raise AssertionError("MATERIAL_GROUP_INTERNAL_ROUNDTRIP_FAILED")
    return data, {
        "writer": "LEGACY_MATERIAL_GROUP_WIN32_SOURCE_NATIVE",
        "format": FORMAT,
        "material_count": len(materials),
        "reform_texture_count": reform_count,
        "byte_size": len(data),
        "semantic_roundtrip_valid": True,
        "runtime_name_buffer_limit": RUNTIME_MAX_SERIALIZED_NAME_BYTES,
        "schema_name_payload_limit": SCHEMA_MAX_SERIALIZED_NAME_BYTES,
        "materials": meta_rows,
        "sha256": _sha(data),
        "source_evidence": [
            "Shared/rendering/legacy_3d/material/LegacyMaterialSerialization.h",
            "Shared/rendering/legacy_3d/material/smTexture_legacy_client.inl",
            "Shared/rendering/legacy_3d/material/smTexture_legacy_server.inl",
            "SrcGame/src/systems/rendering/legacy_3d/smTexture.h",
        ],
    }


def _read_cstring(payload: bytes, cursor: int, end: int) -> tuple[str, int]:
    if cursor >= end:
        raise ValueError("MATERIAL_NAME_PAYLOAD_TRUNCATED")
    stop = payload.find(b"\0", cursor, end)
    if stop < 0:
        raise ValueError("MATERIAL_NAME_UNTERMINATED")
    raw = payload[cursor:stop]
    if len(raw) > MAX_TEXTURE_NAME_BYTES:
        raise ValueError("MATERIAL_NAME_EXCEEDS_63_BYTES")
    try:
        text = raw.decode("cp949")
    except UnicodeDecodeError as exc:
        raise ValueError(f"MATERIAL_NAME_NOT_CP949:{exc}") from exc
    return text, stop + 1


def inspect_material_group(data: bytes, *, expected_count: int | None = None) -> dict[str, Any]:
    if not data:
        return {
            "format": FORMAT,
            "material_count": 0,
            "reform_texture_count": 0,
            "max_material": 0,
            "last_search_material": 0,
            "materials": [],
            "byte_size": 0,
            "valid": expected_count in (None, 0),
            "errors": [] if expected_count in (None, 0) else [f"MATERIAL_COUNT_MISMATCH:0:{expected_count}"],
        }
    if len(data) < GROUP_SIZE:
        raise ValueError("MATERIAL_GROUP_TRUNCATED")

    material_count = struct.unpack_from("<I", data, 8)[0]
    reform_count = struct.unpack_from("<i", data, 12)[0]
    max_material = struct.unpack_from("<i", data, 16)[0]
    last_search = struct.unpack_from("<i", data, 20)[0]
    errors: list[str] = []
    if material_count > MAX_MATERIALS:
        errors.append(f"MATERIAL_COUNT_LIMIT:{material_count}")
    if not 0 <= max_material <= MAX_MATERIALS or material_count > max_material:
        errors.append(f"MATERIAL_MAX_INVALID:{material_count}:{max_material}")
    if expected_count is not None and material_count != int(expected_count):
        errors.append(f"MATERIAL_COUNT_MISMATCH:{material_count}:{expected_count}")

    cursor = GROUP_SIZE
    rows: list[dict[str, Any]] = []
    observed_reform = 0
    for idx in range(min(material_count, MAX_MATERIALS)):
        if cursor + MATERIAL_SIZE > len(data):
            errors.append(f"MATERIAL_RECORD_TRUNCATED:{idx}")
            break
        rec_start = cursor
        in_use = struct.unpack_from("<I", data, rec_start)[0]
        texture_count = struct.unpack_from("<I", data, rec_start + 4)[0]
        anim_count = struct.unpack_from("<I", data, rec_start + 304)[0]
        reform = struct.unpack_from("<i", data, rec_start + 104)[0]
        if texture_count > MAX_TEXTURES:
            errors.append(f"MATERIAL_TEXTURE_COUNT_INVALID:{idx}:{texture_count}")
        if anim_count > MAX_ANIM_TEXTURES:
            errors.append(f"MATERIAL_ANIM_COUNT_INVALID:{idx}:{anim_count}")
        cursor += MATERIAL_SIZE

        regular: list[dict[str, str]] = []
        animated: list[dict[str, str]] = []
        serialized_name_bytes = 0
        if in_use:
            if cursor + 4 > len(data):
                errors.append(f"MATERIAL_NAME_LENGTH_TRUNCATED:{idx}")
                break
            serialized_name_bytes = struct.unpack_from("<i", data, cursor)[0]
            cursor += 4
            if serialized_name_bytes < 0 or cursor + serialized_name_bytes > len(data):
                errors.append(f"MATERIAL_NAME_LENGTH_INVALID:{idx}:{serialized_name_bytes}")
                break
            if serialized_name_bytes > RUNTIME_MAX_SERIALIZED_NAME_BYTES:
                errors.append(f"MATERIAL_NAME_RUNTIME_LIMIT:{idx}:{serialized_name_bytes}")
            payload_end = cursor + serialized_name_bytes
            try:
                for target, count in ((regular, min(texture_count, MAX_TEXTURES)), (animated, min(anim_count, MAX_ANIM_TEXTURES))):
                    for _ in range(count):
                        name, cursor = _read_cstring(data, cursor, payload_end)
                        alpha, cursor = _read_cstring(data, cursor, payload_end)
                        target.append({"name": name, "alpha": alpha})
                if cursor != payload_end:
                    errors.append(f"MATERIAL_NAME_PAYLOAD_TRAILING_BYTES:{idx}:{payload_end-cursor}")
                cursor = payload_end
            except ValueError as exc:
                errors.append(f"MATERIAL_NAME_PARSE:{idx}:{exc}")
                cursor = payload_end
        elif texture_count or anim_count:
            errors.append(f"MATERIAL_UNUSED_HAS_TEXTURES:{idx}")

        if reform:
            observed_reform += 1
        rows.append({
            "index": idx,
            "in_use": bool(in_use),
            "texture_count": texture_count,
            "animated_texture_count": anim_count,
            "textures": regular,
            "animated_textures": animated,
            "serialized_name_bytes": serialized_name_bytes,
            "reform_texture": reform,
            "texture_type": struct.unpack_from("<I", data, rec_start + 112)[0],
            "blend_type": struct.unpack_from("<I", data, rec_start + 116)[0],
            "shade": struct.unpack_from("<I", data, rec_start + 120)[0],
            "two_side": struct.unpack_from("<I", data, rec_start + 124)[0],
            "serial": struct.unpack_from("<I", data, rec_start + 128)[0],
            "diffuse": struct.unpack_from("<3f", data, rec_start + 132),
            "transparency": struct.unpack_from("<f", data, rec_start + 144)[0],
            "self_illum": struct.unpack_from("<f", data, rec_start + 148)[0],
            "pointers_zero": (
                data[rec_start + 8:rec_start + 40] == b"\0" * 32
                and data[rec_start + 176:rec_start + 304] == b"\0" * 128
            ),
        })

    if cursor != len(data):
        errors.append(f"MATERIAL_GROUP_TRAILING_BYTES:{len(data)-cursor}")
    if reform_count != observed_reform:
        errors.append(f"MATERIAL_REFORM_COUNT_MISMATCH:{reform_count}:{observed_reform}")

    return {
        "format": FORMAT,
        "material_count": material_count,
        "reform_texture_count": reform_count,
        "max_material": max_material,
        "last_search_material": last_search,
        "materials": rows,
        "byte_size": len(data),
        "runtime_name_buffer_limit": RUNTIME_MAX_SERIALIZED_NAME_BYTES,
        "errors": errors,
        "valid": not errors,
    }
