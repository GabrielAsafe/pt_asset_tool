#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pt_asset_tool.multilayer_texlink import parse_multilayer_semantics, STAGE_OP_NAMES, FORM_NAMES
from pt_asset_tool.utils import norm_path


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--client-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--report", required=True)
    return p.parse_args(argv)


def _low(s: str) -> str:
    return norm_path(s).lower()


def _file_index(root: pathlib.Path) -> dict[str, pathlib.Path]:
    out = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            out[_low(p.relative_to(root).as_posix())] = p
    return out


def _image(root: pathlib.Path, index: dict[str, pathlib.Path], logical: str):
    p = index.get(_low(logical))
    if p is None:
        q = root / pathlib.PurePosixPath(norm_path(logical))
        if q.is_file():
            p = q
    if p is None:
        raise FileNotFoundError(f"multilayer texture not found in overlay: {logical}")
    # Reuse an already-loaded image by absolute filepath where possible.
    rp = str(p.resolve())
    for img in bpy.data.images:
        try:
            if pathlib.Path(bpy.path.abspath(img.filepath)).resolve() == p.resolve():
                return img
        except Exception:
            pass
    return bpy.data.images.load(rp, check_existing=True)


def _base_name(name: str) -> str:
    # Blender suffixes duplicate names as .001 / .002. Keep source names that
    # legitimately contain dots otherwise.
    if len(name) > 4 and name[-4] == "." and name[-3:].isdigit():
        return name[:-4]
    return name


def _map_objects(report: dict) -> list[tuple[dict, bpy.types.Object]]:
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    used = set()
    pairs = []
    for src in report["objects"]:
        candidates = []
        for obj in meshes:
            if obj.name in used:
                continue
            if len(obj.data.vertices) != int(src["vertices"]) or len(obj.data.polygons) != int(src["faces"]):
                continue
            score = 0
            if _base_name(obj.name).lower() == str(src["name"]).lower():
                score += 10
            candidates.append((score, obj))
        if not candidates:
            raise RuntimeError(
                f"cannot map SMD object to Blender mesh: {src['name']} "
                f"V={src['vertices']} F={src['faces']}"
            )
        candidates.sort(key=lambda x: (-x[0], list(bpy.context.scene.objects).index(x[1])))
        obj = candidates[0][1]
        used.add(obj.name)
        pairs.append((src, obj))
    return pairs


def _ensure_uv_layer(mesh, name: str):
    uv = mesh.uv_layers.get(name)
    if uv is None:
        uv = mesh.uv_layers.new(name=name)
    if len(uv.data) != len(mesh.loops):
        raise RuntimeError(f"UV layer storage mismatch {name}: {len(uv.data)} != {len(mesh.loops)}")
    return uv


def _assign_uvs(src_obj: dict, obj: bpy.types.Object):
    mesh = obj.data
    uv0 = _ensure_uv_layer(mesh, "PT_TEXLINK_STAGE_0")
    uv1 = _ensure_uv_layer(mesh, "PT_TEXLINK_STAGE_1")
    depth_attr = mesh.attributes.get("pt_texlink_depth")
    if depth_attr is None:
        depth_attr = mesh.attributes.new("pt_texlink_depth", type="INT", domain="FACE")

    if len(src_obj["face_rows"]) != len(mesh.polygons):
        raise RuntimeError(f"face count mismatch for {obj.name}")
    stage1_faces = 0
    distinct_uv_faces = 0
    for fi, (face, poly) in enumerate(zip(src_obj["face_rows"], mesh.polygons)):
        src_verts = list(face["vertices"])
        if sorted(src_verts) != sorted(int(v) for v in poly.vertices):
            raise RuntimeError(
                f"polygon/source vertex mismatch {obj.name}:{fi}: "
                f"source={src_verts} blender={list(poly.vertices)}"
            )
        chain = face["chain"]
        depth_attr.data[fi].value = len(chain)
        if not chain:
            continue
        if len(chain) > 2:
            raise RuntimeError(f"V1 preview refuses >2 TexLink stages: {obj.name}:{fi}")
        # Map each Blender loop to source corner by vertex index, so winding/order
        # differences cannot silently swap UV corners.
        for loop_idx in poly.loop_indices:
            vi = int(mesh.loops[loop_idx].vertex_index)
            try:
                corner = src_verts.index(vi)
            except ValueError:
                raise RuntimeError(f"cannot map loop vertex {vi} in {obj.name}:{fi}")
            u, v = chain[0]["uv"][corner]
            uv0.data[loop_idx].uv = (float(u), 1.0 - float(v))
            if len(chain) > 1:
                u1, v1 = chain[1]["uv"][corner]
                uv1.data[loop_idx].uv = (float(u1), 1.0 - float(v1))
            else:
                uv1.data[loop_idx].uv = (float(u), 1.0 - float(v))
        if len(chain) > 1:
            stage1_faces += 1
            if max(abs(chain[0]["uv"][j][k] - chain[1]["uv"][j][k]) for j in range(3) for k in range(2)) > 1e-7:
                distinct_uv_faces += 1
    mesh.update()
    return stage1_faces, distinct_uv_faces



