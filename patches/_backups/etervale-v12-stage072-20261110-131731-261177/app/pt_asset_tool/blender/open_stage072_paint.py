from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import re
import shutil
import sys

import bpy
from mathutils import Vector

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pt_asset_tool.blender import open_stage072_preview as view

SOURCE_UV_PREFIX = "PT_STAGE072_TEXLINK_STAGE_"
PAINT_UV_PREFIX = "PT_STAGE072_PAINT_UV_STAGE_"
PAINT_MAT_SUFFIX = "__PT_PAINT"
PAINT_IMAGE_PREFIX = "PTPAINT_"


def _parse_args():
    argv = sys.argv
    tail = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--paint-root", required=True)
    ap.add_argument("--stage", type=int, default=0)
    return ap.parse_args(tail)


def _safe_basename(name: str) -> str:
    raw = pathlib.PurePosixPath(str(name or "texture").replace("\\", "/")).name
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._") or "texture"
    return raw[:100]


def _stage_for_image_node(node) -> int | None:
    try:
        links = node.inputs["Vector"].links
    except Exception:
        return None
    for link in links:
        src = link.from_node
        if getattr(src, "type", "") != "UVMAP":
            continue
        name = str(getattr(src, "uv_map", "") or "")
        if name.startswith(SOURCE_UV_PREFIX):
            try:
                return int(name[len(SOURCE_UV_PREFIX):])
            except Exception:
                return None
    return None


def _copy_image_to_workspace(image, logical: str, paint_root: pathlib.Path, cache: dict[str, object]):
    if image is None:
        return None, None
    src_text = bpy.path.abspath(str(image.filepath or ""))
    if not src_text:
        return image, None
    src = pathlib.Path(src_text)
    if not src.is_file():
        return image, None

    key = str(logical or src.name).replace("\\", "/").lower()
    digest = hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:12]
    dst_dir = paint_root / "textures"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{digest}_{_safe_basename(logical or src.name)}"
    if not dst.suffix:
        dst = dst.with_suffix(src.suffix or ".png")

    cache_key = str(dst.resolve()) if dst.exists() else str(dst)
    if cache_key in cache:
        return cache[cache_key], dst

    # Never overwrite an existing paint copy: it may contain user edits from
    # an earlier session.  shutil.copyfile follows overlay symlinks, so the
    # destination is always a real private file rather than a link to client.
    if not dst.exists():
        shutil.copyfile(src, dst)
    if dst.is_symlink():
        raise RuntimeError(f"paint destination unexpectedly symlinked: {dst}")

    img = bpy.data.images.load(str(dst), check_existing=True)
    img.filepath = str(dst)
    img.filepath_raw = str(dst)
    img.name = f"{PAINT_IMAGE_PREFIX}{digest}_{image.name}"
    try:
        img.colorspace_settings.name = image.colorspace_settings.name
    except Exception:
        pass
    cache[cache_key] = img
    return img, dst


def _duplicate_materials_for_paint(proxy, paint_root: pathlib.Path, target_stage: int, manifest_rows: list[dict]):
    image_cache: dict[str, object] = {}
    mesh = proxy.data
    for slot_index, old_mat in enumerate(list(mesh.materials)):
        if old_mat is None:
            continue
        mat = old_mat.copy()
        mat.name = f"{old_mat.name}{PAINT_MAT_SUFFIX}"
        mat["pt_stage072_paint_workspace"] = True
        mat["pt_stage072_paint_stage"] = int(target_stage)

        active_target = None
        for node in mat.node_tree.nodes if mat.use_nodes and mat.node_tree else []:
            if getattr(node, "type", "") != "TEX_IMAGE" or node.image is None:
                continue
            stage = _stage_for_image_node(node)
            logical = ""
            if stage is not None:
                logical = str(mat.get(f"pt_stage072_stage{stage}_texture") or "")
            paint_img, dst = _copy_image_to_workspace(node.image, logical, paint_root, image_cache)
            if paint_img is not None:
                node.image = paint_img
            node.select = False
            if stage == target_stage and paint_img is not None:
                active_target = node
            manifest_rows.append({
                "material_slot": int(slot_index),
                "material": old_mat.name,
                "paint_material": mat.name,
                "stage": stage,
                "logical": logical,
                "paint_file": str(dst) if dst else None,
            })

        if active_target is not None:
            active_target.select = True
            mat.node_tree.nodes.active = active_target
            try:
                # Texture Paint slots are derived from image texture nodes.
                # Select the slot corresponding to the target stage when the
                # API exposes it; node selection remains the fallback.
                images = list(mat.texture_paint_images)
                for i, im in enumerate(images):
                    if im == active_target.image:
                        mat.paint_active_slot = i
                        break
            except Exception:
                pass
        mesh.materials[slot_index] = mat


