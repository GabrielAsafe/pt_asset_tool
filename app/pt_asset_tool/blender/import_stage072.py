from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pt_asset_tool.stage072_corpus import parse_stage072, FORM_NAMES, STAGE_OP_NAMES

UV_PREFIX = "PT_STAGE072_TEXLINK_STAGE_"
COLOR_NAME = "PT_STAGE072_VERTEX_COLOR"


def parse_args(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--smd", required=True)
    ap.add_argument("--client-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--pack", action="store_true")
    return ap.parse_args(argv)


def norm_texture(name: str) -> pathlib.PurePosixPath:
    return pathlib.PurePosixPath(str(name or "").replace("\\", "/").lstrip("/"))


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        # Keep loaded images until after materials are rebuilt; stale datablocks
        # do not affect transport checks, but removing them makes reruns cleaner.
        pass


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "NO_TEXTURE")[:80]


def load_image(client_root: pathlib.Path, logical: str):
    if not logical:
        return None, "NO_TEXTURE"
    p = client_root / norm_texture(logical)
    if not p.is_file():
        return None, "MISSING"
    try:
        image = bpy.data.images.load(str(p), check_existing=False)
        image.reload()
        if int(image.size[0]) <= 0 or int(image.size[1]) <= 0:
            raise RuntimeError(f"invalid image size {tuple(image.size)}")
        try:
            image.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        return image, "LOADED"
    except Exception as exc:
        return None, f"LOAD_ERROR:{type(exc).__name__}:{exc}"


def material_depths(parsed: dict) -> dict[int, int]:
    out: dict[int, int] = {}
    for face in parsed["payload"]["faces"]:
        mid = int(face["material"])
        out[mid] = max(out.get(mid, 0), len(face.get("texlink_chain") or []))
    return out


def create_material(src: dict, depth: int, client_root: pathlib.Path, *, pack: bool):
    label = ""
    if src.get("textures"):
        label = pathlib.PureWindowsPath(src["textures"][0].get("Name") or "").name
    mat = bpy.data.materials.new(name=f"PT_STAGE072_MAT_{int(src['id']):04d}_{safe_name(label)}")
    mat.use_nodes = True
    mat["pt_stage072_material_id"] = int(src["id"])
    mat["pt_stage072_texture_counter"] = int(src.get("TextureCounter") or 0)
    mat["pt_stage072_anim_texture_counter"] = int(src.get("AnimTexCounter") or 0)
    mat["pt_stage072_two_side"] = int(src.get("TwoSide") or 0)
    mat["pt_stage072_blend_type"] = int(src.get("BlendType") or 0)
    mat["pt_stage072_shade"] = int(src.get("Shade") or 0)
    mat["pt_stage072_transparency"] = float(src.get("Transparency") or 0.0)
    mat["pt_stage072_self_illum"] = float(src.get("SelfIllum") or 0.0)
    mat["pt_stage072_preview_semantics"] = "FRAME0_STATIC_TEXTURE_COMBINER"
    runtime_renderable = bool(int(src.get("TextureCounter") or 0) or int(src.get("AnimTexCounter") or 0))
    mat["pt_stage072_runtime_renderable"] = int(runtime_renderable)

    if hasattr(mat, "use_backface_culling"):
        try:
            mat.use_backface_culling = not bool(src.get("TwoSide"))
        except Exception:
            pass

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.8

    stage_colors = []
    loads = []
    for stage in range(depth):
        textures = src.get("textures") or []
        logical = textures[stage].get("Name") if stage < len(textures) else ""
        op = int((src.get("TextureStageState") or [0] * 8)[stage])
        form = int((src.get("TextureFormState") or [0] * 8)[stage])
        mat[f"pt_stage072_stage{stage}_texture"] = str(logical or "")
        mat[f"pt_stage072_stage{stage}_op"] = op
        mat[f"pt_stage072_stage{stage}_form"] = form
        mat[f"pt_stage072_stage{stage}_op_name"] = STAGE_OP_NAMES.get(op, f"UNKNOWN_{op}")
        mat[f"pt_stage072_stage{stage}_form_name"] = FORM_NAMES.get(form, f"UNKNOWN_{form}")

        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map = f"{UV_PREFIX}{stage}"
        tex = nodes.new("ShaderNodeTexImage")
        image, status = load_image(client_root, str(logical or ""))
        loads.append(status)
        tex.image = image
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
        if image is not None and pack:
            try:
                image.pack()
            except Exception:
                pass
        stage_colors.append(tex.outputs["Color"])

    color_socket = None
    exact_combiner = True
    if stage_colors:
        color_socket = stage_colors[0]
        for stage in range(1, len(stage_colors)):
            op = int((src.get("TextureStageState") or [0] * 8)[stage])
            mix = nodes.new("ShaderNodeMixRGB")
            mix.inputs[0].default_value = 1.0
            if op in (0, 4):
                # Runtime substitutes D3DTOP_MODULATE when serialized op == 0.
                mix.blend_type = "MULTIPLY"
            elif op == 7:
                mix.blend_type = "ADD"
            else:
                exact_combiner = False
                mix.blend_type = "MULTIPLY"
            links.new(color_socket, mix.inputs[1])
            links.new(stage_colors[stage], mix.inputs[2])
            color_socket = mix.outputs[0]

    # Runtime stage geometry carries per-vertex colour. Multiply it into the
    # frame-0 texture result for a useful preview; transport is checked exactly
    # independently of this shader approximation.
    vcol = nodes.new("ShaderNodeVertexColor")
    vcol.layer_name = COLOR_NAME
    if color_socket is not None:
        mult = nodes.new("ShaderNodeMixRGB")
        mult.blend_type = "MULTIPLY"
        mult.inputs[0].default_value = 1.0
        links.new(color_socket, mult.inputs[1])
        links.new(vcol.outputs["Color"], mult.inputs[2])
        color_socket = mult.outputs[0]
    else:
        color_socket = vcol.outputs["Color"]
    links.new(color_socket, bsdf.inputs["Base Color"])

    alpha = max(0.0, min(1.0, 1.0 - float(src.get("Transparency") or 0.0)))
    if not runtime_renderable:
        # smRENDER3D::RenderD3D returns false when both counters are zero.
        # Keep the faces in the certified mesh, but do not present them as a
        # "missing texture" in Material Preview.
        alpha = 0.0
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = alpha
    try:
        mat.surface_render_method = "DITHERED" if alpha < 0.999 else "DITHERED"
    except Exception:
        pass

    mat["pt_stage072_combiner_exact_frame0"] = int(exact_combiner)
    mat["pt_stage072_texture_load_status"] = "|".join(loads)
    return mat, exact_combiner, loads


