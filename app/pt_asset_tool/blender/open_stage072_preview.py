from __future__ import annotations

import math
import pathlib
import sys

import bpy
from mathutils import Matrix, Vector, Euler

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pt_asset_tool.stage072_view_axes import GAME_TO_BLENDER_VIEW_MATRIX, VIEW_AXIS_PROFILE



VIEW_COLLECTION = "PT_STAGE072_VIEW_PROXY"
VIEW_LIGHT_COLLECTION = "PT_STAGE072_VIEW_LIGHTS"
VIEW_STAGE_PREFIX = "PT_STAGE072_VIEW_STAGE"
VIEW_LIGHT_PREFIX = "PT_STAGE072_VIEW_LIGHT_"
VIEW_CENTER_NAME = "PT_STAGE072_VIEW_CENTER"


def _source_stage_meshes():
    """Return only persisted/certified Stage0.72 source meshes.

    View proxies deliberately do not carry pt_stage072_source_sha256, so the
    writer/transport tooling cannot mistake them for source-space meshes.
    """
    return [
        o for o in bpy.data.objects
        if o.type == "MESH" and o.get("pt_stage072_source_sha256")
    ]


def _world_bounds(objects):
    first = True
    mn = Vector((0.0, 0.0, 0.0))
    mx = Vector((0.0, 0.0, 0.0))
    for obj in objects:
        mw = obj.matrix_world
        for v in obj.data.vertices:
            p = mw @ v.co
            if first:
                mn = p.copy()
                mx = p.copy()
                first = False
            else:
                mn.x = min(mn.x, p.x)
                mn.y = min(mn.y, p.y)
                mn.z = min(mn.z, p.z)
                mx.x = max(mx.x, p.x)
                mx.y = max(mx.y, p.y)
                mx.z = max(mx.z, p.z)
    if first:
        return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0))
    return mn, mx


def _remove_collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        return
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(col)


def _new_collection(name):
    _remove_collection(name)
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def _copy_custom_properties(src, dst):
    for key in src.keys():
        try:
            dst[key] = src[key]
        except Exception:
            pass


def _build_stage_view_proxies(source_objects, center, view_scale):
    """Build disposable, origin-centred display meshes.

    The persisted .blend and source SMD are not saved or modified.  Each proxy
    receives a private mesh copy whose vertices are transformed from source
    world space into floating-origin view space: view = source_world - center.
    The original Stage mesh is hidden only for this Blender session.
    """
    col = _new_collection(VIEW_COLLECTION)
    proxies = []

    # Convert the legacy Y-up, left-handed Stage basis to Blender Z-up,
    # right-handed coordinates. The determinant -1 fixes preview face winding
    # (Ricarten ground is otherwise visible from underneath, not from above).
    # Only this disposable proxy receives the transform: source mesh/SMD,
    # face order, normals, texlinks and UV data stay unchanged.
    # Float32 safety: never compose the huge absolute source translation with
    # the small normalized scale before applying it to geometry. Blender's
    # Matrix/mesh coordinates are binary32; precomposing scale @ translation
    # loses low bits for stages placed far from the game-world origin (e.g.
    # Field/Boss/dark_boss.smd, centre approximately X=198296, Z=241892).
    #
    # Sequential mesh transforms first bring the world coordinates near zero,
    # then scale and convert Y-up to Blender Z-up. This preserves the existing
    # determinant -1 / face-winding behavior and all UV/material attributes.
    # Only the private proxy mesh is transformed; the source mesh is untouched.
    axis_matrix = Matrix(GAME_TO_BLENDER_VIEW_MATRIX)
    center_translation = Matrix.Translation(-center)
    normalized_scale = Matrix.Scale(float(view_scale), 4)
    for idx, src in enumerate(source_objects):
        mesh = src.data.copy()
        mesh.name = f"{src.data.name}_VIEW_PROXY"
        mesh.transform(src.matrix_world)
        mesh.transform(center_translation)
        mesh.transform(normalized_scale)
        mesh.transform(axis_matrix)
        mesh.update()

        name = VIEW_STAGE_PREFIX if idx == 0 else f"{VIEW_STAGE_PREFIX}_{idx:02d}"
        proxy = bpy.data.objects.new(name, mesh)
        col.objects.link(proxy)
        proxy.matrix_world = Matrix.Identity(4)
        proxy["pt_stage072_view_proxy"] = True
        proxy["pt_stage072_view_only"] = True
        proxy["pt_stage072_source_object"] = src.name
        proxy["pt_stage072_source_world_center"] = [float(x) for x in center]
        proxy["pt_stage072_view_transform"] = "BLENDER_VIEW=SWAP_YZ((SOURCE_WORLD_POSITION-SOURCE_BOUNDS_CENTER)*VIEW_SCALE)"
        proxy["pt_stage072_view_scale"] = float(view_scale)
        proxy["pt_stage072_view_axis_profile"] = VIEW_AXIS_PROFILE
        proxies.append(proxy)

        src.hide_set(True)
        src.hide_render = True

    return proxies