def _uv_bounds(layer):
    if layer is None or not layer.data:
        return None
    us = [float(x.uv.x) for x in layer.data]
    vs = [float(x.uv.y) for x in layer.data]
    return [min(us), min(vs), max(us), max(vs)]


def _make_paint_uv_layers(proxy, target_stage: int):
    mesh = proxy.data
    stats = []
    made_target = None
    for stage in range(8):
        src = mesh.uv_layers.get(f"{SOURCE_UV_PREFIX}{stage}")
        if src is None:
            continue
        name = f"{PAINT_UV_PREFIX}{stage}"
        old = mesh.uv_layers.get(name)
        if old is not None:
            mesh.uv_layers.remove(old)
        dst = mesh.uv_layers.new(name=name)

        # Remove only an integer tile translation per polygon.  This preserves
        # the triangle's exact local UV shape while bringing tiled UV islands
        # close to the base image tile for Blender Texture Paint.  Source UVs
        # remain untouched and are still used by the material preview nodes.
        tile_offsets = {}
        for poly in mesh.polygons:
            lis = list(poly.loop_indices)
            if not lis:
                continue
            coords = [src.data[li].uv.copy() for li in lis]
            cu = sum(float(c.x) for c in coords) / len(coords)
            cv = sum(float(c.y) for c in coords) / len(coords)
            ou = math.floor(cu)
            ov = math.floor(cv)
            tile_offsets[int(poly.index)] = [int(ou), int(ov)]
            for li, c in zip(lis, coords):
                dst.data[li].uv = (float(c.x) - ou, float(c.y) - ov)

        stats.append({
            "stage": int(stage),
            "source_layer": src.name,
            "paint_layer": dst.name,
            "source_bounds": _uv_bounds(src),
            "paint_bounds": _uv_bounds(dst),
            "polygon_tile_offsets": len(tile_offsets),
        })
        if stage == target_stage:
            made_target = dst

    if made_target is None:
        raise RuntimeError(f"requested paint stage {target_stage} has no UV layer")
    # Do NOT make the rebased diagnostic UV active for 3D painting. The material
    # nodes and paint projection must keep the exact source Stage0.72 UV.
    source_target = mesh.uv_layers.get(f"{SOURCE_UV_PREFIX}{target_stage}")
    if source_target is not None:
        mesh.uv_layers.active_index = list(mesh.uv_layers).index(source_target)
    try:
        made_target.active_render = False
    except Exception:
        pass
    return stats, made_target


def _hide_paint_clutter():
    # Paint mode is for the artist, not for inspecting metadata helpers.
    for name in (view.VIEW_LIGHT_COLLECTION, "PT_STAGE072_LIGHT_METADATA"):
        col = bpy.data.collections.get(name)
        if col is not None:
            col.hide_viewport = True
            col.hide_render = True
    marker = bpy.data.objects.get(view.VIEW_CENTER_NAME)
    if marker is not None:
        marker.hide_set(True)
        marker.hide_viewport = True


