import pytest

from pt_asset_tool.material_group_compiler import (
    RUNTIME_MAX_SERIALIZED_NAME_BYTES,
    compile_material_group,
    inspect_material_group,
)
from pt_asset_tool.model062_static_compiler import compile_static_model062


def test_material_group_native_roundtrip_regular_animated_and_alpha_names():
    data, meta = compile_material_group([
        {
            "textures": [
                "image/monster/test/diffuse.tga",
                {"name": "image/monster/test/detail.bmp", "alpha": "image/monster/test/detail_a.bmp"},
            ],
            "animated_textures": [
                {"name": "image/effect/fire01.tga", "alpha": ""},
                {"name": "image/effect/fire02.tga", "alpha": "image/effect/fire02a.tga"},
            ],
            "two_side": True,
            "blend_type": 3,
            "reform_texture": 1,
            "transparency": 0.25,
        },
        {"in_use": False},
    ])
    assert meta["writer"] == "LEGACY_MATERIAL_GROUP_WIN32_SOURCE_NATIVE"
    assert meta["semantic_roundtrip_valid"] is True
    assert meta["runtime_name_buffer_limit"] == 4096

    parsed = inspect_material_group(data, expected_count=2)
    assert parsed["valid"] is True, parsed["errors"]
    assert parsed["material_count"] == 2
    assert parsed["reform_texture_count"] == 1
    first = parsed["materials"][0]
    assert first["texture_count"] == 2
    assert first["animated_texture_count"] == 2
    assert first["textures"][1] == {
        "name": "image/monster/test/detail.bmp",
        "alpha": "image/monster/test/detail_a.bmp",
    }
    assert first["animated_textures"][1]["alpha"] == "image/effect/fire02a.tga"
    assert first["pointers_zero"] is True
    assert parsed["materials"][1]["in_use"] is False


def test_material_group_blocks_payload_larger_than_runtime_loader_buffer():
    # 32 animated texture pairs can fit the schema's 5120-byte theoretical cap,
    # but active legacy loaders read into char szNameBuff[4096].
    row = {"name": "a" * 63, "alpha": "b" * 63}
    with pytest.raises(ValueError, match="RUNTIME_LIMIT_4096"):
        compile_material_group([{"textures": [row] * 8, "animated_textures": [row] * 32}])
    assert RUNTIME_MAX_SERIALIZED_NAME_BYTES == 4096


def test_model062_static_uses_reusable_native_material_compiler():
    data, meta = compile_static_model062({
        "mesh": {
            "materials": [{"textures": ["image/test/d.tga"]}],
            "objects": [{
                "name": "body",
                "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                "faces": [{"vertices": [0, 1, 2], "material": 0, "uv": [[0, 0], [1, 0], [0, 1]]}],
            }],
        }
    })
    assert data.startswith(b"SMD Model data Ver 0.62")
    assert meta["material_compiler"] == "LEGACY_MATERIAL_GROUP_WIN32_SOURCE_NATIVE"
    assert meta["materials"][0]["textures"][0]["name"] == "image/test/d.tga"
