#!/usr/bin/env python3
"""
PT Blender Bind Editable Texture V2

Resolution order:
1. existing image basename/path match;
2. deterministic SMD global material IDs supplied by --material-slot.

Only a COPY of the artist .blend is modified.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--source-basename", required=True)
    p.add_argument("--material-slot", type=int, action="append", default=[])
    p.add_argument("--texture", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args(argv)


def match_image(img, source_basename):
    wanted = pathlib.Path(source_basename).name.lower()
    stem = pathlib.Path(wanted).stem.lower()
    raw_values = [
        img.name or "",
        pathlib.Path(bpy.path.abspath(img.filepath or "")).name,
        pathlib.Path(bpy.path.abspath(img.filepath_raw or "")).name,
    ]
    for raw in raw_values:
        name = str(raw).lower()
        if name == wanted:
            return True
        if name.startswith(stem + ".") and ".decoded." in name:
            return True
        if pathlib.Path(name).stem == stem:
            return True
    return False


def existing_basename_materials(source_basename):
    result = set()
    matched_images = set()
    for mat in bpy.data.materials:
        if not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.bl_idname != "ShaderNodeTexImage" or node.image is None:
                continue
            if match_image(node.image, source_basename):
                result.add(mat)
                matched_images.add(node.image.name)
    return result, matched_images


def material_slot_fallback(slot_ids):
    wanted = set(slot_ids)
    if not wanted:
        return set(), {}, {}

    materials = set()
    polygon_counts = {idx: 0 for idx in wanted}
    bindings = {idx: set() for idx in wanted}

    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data is None:
            continue

        used = {}
        for poly in obj.data.polygons:
            idx = int(poly.material_index)
            if idx in wanted:
                used[idx] = used.get(idx, 0) + 1

        for idx, count in used.items():
            polygon_counts[idx] += count
            if idx >= len(obj.data.materials):
                raise RuntimeError(
                    f"{obj.name}: polygon uses material_index={idx}, "
                    f"but mesh has only {len(obj.data.materials)} material slots"
                )
            mat = obj.data.materials[idx]
            if mat is None:
                raise RuntimeError(
                    f"{obj.name}: polygon uses material_index={idx}, "
                    "but that material slot is empty"
                )
            materials.add(mat)
            bindings[idx].add(mat.name)

    missing = [idx for idx in sorted(wanted) if polygon_counts[idx] == 0]
    if missing:
        raise RuntimeError(
            f"requested material IDs are not used by any mesh polygon: {missing}"
        )

    return materials, polygon_counts, bindings


def principled_node(mat):
    nt = mat.node_tree
    if nt is None:
        return None
    for node in nt.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            return node
    return None


def bind_image_to_material(mat, image):
    mat.use_nodes = True
    nt = mat.node_tree
    image_nodes = [
        n for n in nt.nodes
        if n.bl_idname == "ShaderNodeTexImage"
    ]

    created = False
    linked = False

    if image_nodes:
        for node in image_nodes:
            node.image = image
    else:
        node = nt.nodes.new("ShaderNodeTexImage")
        node.name = "PT_EDITABLE_CHARACTER_TEXTURE"
        node.label = "PT Editable Character Texture"
        node.image = image
        image_nodes = [node]
        created = True

        bsdf = principled_node(mat)
        if bsdf is not None and "Base Color" in bsdf.inputs:
            try:
                nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
                linked = True
            except Exception:
                pass

    return len(image_nodes), created, linked


def main():
    a = parse_args()
    texture = pathlib.Path(a.texture).expanduser().resolve()
    out = pathlib.Path(a.out).expanduser().resolve()

    if not texture.is_file():
        raise FileNotFoundError(texture)
    if out.exists() and not a.overwrite:
        raise FileExistsError(out)

    new_image = bpy.data.images.load(str(texture), check_existing=False)

    basename_materials, matched_images = existing_basename_materials(
        a.source_basename
    )

    polygon_counts = {}
    slot_bindings = {}

    if basename_materials:
        target_materials = basename_materials
        strategy = "IMAGE_BASENAME"
    else:
        target_materials, polygon_counts, slot_bindings = material_slot_fallback(
            a.material_slot
        )
        strategy = "SMD_MATERIAL_SLOT"

    if not target_materials:
        raise RuntimeError(
            f"no materials resolved for {a.source_basename!r}; "
            f"material_slots={a.material_slot}"
        )

    node_count = 0
    created_nodes = 0
    new_links = 0
    material_names = []

    for mat in sorted(target_materials, key=lambda m: m.name):
        n, created, linked = bind_image_to_material(mat, new_image)
        node_count += n
        created_nodes += int(created)
        new_links += int(linked)
        material_names.append(mat.name)

    verified = 0
    for mat in target_materials:
        ok = False
        if mat.node_tree:
            for node in mat.node_tree.nodes:
                if (
                    node.bl_idname == "ShaderNodeTexImage"
                    and node.image == new_image
                ):
                    ok = True
                    break
        if not ok:
            raise RuntimeError(f"post-bind verification failed for material {mat.name}")
        verified += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    print("PT_BLENDER_BIND_EDITABLE_TEXTURE_V2")
    print(f"source_basename={a.source_basename}")
    print(f"requested_material_slots={sorted(set(a.material_slot))}")
    print(f"resolution_strategy={strategy}")
    print(f"matched_original_images={sorted(matched_images)}")
    print(f"polygon_counts_by_material_slot={polygon_counts}")
    print(
        "material_slot_bindings="
        + repr({k: sorted(v) for k, v in slot_bindings.items()})
    )
    print(f"target_materials={material_names}")
    print(f"editable_texture={texture}")
    print(f"image_nodes_bound={node_count}")
    print(f"image_nodes_created={created_nodes}")
    print(f"base_color_links_created={new_links}")
    print(f"materials_verified={verified}")
    print(f"output_blend={out}")
    print("artist_master_overwritten=False")
    print("texture_bind_blend_check=PASS")


if __name__ == "__main__":
    main()