def _validate_private_paint_images(proxy, paint_root: pathlib.Path, target_stage: int):
    rows = []
    hard = []
    for slot_index, mat in enumerate(proxy.data.materials):
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if getattr(node, "type", "") != "TEX_IMAGE":
                continue
            stage = _stage_for_image_node(node)
            img = node.image
            if img is None:
                # A no-texture stage can be physically valid; only target stages
                # with a serialized texture name are hard failures.
                logical = str(mat.get(f"pt_stage072_stage{stage}_texture") or "") if stage is not None else ""
                if stage == target_stage and logical:
                    hard.append({"slot": slot_index, "material": mat.name, "stage": stage, "reason": "target_image_none", "logical": logical})
                continue
            path = pathlib.Path(bpy.path.abspath(str(img.filepath or ""))) if str(img.filepath or "") else None
            ok_path = bool(path and path.is_file())
            try:
                ok_size = int(img.size[0]) > 0 and int(img.size[1]) > 0
            except Exception:
                ok_size = False
            private = bool(path and paint_root in path.parents)
            row = {"slot": slot_index, "material": mat.name, "stage": stage, "image": img.name, "path": str(path) if path else None, "path_exists": ok_path, "size_ok": ok_size, "private": private}
            rows.append(row)
            if not ok_path or not ok_size or not private:
                hard.append(row)
    return rows, hard


def _direct_select_only(proxy):
    # Avoid context-sensitive bpy.ops.object.select_all(), which fails after
    # Blender workspace switches on 5.x.
    for obj in bpy.context.view_layer.objects:
        try:
            obj.select_set(False)
        except Exception:
            pass
    proxy.hide_set(False)
    proxy.hide_viewport = False
    proxy.select_set(True)
    bpy.context.view_layer.objects.active = proxy


def _configure_artist_areas(radius: float):
    wm = bpy.context.window_manager
    view_areas = 0
    converted_image_areas = 0
    for window in list(wm.windows):
        screen = window.screen
        if screen is None:
            continue
        # The stock Texture Paint workspace opens a giant UV/Image editor.
        # That is useful to technical artists but overwhelming for this map
        # family (34k faces, tiled UVs). Convert it to another 3D paint view.
        for area in list(screen.areas):
            if area.type == "IMAGE_EDITOR":
                try:
                    area.type = "VIEW_3D"
                    converted_image_areas += 1
                except Exception:
                    pass
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            view_areas += 1
            space = area.spaces.active
            space.clip_start = max(0.001, radius / 100000.0)
            space.clip_end = max(1000.0, radius * 100.0)
            try:
                space.shading.type = "MATERIAL"
            except Exception:
                pass
            try:
                space.overlay.show_floor = False
                space.overlay.show_axis_x = False
                space.overlay.show_axis_y = False
                space.overlay.show_axis_z = False
                space.overlay.show_extras = False
                space.overlay.show_relationship_lines = False
            except Exception:
                pass
            r3d = space.region_3d
            r3d.view_location = Vector((0.0, 0.0, 0.0))
            # Start close enough to paint, but not inside the mesh.
            r3d.view_distance = max(5.0, radius * 0.55)
            try:
                r3d.view_perspective = "PERSP"
            except Exception:
                pass
    return view_areas, converted_image_areas


def _configure_texture_paint_workspace(proxy, radius: float):
    wm = bpy.context.window_manager
    for window in list(wm.windows):
        ws = bpy.data.workspaces.get("Texture Paint")
        if ws is not None:
            try:
                window.workspace = ws
            except Exception:
                pass

    def finish_ui():
        _direct_select_only(proxy)
        _hide_paint_clutter()
        view_areas, converted = _configure_artist_areas(radius)

        mode_status = "OBJECT_FALLBACK"
        try:
            if bpy.context.object == proxy:
                bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
                mode_status = "TEXTURE_PAINT"
        except Exception as exc:
            print(f"PT_STAGE072_PAINT_MODE=OBJECT_FALLBACK reason={type(exc).__name__}:{exc}")

        print(
            "PT_STAGE072_PAINT_UI=PASS "
            f"view3d_areas={view_areas} converted_image_editors={converted} "
            f"mode={mode_status} workspace=Texture Paint helpers_hidden=true"
        )
        return None

    bpy.app.timers.register(finish_ui, first_interval=0.35)