def _build_light_view_proxies(center, view_scale):
    """Rebase source light-metadata empties for usable viewport inspection."""
    col = _new_collection(VIEW_LIGHT_COLLECTION)
    source_lights = [
        o for o in bpy.data.objects
        if o.type == "EMPTY" and o.name.startswith("PT_STAGE072_LIGHT_")
        and not o.name.startswith(VIEW_LIGHT_PREFIX)
    ]

    axis = Matrix(GAME_TO_BLENDER_VIEW_MATRIX).to_3x3()
    for src in source_lights:
        suffix = src.name.removeprefix("PT_STAGE072_LIGHT_")
        proxy = bpy.data.objects.new(f"{VIEW_LIGHT_PREFIX}{suffix}", None)
        proxy.empty_display_type = "SPHERE"
        proxy.empty_display_size = float(getattr(src, "empty_display_size", 1.0) or 1.0)
        source_world = src.matrix_world.translation.copy()
        proxy.location = axis @ ((source_world - center) * float(view_scale))
        proxy.hide_render = True
        proxy["pt_stage072_view_proxy"] = True
        proxy["pt_stage072_view_only"] = True
        proxy["pt_stage072_source_object"] = src.name
        proxy["pt_stage072_source_world_location"] = [float(x) for x in source_world]
        proxy["pt_stage072_view_location"] = [float(x) for x in proxy.location]
        proxy["pt_stage072_view_scale"] = float(view_scale)
        proxy["pt_stage072_view_axis_profile"] = VIEW_AXIS_PROFILE
        _copy_custom_properties(src, proxy)
        col.objects.link(proxy)

        src.hide_set(True)
        src.hide_render = True

    # Hide the original source-light collection as a whole when present.  Its
    # exact integer metadata remains in the .blend and on every source empty.
    source_col = bpy.data.collections.get("PT_STAGE072_LIGHT_METADATA")
    if source_col is not None:
        source_col.hide_viewport = True
        source_col.hide_render = True

    return len(source_lights)


def set_stage_view_rotation(region_3d):
    """Start above the Y-up game ground (Blender +Z), with a slight tilt."""
    region_3d.view_rotation = Euler((math.radians(38.0), 0.0, math.radians(-25.0)), 'XYZ').to_quaternion()


def _configure_viewports(radius):
    configured = 0
    wm = bpy.context.window_manager
    for window in list(wm.windows):
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            # After floating-origin rebasing, near/far clipping can be tied to
            # map size instead of the large absolute game-world offset.
            space.clip_start = max(0.01, radius / 1_000_000.0)
            space.clip_end = max(100_000.0, radius * 100.0)
            try:
                space.shading.type = "MATERIAL"
            except Exception:
                pass
            try:
                space.overlay.show_floor = False
                space.overlay.show_axis_x = False
                space.overlay.show_axis_y = False
                space.overlay.show_axis_z = False
            except Exception:
                pass
            r3d = space.region_3d
            r3d.view_location = Vector((0.0, 0.0, 0.0))
            r3d.view_distance = max(10.0, radius * 1.35)
            set_stage_view_rotation(r3d)
            try:
                r3d.view_perspective = "PERSP"
            except Exception:
                pass
            configured += 1
    return configured


