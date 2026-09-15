from __future__ import annotations

import bpy


def configure():
    if bpy.context.screen is None:
        return 0.5
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and str(o.get("pt_rare_role", "")) in {"ROOT", "RARE"} and not o.hide_render]
    rare = [o for o in meshes if str(o.get("pt_rare_role", "")) == "RARE"]
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE" and o.name == "PT_RARE_CONTEXT_ARMATURE"]
    for arm in arms:
        try:
            arm.hide_set(True)
        except Exception:
            arm.hide_viewport = True
    if not meshes:
        print("PT_RARE_RIGID_VIEW=FAIL reason=no_visible_meshes")
        return None

    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = rare[0] if rare else meshes[0]

    areas = 0
    for area in bpy.context.screen.areas:
        if area.type != "VIEW_3D":
            continue
        areas += 1
        space = area.spaces.active
        space.clip_start = 0.01
        space.clip_end = 100000.0
        space.shading.type = "MATERIAL"
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is not None:
            try:
                with bpy.context.temp_override(area=area, region=region, space_data=space):
                    bpy.ops.view3d.view_selected(use_all_regions=False)
            except Exception as exc:
                print(f"PT_RARE_RIGID_VIEW_WARN frame={type(exc).__name__}:{exc}")

    # Leave only the rare piece selected after framing; root is context.
    for o in meshes:
        o.select_set(o in rare)
    if rare:
        bpy.context.view_layer.objects.active = rare[0]
    print(
        f"PT_RARE_RIGID_VIEW=PASS visible_meshes={len(meshes)} rare_visible={len(rare)} "
        f"view3d_areas={areas} root_context=true write_authorized=false"
    )
    return None


bpy.app.timers.register(configure, first_interval=0.8)