def configure_stage072_paint():
    a = _parse_args()
    paint_root = pathlib.Path(a.paint_root).resolve()
    paint_root.mkdir(parents=True, exist_ok=True)
    if a.stage < 0 or a.stage > 7:
        raise RuntimeError("paint stage must be 0..7")

    # Build the same disposable floating-origin view first.
    view.configure_stage072_view()
    proxies = [
        o for o in bpy.data.objects
        if o.type == "MESH" and bool(o.get("pt_stage072_view_proxy"))
    ]
    if not proxies:
        print("PT_STAGE072_PAINT=FAIL reason=no_view_proxy")
        return None
    proxy = proxies[0]
    radius = float(bpy.context.scene.get("pt_stage072_view_radius") or 1000.0)

    uv_stats, active_paint_uv = _make_paint_uv_layers(proxy, int(a.stage))
    manifest_rows: list[dict] = []
    _duplicate_materials_for_paint(proxy, paint_root, int(a.stage), manifest_rows)
    private_rows, private_hard = _validate_private_paint_images(proxy, paint_root, int(a.stage))
    if private_hard:
        raise RuntimeError(f"private paint image validation failed: {private_hard[:5]}")

    proxy["pt_stage072_paint_proxy"] = True
    proxy["pt_stage072_paint_stage"] = int(a.stage)
    proxy["pt_stage072_paint_uv_layer"] = active_paint_uv.name
    proxy["pt_stage072_paint_active_source_uv"] = f"{SOURCE_UV_PREFIX}{int(a.stage)}"
    proxy["pt_stage072_paint_warning"] = "PAINT_UV_IS_VIEW_ONLY_SOURCE_TEXLINK_UV_UNCHANGED"
    bpy.context.scene["pt_stage072_paint_root"] = str(paint_root)
    bpy.context.scene["pt_stage072_paint_stage"] = int(a.stage)
    bpy.context.scene["pt_stage072_paint_semantics"] = "SAFE_TEXTURE_COPY_PLUS_NORMALIZED_FLOATING_ORIGIN_SOURCE_UV_PAINT"

    manifest = {
        "format": "PT_STAGE072_TEXTURE_PAINT_WORKSPACE_V1",
        "paint_stage": int(a.stage),
        "paint_root": str(paint_root),
        "paint_uv_layer": active_paint_uv.name,
        "source_uv_layers_unchanged": True,
        "client_textures_modified": False,
        "paint_texture_files_are_private_copies": True,
        "uv_policy": "SOURCE_UV_ACTIVE_FOR_PAINT; REBASED_UV_DIAGNOSTIC_ONLY",
        "uv_stats": uv_stats,
        "material_images": manifest_rows,
        "private_image_validation": private_rows,
        "private_image_validation_pass": True,
    }
    manifest_path = paint_root / "paint_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Save a distinct, non-certified working .blend.  Ctrl+S is therefore safe
    # for viewport/workspace state, and images point only to private copies.
    workspace_blend = paint_root / "stage072_texture_paint_workspace.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(workspace_blend), check_existing=False)

    _configure_texture_paint_workspace(proxy, radius)

    target_stat = next(x for x in uv_stats if x["stage"] == int(a.stage))
    print(
        "PT_STAGE072_PAINT=PASS "
        f"stage={int(a.stage)} "
        f"paint_uv={active_paint_uv.name} "
        f"source_uv_bounds={target_stat['source_bounds']} "
        f"paint_uv_bounds={target_stat['paint_bounds']} "
        f"private_images={len({x['paint_file'] for x in manifest_rows if x.get('paint_file')})} "
        f"private_image_validation=PASS "
        f"workspace={workspace_blend} "
        "source_uv_unchanged=true client_modified=false"
    )
    return None


if __name__ == "__main__":
    bpy.app.timers.register(configure_stage072_paint, first_interval=0.35)