def _verify_uv_assignment(src_obj: dict, obj: bpy.types.Object, tolerance: float = 1e-6):
    """Read Blender UV storage back and compare every source face/corner exactly.

    This gate certifies transport/mapping only. It does not claim that runtime
    dynamic texture-form motion (FS_SCROLL*) is reproduced by Blender.
    """
    mesh = obj.data
    uv0 = mesh.uv_layers.get("PT_TEXLINK_STAGE_0")
    uv1 = mesh.uv_layers.get("PT_TEXLINK_STAGE_1")
    depth_attr = mesh.attributes.get("pt_texlink_depth")
    if uv0 is None or uv1 is None or depth_attr is None:
        raise RuntimeError(f"missing TexLink UV/depth storage on {obj.name}")

    mismatch_count = 0
    depth_mismatch_count = 0
    max_abs_error = 0.0
    checked_loops = 0
    for fi, (face, poly) in enumerate(zip(src_obj["face_rows"], mesh.polygons)):
        chain = face["chain"]
        if int(depth_attr.data[fi].value) != len(chain):
            depth_mismatch_count += 1
        if not chain:
            continue
        src_verts = list(face["vertices"] )
        for loop_idx in poly.loop_indices:
            vi = int(mesh.loops[loop_idx].vertex_index)
            try:
                corner = src_verts.index(vi)
            except ValueError:
                mismatch_count += 1
                continue
            exp0 = (float(chain[0]["uv"][corner][0]), 1.0 - float(chain[0]["uv"][corner][1]))
            stage1 = chain[1] if len(chain) > 1 else chain[0]
            exp1 = (float(stage1["uv"][corner][0]), 1.0 - float(stage1["uv"][corner][1]))
            got0 = uv0.data[loop_idx].uv
            got1 = uv1.data[loop_idx].uv
            err = max(
                abs(float(got0[0]) - exp0[0]), abs(float(got0[1]) - exp0[1]),
                abs(float(got1[0]) - exp1[0]), abs(float(got1[1]) - exp1[1]),
            )
            max_abs_error = max(max_abs_error, err)
            checked_loops += 1
            if err > tolerance:
                mismatch_count += 1
    return {
        "checked_loops": checked_loops,
        "mismatch_count": mismatch_count,
        "depth_mismatch_count": depth_mismatch_count,
        "max_abs_error": max_abs_error,
        "tolerance": tolerance,
        "check": "PASS" if mismatch_count == 0 and depth_mismatch_count == 0 else "FAIL",
    }

def _uv_vector(nodes, links, stage: int, form_code: int):
    if form_code == 5:  # FS_REFLEX
        tc = nodes.new("ShaderNodeTexCoord")
        tc.label = "PT FS_REFLEX"
        return tc.outputs.get("Reflection"), "REFLECTION_VECTOR"
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = f"PT_TEXLINK_STAGE_{stage}"
    uv.label = f"PT TexLink UV stage {stage} / {FORM_NAMES.get(form_code, form_code)}"
    # Scroll/form transforms are runtime dynamic. At preview frame 0 their
    # serialized UV basis remains the correct evidence surface.
    return uv.outputs.get("UV"), "SERIALIZED_UV_FRAME0"


def _texture_node(nodes, links, image, vector_socket, *, environment: bool):
    if environment:
        tex = nodes.new("ShaderNodeTexEnvironment")
    else:
        tex = nodes.new("ShaderNodeTexImage")
        tex.interpolation = "Linear"
    tex.image = image
    if vector_socket is not None:
        links.new(vector_socket, tex.inputs.get("Vector"))
    return tex


