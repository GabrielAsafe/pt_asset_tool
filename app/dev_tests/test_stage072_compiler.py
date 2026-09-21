from pathlib import Path

import pytest

from pt_asset_tool.asset_compiler import BUNDLE_RECIPE_FORMAT, RECIPE_FORMAT, compile_asset_bundle, compile_asset_recipe, plan_asset_bundle, plan_asset_recipe
from pt_asset_tool.stage072_compiler import compile_stage072
from pt_asset_tool.stage072_corpus import parse_stage072


def _stage_payload() -> dict:
    return {
        "materials": [
            {
                "textures": ["field/ground.bmp", "field/detail.bmp"],
                "texture_stage_state": [4, 7],
                "texture_form_state": [0, 4],
                "two_side": True,
            }
        ],
        "vertices": [
            {"position": [0, 0, 0], "color": [255, 255, 255, 255]},
            {"position": [64, 0, 0], "color": [220, 210, 200, 255]},
            [0, 0, 64],
        ],
        "faces": [
            {
                "vertices": [0, 2, 1],
                "material": 0,
                "uv_layers": [
                    [[0, 0], [0, 1], [1, 0]],
                    [[0.1, 0.1], [0.1, 0.9], [0.9, 0.1]],
                ],
            }
        ],
        "lights": [{"type": 1, "position": [32, 16, 32], "range": 400, "color": [255, 220, 180]}],
        "contrast": 1,
        "bright": 256,
        "vect_light": [0, -32767, 0],
    }


def test_stage072_native_writer_roundtrips_with_areas_materials_uv_and_lights(tmp_path: Path):
    data, meta = compile_stage072(_stage_payload())
    path = tmp_path / "native.smd"
    path.write_bytes(data)
    parsed = parse_stage072(path, include_payload=True)

    assert parsed["full_parse"] == "PASS"
    assert parsed["counts"]["materials"] == 1
    assert parsed["counts"]["vertices"] == 3
    assert parsed["counts"]["faces"] == 1
    assert parsed["counts"]["texlinks"] == 2
    assert parsed["counts"]["lights"] == 1
    assert parsed["counts"]["active_area_cells"] == 4
    assert parsed["area"]["encoding"] == "DWORD32"
    assert parsed["max_texlink_depth"] == 2
    assert parsed["uv_distinct_multilayer_faces"] == 1
    assert parsed["materials"][0]["TextureStageState"][:2] == [4, 7]
    assert parsed["materials"][0]["TextureFormState"][:2] == [0, 4]
    assert meta["writer"] == "SMD_STAGE_072_SOURCE_NATIVE_FROM_ZERO"
    assert meta["semantic_roundtrip_valid"] is True


def test_stage072_native_writer_supports_no_material_visual_only_geometry(tmp_path: Path):
    data, _meta = compile_stage072({
        "materials": [],
        "vertices": [[0, 0, 0], [64, 0, 0], [0, 0, 64]],
        "faces": [{"vertices": [0, 2, 1], "material": 0}],
        "area_mode": "NONE",
    })
    path = tmp_path / "plain.smd"
    path.write_bytes(data)
    parsed = parse_stage072(path)
    assert parsed["full_parse"] == "PASS"
    assert parsed["counts"]["materials"] == 0
    assert parsed["counts"]["texlinks"] == 0
    assert parsed["area"]["encoding"] == "NONE"


def test_stage072_native_writer_rejects_uv_stage_without_material_texture():
    payload = _stage_payload()
    payload["materials"][0]["textures"] = ["field/ground.bmp"]
    with pytest.raises(ValueError, match="UV_EXCEEDS_MATERIAL_TEXTURES"):
        compile_stage072(payload)


def test_stage072_asset_compiler_dispatches_native_payload(tmp_path: Path):
    recipe = {
        "format": RECIPE_FORMAT,
        "id": "native_field",
        "contract_id": "stage.smd.072",
        "target_side": "CLIENT",
        "output": "field/native.smd",
        "payload": _stage_payload(),
    }
    plan = plan_asset_recipe(recipe)
    assert plan["status"] == "READY", plan["errors"]
    assert plan["preview"]["writer"]["writer"] == "SMD_STAGE_072_SOURCE_NATIVE_FROM_ZERO"
    build = compile_asset_recipe(tmp_path, recipe)
    parsed = parse_stage072(Path(build["output"]))
    assert parsed["full_parse"] == "PASS"


def test_native_stage_closes_field_bundle_against_live_texture_dependencies(tmp_path: Path):
    client = tmp_path / "client"
    server = tmp_path / "server"
    server.mkdir()
    for rel in ("field/ground.bmp", "field/detail.bmp"):
        target = client / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"texture-present")
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "native_stage_bundle",
        "bundle_type": "FIELD",
        "payload": {
            "stage_asset": {
                "output": "field/native/native.smd",
                **_stage_payload(),
            }
        },
    }
    plan = plan_asset_bundle(recipe, client_root=client, server_root=server)
    assert plan["status"] == "READY", plan["errors"]
    assert sorted(
        x["path"] for x in plan["visual_dependency"]["closure"] if x.get("role") == "stage_texture"
    ) == ["field/detail.bmp", "field/ground.bmp"]
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    stage = next(x for x in build["assets"] if x.get("contract_id") == "stage.smd.072")
    assert stage["writer"]["writer"] == "SMD_STAGE_072_SOURCE_NATIVE_FROM_ZERO"
    assert stage["binding_evidence"]["graph"] == "FIELD_STAGE_CLOSURE"
