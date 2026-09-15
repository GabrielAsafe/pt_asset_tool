from __future__ import annotations

import argparse
import json
import pathlib
import sys

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pt_asset_tool.stage072_corpus import parse_stage072

UV_PREFIX = "PT_STAGE072_TEXLINK_STAGE_"
COLOR_NAME = "PT_STAGE072_VERTEX_COLOR"


def args(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--smd", required=True)
    ap.add_argument("--report", required=True)
    return ap.parse_args(argv)


def main(argv):
    a = args(argv)
    source = pathlib.Path(a.smd).resolve()
    report_path = pathlib.Path(a.report).resolve()
    parsed = parse_stage072(source, include_payload=True)
    payload = parsed["payload"]

    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.get("pt_stage072_source_sha256")]
    if len(meshes) != 1:
        raise RuntimeError(f"expected one Stage0.72 mesh, got {len(meshes)}")
    obj = meshes[0]
    mesh = obj.data
    errors = []
    max_pos_error = 0.0
    max_uv_error = 0.0
    max_color_error = 0.0

    if obj.get("pt_stage072_source_sha256") != parsed["sha256"]:
        errors.append("source sha metadata mismatch")
    if len(mesh.vertices) != len(payload["vertices"]):
        errors.append(f"vertex count {len(mesh.vertices)} != {len(payload['vertices'])}")
    if len(mesh.polygons) != len(payload["faces"]):
        errors.append(f"face count {len(mesh.polygons)} != {len(payload['faces'])}")

    for i, (v, src) in enumerate(zip(mesh.vertices, payload["vertices"])):
        expected = (src["x"] / 256.0, src["y"] / 256.0, src["z"] / 256.0)
        err = max(abs(float(v.co[j]) - expected[j]) for j in range(3))
        max_pos_error = max(max_pos_error, err)
        if err > 1e-6 and len(errors) < 20:
            errors.append(f"vertex {i} position mismatch {err}")

    depth_attr = mesh.attributes.get("PT_STAGE072_TEXLINK_DEPTH")
    mid_attr = mesh.attributes.get("PT_STAGE072_MATERIAL_ID")
    if depth_attr is None or mid_attr is None:
        errors.append("missing Stage0.72 face attributes")
    for i, (poly, srcf) in enumerate(zip(mesh.polygons, payload["faces"])):
        if tuple(poly.vertices) != tuple(srcf["vertices"]) and len(errors) < 20:
            errors.append(f"face {i} vertex order mismatch")
        if depth_attr is not None and int(depth_attr.data[i].value) != len(srcf.get("texlink_chain") or []) and len(errors) < 20:
            errors.append(f"face {i} depth mismatch")
        if mid_attr is not None and int(mid_attr.data[i].value) != int(srcf["material"]) and len(errors) < 20:
            errors.append(f"face {i} material id mismatch")
        if poly.material_index >= len(mesh.materials):
            errors.append(f"face {i} invalid material slot")
        else:
            mat = mesh.materials[poly.material_index]
            if int(mat.get("pt_stage072_material_id", -1)) != int(srcf["material"]) and len(errors) < 20:
                errors.append(f"face {i} material slot source-id mismatch")

        for stage, ti in enumerate(srcf.get("texlink_chain") or []):
            layer = mesh.uv_layers.get(f"{UV_PREFIX}{stage}")
            if layer is None:
                errors.append(f"missing UV stage {stage}")
                continue
            tl = payload["texlinks"][ti]
            for corner, li in enumerate(poly.loop_indices):
                expected = (float(tl["u"][corner]), 1.0 - float(tl["v"][corner]))
                got = layer.data[li].uv
                err = max(abs(float(got[0])-expected[0]), abs(float(got[1])-expected[1]))
                max_uv_error = max(max_uv_error, err)
                if err > 2e-6 and len(errors) < 20:
                    errors.append(f"face {i} stage {stage} corner {corner} UV mismatch {err}")

    colors = mesh.color_attributes.get(COLOR_NAME)
    if colors is None:
        errors.append("missing vertex color attribute")
    else:
        for i, src in enumerate(payload["vertices"]):
            expected = tuple(max(0.0, min(1.0, float(x)/255.0)) for x in src["color"])
            got = colors.data[i].color
            err = max(abs(float(got[j])-expected[j]) for j in range(4))
            max_color_error = max(max_color_error, err)
            if err > 2e-6 and len(errors) < 20:
                errors.append(f"vertex {i} color mismatch {err}")

    lights = sorted([o for o in bpy.data.objects if o.name.startswith("PT_STAGE072_LIGHT_")], key=lambda x: x.name)
    if len(lights) != len(payload["lights"]):
        errors.append(f"light metadata count {len(lights)} != {len(payload['lights'])}")
    for i, (objl, src) in enumerate(zip(lights, payload["lights"])):
        expected_pos = (src["x"]/256.0, src["y"]/256.0, src["z"]/256.0)
        if max(abs(float(objl.location[j])-expected_pos[j]) for j in range(3)) > 1e-6 and len(errors) < 20:
            errors.append(f"light {i} position mismatch")
        for key in ("type", "x", "y", "z", "range", "r", "g", "b"):
            if int(objl.get(f"pt_stage072_{key}", -999999999)) != int(src[key]) and len(errors) < 20:
                errors.append(f"light {i} metadata {key} mismatch")

    # Verify material stage metadata against every material actually used.
    expected_depth = {}
    for f in payload["faces"]:
        mid = int(f["material"])
        expected_depth[mid] = max(expected_depth.get(mid, 0), len(f.get("texlink_chain") or []))
    mats_by_id = {int(m.get("pt_stage072_material_id", -1)): m for m in mesh.materials if m is not None}
    src_by_id = {int(m["id"]): m for m in parsed["materials"]}
    for mid, depth in expected_depth.items():
        mat = mats_by_id.get(mid)
        if mat is None:
            errors.append(f"missing used material {mid}")
            continue
        src = src_by_id[mid]
        for stage in range(depth):
            logical = (src.get("textures") or [])[stage].get("Name") if stage < len(src.get("textures") or []) else ""
            op = int((src.get("TextureStageState") or [0]*8)[stage])
            form = int((src.get("TextureFormState") or [0]*8)[stage])
            if str(mat.get(f"pt_stage072_stage{stage}_texture", "")) != str(logical or "") and len(errors) < 20:
                errors.append(f"material {mid} stage {stage} texture metadata mismatch")
            if int(mat.get(f"pt_stage072_stage{stage}_op", -1)) != op and len(errors) < 20:
                errors.append(f"material {mid} stage {stage} op metadata mismatch")
            if int(mat.get(f"pt_stage072_stage{stage}_form", -1)) != form and len(errors) < 20:
                errors.append(f"material {mid} stage {stage} form metadata mismatch")

    report = {
        "format": "PT_STAGE072_BLENDER_TRANSPORT_CHECK_V1",
        "check": "PASS" if not errors else "FAIL",
        "source": str(source),
        "source_sha256": parsed["sha256"],
        "vertices": len(mesh.vertices),
        "faces": len(mesh.polygons),
        "loops": len(mesh.loops),
        "max_texlink_depth": int(parsed["max_texlink_depth"]),
        "max_position_abs_error": max_pos_error,
        "max_uv_abs_error": max_uv_error,
        "max_color_abs_error": max_color_error,
        "light_metadata_count": len(lights),
        "errors": errors,
        "client_modified": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise RuntimeError(f"Stage0.72 persisted transport failed: {errors[:5]}")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    main(argv)