def _combine(nodes, links, c0, c1, op_code: int):
    # Exact for the profiles present in the V0.5.3 representative corpus:
    # DEFAULT/0 is the historical no-BS_* path and is previewed as modulation;
    # 7 is D3DTOP_ADD from BS_ADD in smRead3d.cpp.
    mix = nodes.new("ShaderNodeMixRGB")
    mix.inputs[0].default_value = 1.0
    if op_code == 7:
        mix.blend_type = "ADD"
        exact = True
    elif op_code in (0, 4):
        mix.blend_type = "MULTIPLY"
        exact = op_code == 4
    elif op_code == 10:
        mix.blend_type = "SUBTRACT"
        exact = True
    else:
        mix.blend_type = "MULTIPLY"
        exact = False
    links.new(c0, mix.inputs[1])
    links.new(c1, mix.inputs[2])
    return mix.outputs[0], exact


def _build_material(src_mat: dict, root: pathlib.Path, index: dict[str, pathlib.Path]):
    mid = int(src_mat["material_id"])
    stages = list(src_mat.get("textures") or [])
    if len(stages) < 2:
        raise RuntimeError(f"material {mid} is not two-stage")
    mat = bpy.data.materials.new(name=f"PT_ML_MAT_{mid:03d}_{src_mat['profile']}")
    mat.use_nodes = True
    mat["pt_material_id"] = mid
    mat["pt_texlink_profile"] = src_mat["profile"]
    mat["pt_reform_texture"] = int(src_mat.get("ReformTexture") or 0)
    mat["pt_stage0_texture"] = stages[0]["name"]
    mat["pt_stage1_texture"] = stages[1]["name"]
    mat["pt_stage0_form"] = stages[0]["form_state_name"]
    mat["pt_stage1_form"] = stages[1]["form_state_name"]
    mat["pt_stage0_op"] = stages[0]["stage_state_name"]
    mat["pt_stage1_op"] = stages[1]["stage_state_name"]

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    img0 = _image(root, index, stages[0]["name"])
    vec0, mode0 = _uv_vector(nodes, links, 0, int(stages[0]["form_state"]))
    t0 = _texture_node(nodes, links, img0, vec0, environment=False)
    t0.label = f"Stage 0: {stages[0]['stage_state_name']} / {stages[0]['form_state_name']}"

    img1 = _image(root, index, stages[1]["name"])
    form1 = int(stages[1]["form_state"])
    vec1, mode1 = _uv_vector(nodes, links, 1, form1)
    t1 = _texture_node(nodes, links, img1, vec1, environment=(form1 == 5))
    t1.label = f"Stage 1: {stages[1]['stage_state_name']} / {stages[1]['form_state_name']}"

    combined, exact = _combine(nodes, links, t0.outputs.get("Color"), t1.outputs.get("Color"), int(stages[1]["stage_state"]))
    links.new(combined, bsdf.inputs["Base Color"])
    # Preserve the base texture alpha as the least surprising preview behavior.
    if t0.outputs.get("Alpha") is not None and bsdf.inputs.get("Alpha") is not None:
        links.new(t0.outputs["Alpha"], bsdf.inputs["Alpha"])

    mat["pt_stage0_coordinate_mode"] = mode0
    mat["pt_stage1_coordinate_mode"] = mode1
    mat["pt_combiner_preview_exact"] = bool(exact)
    mat["pt_dynamic_form_preview"] = "FRAME0_ONLY" if any(int(x["form_state"]) not in (0, 5) for x in stages[:2]) else "NOT_DYNAMIC"
    return mat, exact


