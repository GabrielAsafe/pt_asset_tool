from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

import bpy


def load_importer(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("pt_rare_rigid_base_importer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load importer: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--importer", required=True)
    p.add_argument("--rare-smd", required=True)
    p.add_argument("--root-smd", required=True)
    p.add_argument("--skeleton", required=True)
    p.add_argument("--rare-model-info", required=True)
    p.add_argument("--root-model-info", required=True)
    p.add_argument("--root-lod", choices=("high", "default", "low"), required=True)
    p.add_argument("--rare-visibility-policy", choices=("SOURCE_INX_EXACT", "SOURCE_INX_EMPTY_SHOW_ALL_DIAGNOSTIC"), required=True)
    p.add_argument("--client-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--logical", required=True)
    p.add_argument("--root-logical", required=True)
    return p.parse_args(argv)


def mat_statuses(materials):
    out = []
    for m in materials:
        out.append({
            "name": m.name,
            "material_id": int(m.get("pt_smd_material_id", -1)),
            "texture_name": str(m.get("pt_smd_texture_name", "")),
            "texture_load": str(m.get("pt_smd_texture_load", "")),
        })
    return out


def set_all_visible(objects, lod):
    visible = []
    for obj in objects:
        obj.hide_render = False
        try:
            obj.hide_set(False)
        except Exception:
            obj.hide_viewport = False
        obj["pt_inx_lod"] = lod
        obj["pt_inx_selected"] = 1
        obj["pt_inx_match_semantics"] = "SOURCE_INX_EMPTY_SHOW_ALL_DIAGNOSTIC"
        visible.append(obj.name)
    return visible, []


def main(argv):
    args = parse_args(argv)
    importer_path = pathlib.Path(args.importer).resolve()
    rare_smd = pathlib.Path(args.rare_smd).resolve()
    root_smd = pathlib.Path(args.root_smd).resolve()
    skeleton = pathlib.Path(args.skeleton).resolve()
    rare_inx = pathlib.Path(args.rare_model_info).resolve()
    root_inx = pathlib.Path(args.root_model_info).resolve()
    client_root = pathlib.Path(args.client_root).resolve()
    out = pathlib.Path(args.out).resolve()
    report = pathlib.Path(args.report).resolve()

    m = load_importer(importer_path)
    rare_data = rare_smd.read_bytes()
    root_data = root_smd.read_bytes()
    skel_data = skeleton.read_bytes()

    rare_meta = m.parse_header_and_infos(rare_data)
    rare_materials = m.parse_materials(rare_data, rare_meta)
    rare_objects = m.parse_objects(rare_data, rare_meta)
    root_meta = m.parse_header_and_infos(root_data)
    root_materials = m.parse_materials(root_data, root_meta)
    root_objects = m.parse_objects(root_data, root_meta)
    skeleton_meta, skeleton_bones = m.parse_skeleton_tms(skel_data)

    rare_bind = m.reconstruct_bind_pose(rare_objects, skeleton_bones)
    root_bind = m.reconstruct_bind_pose(root_objects, skeleton_bones)
    rare_groups = m.parse_inx_model_groups(rare_inx)
    root_groups = m.parse_inx_model_groups(root_inx)

    m.clear_scene()
    root_collection = m.ensure_collection("PT_RARE_CONTEXT_ROOT")
    rare_collection = m.ensure_collection("PT_RARE_PIECE")

    root_mats = m.create_blender_materials(root_materials, client_root, out.parent / "_root_texture_cache", pack_images=False)
    for mat in root_mats:
        mat.name = "PT_ROOT__" + mat.name
        mat["pt_rare_role"] = "ROOT"
    root_blender = []
    root_stats = []
    for idx, src_obj in enumerate(root_objects):
        obj, info = m.create_mesh_object(src_obj, root_collection, root_mats)
        obj["pt_rare_role"] = "ROOT"
        obj["pt_source_object_index"] = idx
        obj["pt_source_table_name"] = str(root_meta["infos"][idx]["name"])
        root_blender.append(obj); root_stats.append(info)
    root_visible, root_hidden = m.apply_lod_visibility(root_blender, root_groups, args.root_lod)

    rare_mats = m.create_blender_materials(rare_materials, client_root, out.parent / "_rare_texture_cache", pack_images=False)
    for mat in rare_mats:
        mat.name = "PT_RARE__" + mat.name
        mat["pt_rare_role"] = "RARE"
    rare_blender = []
    rare_stats = []
    for idx, src_obj in enumerate(rare_objects):
        obj, info = m.create_mesh_object(src_obj, rare_collection, rare_mats)
        obj.name = "PT_RARE__" + obj.name
        obj["pt_rare_role"] = "RARE"
        obj["pt_source_object_index"] = idx
        obj["pt_source_table_name"] = str(rare_meta["infos"][idx]["name"])
        obj["pt_source_head_name"] = str(src_obj["name"])
        rare_blender.append(obj); rare_stats.append(info)

    if args.rare_visibility_policy == "SOURCE_INX_EXACT":
        rare_visible, rare_hidden = m.apply_lod_visibility(rare_blender, rare_groups, args.root_lod)
    else:
        if any((rare_groups[k].get("active") or []) for k in ("high", "default", "low")):
            raise RuntimeError("SHOW_ALL diagnostic policy requires an INX with zero model groups")
        rare_visible, rare_hidden = set_all_visible(rare_blender, args.root_lod)

    arm_stats = m.create_static_armature(skeleton_bones, root_blender + rare_blender, root_collection)
    arm = arm_stats["object"]
    arm.name = "PT_RARE_CONTEXT_ARMATURE"
    arm["pt_source"] = str(skeleton)
    arm["pt_rare_preview"] = 1

    bpy.context.scene["pt_rare_preview_logical"] = args.logical
    bpy.context.scene["pt_rare_preview_root_logical"] = args.root_logical
    bpy.context.scene["pt_rare_preview_skeleton"] = str(skeleton)
    bpy.context.scene["pt_rare_preview_source_inx"] = str(rare_inx)
    bpy.context.scene["pt_rare_preview_target_inx"] = str(root_inx)
    bpy.context.scene["pt_rare_preview_root_lod"] = args.root_lod
    bpy.context.scene["pt_rare_preview_visibility_policy"] = args.rare_visibility_policy
    bpy.context.scene["pt_rare_preview_write_authorized"] = False

    root_table_names = [str(x["name"]) for x in root_meta["infos"]]
    rare_table_names = [str(x["name"]) for x in rare_meta["infos"]]
    rare_head_names = [str(x["name"]) for x in rare_objects]
    name_mismatches = [
        {"index": i, "table_name": rare_table_names[i], "head_name": rare_head_names[i]}
        for i in range(len(rare_objects)) if rare_table_names[i] != rare_head_names[i]
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    load_rows = mat_statuses(root_mats) + mat_statuses(rare_mats)
    load_errors = [x for x in load_rows if str(x["texture_load"]).startswith("LOAD_ERROR")]
    result = {
        "check": "PASS" if not load_errors else "FAIL",
        "logical": args.logical,
        "root_logical": args.root_logical,
        "root_lod": args.root_lod,
        "rare_visibility_policy": args.rare_visibility_policy,
        "root_objects": len(root_objects),
        "root_vertices": sum(x["vertices"] for x in root_stats),
        "root_faces": sum(x["faces"] for x in root_stats),
        "root_visible_objects": root_visible,
        "root_hidden_objects": root_hidden,
        "rare_objects": len(rare_objects),
        "rare_vertices": sum(x["vertices"] for x in rare_stats),
        "rare_faces": sum(x["faces"] for x in rare_stats),
        "rare_visible_objects": rare_visible,
        "rare_hidden_objects": rare_hidden,
        "rare_table_names": rare_table_names,
        "rare_head_names": rare_head_names,
        "rare_name_mismatches": name_mismatches,
        "rare_bind_vertices": rare_bind["vertices"],
        "rare_bind_bones_used": rare_bind["bones_used"],
        "root_bind_vertices": root_bind["vertices"],
        "root_bind_bones_used": root_bind["bones_used"],
        "armature_bones": arm_stats["bones"],
        "skeleton_objects": skeleton_meta["obj_counter"],
        "texture_load_error_count": len(load_errors),
        "texture_load_errors": load_errors,
        "blend": str(out),
        "write_authorized": False,
        "client_modified": False,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "PT_RARE_RIGID_IMPORT=" + result["check"] +
        f" rare_objects={result['rare_objects']} rare_visible={len(rare_visible)}" +
        f" root_objects={result['root_objects']} root_visible={len(root_visible)}" +
        f" bones={result['armature_bones']} texture_errors={len(load_errors)}"
    )
    if load_errors:
        raise RuntimeError(f"texture load errors: {load_errors[:5]}")


if __name__ == "__main__":
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    main(argv)