def main(argv):
    a = parse_args(argv)
    smd = pathlib.Path(a.smd).resolve()
    client_root = pathlib.Path(a.client_root).resolve()
    out_path = pathlib.Path(a.out).resolve()
    report_path = pathlib.Path(a.report).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    parsed = parse_stage072(smd, include_payload=True)
    if parsed.get("full_parse") != "PASS":
        raise RuntimeError("Stage0.72 source did not pass physical parser")
    payload = parsed["payload"]
    clear_scene()

    verts = [(v["x"] / 256.0, v["y"] / 256.0, v["z"] / 256.0) for v in payload["vertices"]]
    faces = [tuple(f["vertices"]) for f in payload["faces"]]
    mesh = bpy.data.meshes.new("PT_STAGE072_MESH")
    mesh.from_pydata(verts, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("PT_STAGE072_STAGE", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["pt_stage072_source"] = str(smd)
    obj["pt_stage072_source_sha256"] = parsed["sha256"]
    obj["pt_stage072_scale"] = 256
    obj["pt_stage072_max_texlink_depth"] = int(parsed["max_texlink_depth"])
    obj["pt_stage072_area_encoding"] = str(parsed["area"]["encoding"])

    depths = material_depths(parsed)
    used_ids = sorted(depths)
    by_id = {int(m["id"]): m for m in parsed["materials"]}
    slot_for_mid = {}
    exact_material_count = 0
    approximate_material_count = 0
    texture_load_failures = []
    for mid in used_ids:
        mat, exact, loads = create_material(by_id[mid], depths[mid], client_root, pack=a.pack)
        slot_for_mid[mid] = len(mesh.materials)
        mesh.materials.append(mat)
        if exact:
            exact_material_count += 1
        else:
            approximate_material_count += 1
        if any(x not in {"LOADED", "NO_TEXTURE"} for x in loads):
            texture_load_failures.append({"material": mid, "status": loads})

    for i, (poly, srcf) in enumerate(zip(mesh.polygons, payload["faces"])):
        mid = int(srcf["material"])
        poly.material_index = slot_for_mid[mid]

    uv_layers = []
    max_depth = int(parsed["max_texlink_depth"])
    for stage in range(max_depth):
        uv_layers.append(mesh.uv_layers.new(name=f"{UV_PREFIX}{stage}"))
    for poly, srcf in zip(mesh.polygons, payload["faces"]):
        chain = srcf.get("texlink_chain") or []
        for stage, ti in enumerate(chain):
            tl = payload["texlinks"][ti]
            coords = [(float(tl["u"][j]), 1.0 - float(tl["v"][j])) for j in range(3)]
            for li, uv in zip(poly.loop_indices, coords):
                uv_layers[stage].data[li].uv = uv

    depth_attr = mesh.attributes.new(name="PT_STAGE072_TEXLINK_DEPTH", type="INT", domain="FACE")
    mid_attr = mesh.attributes.new(name="PT_STAGE072_MATERIAL_ID", type="INT", domain="FACE")
    for i, srcf in enumerate(payload["faces"]):
        depth_attr.data[i].value = len(srcf.get("texlink_chain") or [])
        mid_attr.data[i].value = int(srcf["material"])

    color = mesh.color_attributes.new(name=COLOR_NAME, type="FLOAT_COLOR", domain="POINT")
    for i, v in enumerate(payload["vertices"]):
        c = v["color"]
        color.data[i].color = tuple(max(0.0, min(1.0, float(x) / 255.0)) for x in c)

    light_col = bpy.data.collections.new("PT_STAGE072_LIGHT_METADATA")
    bpy.context.scene.collection.children.link(light_col)
    for i, src in enumerate(payload["lights"]):
        empty = bpy.data.objects.new(f"PT_STAGE072_LIGHT_{i:04d}", None)
        empty.empty_display_type = "SPHERE"
        empty.empty_display_size = max(0.25, abs(float(src["range"])) / 256.0 * 0.025)
        empty.location = (src["x"] / 256.0, src["y"] / 256.0, src["z"] / 256.0)
        for key in ("type", "x", "y", "z", "range", "r", "g", "b"):
            empty[f"pt_stage072_{key}"] = int(src[key])
        light_col.objects.link(empty)

    # Store scene-level source lighting controls as exact metadata. These are
    # not claimed to reproduce the game renderer in Blender.
    scene = bpy.context.scene
    scene["pt_stage072_contrast"] = int(parsed["lighting"]["Contrast"])
    scene["pt_stage072_bright"] = int(parsed["lighting"]["Bright"])
    scene["pt_stage072_vectlight"] = list(parsed["lighting"]["VectLight"])
    scene["pt_stage072_light_preview_semantics"] = "METADATA_ONLY_NOT_RUNTIME_LIGHTING"

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    for other in bpy.context.selected_objects:
        if other != obj:
            other.select_set(False)

    runtime_nonrendered_material_ids = [
        int(mid) for mid in used_ids
        if not bool(int(by_id[mid].get("TextureCounter") or 0) or int(by_id[mid].get("AnimTexCounter") or 0))
    ]
    face_counts = parsed.get("material_face_counts") or {}
    runtime_nonrendered_faces = sum(int(face_counts.get(mid, face_counts.get(str(mid), 0)) or 0) for mid in runtime_nonrendered_material_ids)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path))

    report = {
        "format": "PT_STAGE072_BLENDER_IMPORT_V1",
        "check": "PASS",
        "source": str(smd),
        "source_sha256": parsed["sha256"],
        "blend": str(out_path),
        "vertices": len(verts),
        "faces": len(faces),
        "used_materials": len(used_ids),
        "serialized_materials": int(parsed["counts"]["materials"]),
        "lights": len(payload["lights"]),
        "max_texlink_depth": max_depth,
        "uv_layers": [x.name for x in uv_layers],
        "custom_vertex_color_vertices": int(parsed["custom_vertex_color_vertices"]),
        "inert_zero_texture_texlink_faces": int(parsed["inert_zero_texture_texlink_faces"]),
        "area_encoding": parsed["area"]["encoding"],
        "opaque_trailing_bytes": int(parsed["area"].get("opaque_trailing_bytes") or 0),
        "combiner_exact_frame0_material_count": exact_material_count,
        "combiner_approximate_frame0_material_count": approximate_material_count,
        "texture_load_failure_count": len(texture_load_failures),
        "runtime_nonrendered_material_ids": runtime_nonrendered_material_ids,
        "runtime_nonrendered_faces": runtime_nonrendered_faces,
        "texture_load_failures": texture_load_failures[:50],
        "dynamic_form_preview": "FRAME0_ONLY",
        "light_preview": "METADATA_ONLY_NOT_RUNTIME_LIGHTING",
        "client_modified": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    main(argv)