def main():
    a = _args()
    smd = pathlib.Path(a.smd).expanduser().resolve()
    client_root = pathlib.Path(a.client_root).expanduser().resolve()
    report = parse_multilayer_semantics(smd)
    if report["source_semantics"] != "PASS":
        raise RuntimeError("multilayer source semantics failed")
    if report["max_layers"] != 2:
        raise RuntimeError(f"preview V1 requires exactly two-stage max; got {report['max_layers']}")
    if report["multilayer_faces"] < 1:
        raise RuntimeError("source has no multilayer faces")

    index = _file_index(client_root)
    pairs = _map_objects(report)
    stage1_faces = 0
    distinct_uv = 0
    uv_checked_loops = 0
    uv_mismatch_count = 0
    uv_depth_mismatch_count = 0
    uv_max_abs_error = 0.0
    for src_obj, obj in pairs:
        a1, a2 = _assign_uvs(src_obj, obj)
        verify = _verify_uv_assignment(src_obj, obj)
        if verify["check"] != "PASS":
            raise RuntimeError(f"source->Blender TexLink UV assignment mismatch on {obj.name}: {verify}")
        stage1_faces += a1
        distinct_uv += a2
        uv_checked_loops += int(verify["checked_loops"])
        uv_mismatch_count += int(verify["mismatch_count"])
        uv_depth_mismatch_count += int(verify["depth_mismatch_count"])
        uv_max_abs_error = max(uv_max_abs_error, float(verify["max_abs_error"]))
        obj["pt_multilayer_texlink"] = True
        obj["pt_texlink_stage_count"] = 2
        obj["pt_texlink_uv_assignment_check"] = "PASS"

    preview_materials = {}
    exact_count = 0
    approximate_count = 0
    for src_mat in report["multilayer_materials"]:
        mat, exact = _build_material(src_mat, client_root, index)
        preview_materials[int(src_mat["material_id"])] = mat
        if exact:
            exact_count += 1
        else:
            approximate_count += 1

    for _, obj in pairs:
        for mid, mat in preview_materials.items():
            if mid < len(obj.data.materials):
                obj.data.materials[mid] = mat
        obj.data.update()

    scene = bpy.context.scene
    scene["pt_multilayer_texlink_preview"] = "TWO_STAGE_V1"
    scene["pt_multilayer_source"] = str(smd)
    scene["pt_multilayer_faces"] = int(report["multilayer_faces"])
    scene["pt_multilayer_uv_distinct_faces"] = int(report["uv_distinct_multilayer_faces"])
    scene["pt_htexture_slot_mapping"] = report["htexture_slot_mapping"]
    scene["pt_multilayer_profiles"] = ",".join(sorted(report["profile_counts"]))
    scene["pt_texlink_uv_assignment_check"] = "PASS"
    scene["pt_texlink_uv_assignment_max_abs_error"] = float(uv_max_abs_error)

    out = pathlib.Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    result = {
        "tool": "PT_MULTILAYER_TEXLINK_BLENDER_PREVIEW_V1",
        "source": str(smd),
        "output": str(out),
        "objects_mapped": len(pairs),
        "multilayer_faces": stage1_faces,
        "distinct_uv_faces": distinct_uv,
        "uv_layers": ["PT_TEXLINK_STAGE_0", "PT_TEXLINK_STAGE_1"],
        "uv_assignment_check": "PASS",
        "uv_assignment_checked_loops": uv_checked_loops,
        "uv_assignment_mismatch_count": uv_mismatch_count,
        "uv_assignment_depth_mismatch_count": uv_depth_mismatch_count,
        "uv_assignment_max_abs_error": uv_max_abs_error,
        "material_profiles": report["profile_counts"],
        "preview_material_count": len(preview_materials),
        "combiner_exact_material_count": exact_count,
        "combiner_approximate_material_count": approximate_count,
        "dynamic_form_preview": "FRAME0_ONLY",
        "htexture_slot_mapping": report["htexture_slot_mapping"],
        "source_semantics": report["source_semantics"],
        "client_modified": False,
        "check": "PASS",
    }
    rp = pathlib.Path(a.report).expanduser().resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PT_MULTILAYER_TEXLINK_BLENDER_PREVIEW_V1")
    print(f"objects_mapped={len(pairs)}")
    print(f"multilayer_faces={stage1_faces}")
    print(f"distinct_uv_faces={distinct_uv}")
    print(f"uv_assignment_check=PASS checked_loops={uv_checked_loops} max_abs_error={uv_max_abs_error:.9g}")
    print(f"profiles={report['profile_counts']}")
    print(f"htexture_slot_mapping={report['htexture_slot_mapping']}")
    print(f"output={out}")
    print("client_modified=False")
    print("multilayer_preview_check=PASS")


if __name__ == "__main__":
    main()