def configure_stage072_view():
    source_objects = _source_stage_meshes()
    if not source_objects:
        print("PT_STAGE072_VIEW=FAIL reason=no_stage072_source_mesh")
        return None

    scene = bpy.context.scene
    mn, mx = _world_bounds(source_objects)
    center = (mn + mx) * 0.5
    dims = mx - mn
    source_max_dim = max(1.0, max(float(dims.x), float(dims.y), float(dims.z)))
    radius = max(1.0, 0.5 * source_max_dim)
    # View-only normalization: keep large Stage0.72 world coordinates out of
    # Blender navigation math. The certified source mesh is never scaled.
    # A ~100-unit map behaves naturally with wheel zoom, orbit and paint brush.
    view_target_max_dim = 100.0
    view_scale = min(1.0, view_target_max_dim / source_max_dim)
    view_radius = max(1.0, radius * view_scale)

    scene["pt_stage072_source_bounds_center"] = [float(x) for x in center]
    scene["pt_stage072_source_bounds_min"] = [float(x) for x in mn]
    scene["pt_stage072_source_bounds_max"] = [float(x) for x in mx]
    scene["pt_stage072_source_radius"] = float(radius)
    scene["pt_stage072_view_radius"] = float(view_radius)
    scene["pt_stage072_view_scale"] = float(view_scale)
    scene["pt_stage072_view_semantics"] = "DISPOSABLE_FLOATING_ORIGIN_SCALED_PROXY_SOURCE_DATA_UNCHANGED"
    scene["pt_stage072_view_axis_profile"] = VIEW_AXIS_PROFILE
    scene["pt_stage072_view_basis_determinant"] = -1
    scene["pt_stage072_view_offset"] = [float(-x) for x in center]

    # Avoid displaying the game coordinates as kilometres/metres in the viewer.
    # This is UI state only; source coordinates retain their exact 1/256 values.
    try:
        scene.unit_settings.system = "NONE"
        scene.unit_settings.scale_length = 1.0
    except Exception:
        pass

    proxies = _build_stage_view_proxies(source_objects, center, view_scale)
    light_count = _build_light_view_proxies(center, view_scale)

    # In view space the useful map centre is exactly the Blender origin.  Use a
    # supported Empty display type across Blender 4.x/5.x (CROSS is not valid).
    marker = bpy.data.objects.get(VIEW_CENTER_NAME)
    if marker is None:
        marker = bpy.data.objects.new(VIEW_CENTER_NAME, None)
        bpy.context.scene.collection.objects.link(marker)
    marker.location = (0.0, 0.0, 0.0)
    marker.empty_display_type = "PLAIN_AXES"
    marker.empty_display_size = max(0.5, view_radius * 0.02)
    marker.hide_render = True
    marker["pt_stage072_preview_helper"] = True
    marker["pt_stage072_source_world_center"] = [float(x) for x in center]

    scene.cursor.location = (0.0, 0.0, 0.0)

    bpy.ops.object.select_all(action="DESELECT")
    for proxy in proxies:
        proxy.hide_set(False)
        proxy.hide_viewport = False
        proxy.select_set(True)
    if proxies:
        bpy.context.view_layer.objects.active = proxies[0]

    configured = _configure_viewports(view_radius)

    print(
        "PT_STAGE072_VIEW=PASS "
        "mode=FLOATING_ORIGIN_SCALED_PROXY "
        f"axis_profile={VIEW_AXIS_PROFILE} face_winding=VIEW_ONLY_HANDEDNESS_CONVERTED "
        f"source_center=({center.x:.6f},{center.y:.6f},{center.z:.6f}) "
        f"source_dims=({dims.x:.6f},{dims.y:.6f},{dims.z:.6f}) "
        f"view_scale={view_scale:.9g} view_max_dim={source_max_dim * view_scale:.6f} "
        f"proxy_meshes={len(proxies)} proxy_lights={light_count} "
        f"view3d_areas={configured} "
        "source_coordinates_unchanged=true persisted_blend_unsaved=true"
    )
    return None


# When launched with a .blend plus --python, UI areas are normally available,
# but a short timer covers startup/workspace restoration races.
if __name__ == "__main__":
    bpy.app.timers.register(configure_stage072_view, first_interval=0.35)
