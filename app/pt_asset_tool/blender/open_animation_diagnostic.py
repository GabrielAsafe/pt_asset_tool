from __future__ import annotations
import bpy


def configure_and_play():
    scene=bpy.context.scene
    scene.frame_set(scene.frame_start)
    cam=scene.camera
    # Force every available 3D viewport into the saved diagnostic camera so
    # the pair opens centered instead of inheriting an arbitrary old view.
    for window in bpy.context.window_manager.windows:
        screen=window.screen
        for area in screen.areas:
            if area.type!='VIEW_3D':
                continue
            space=area.spaces.active
            if cam is not None:
                space.region_3d.view_perspective='CAMERA'
            space.overlay.show_relationship_lines=False
    try:
        bpy.ops.screen.animation_play()
    except RuntimeError:
        pass
    return None

# UI areas are fully available on the next event-loop tick.
bpy.app.timers.register(configure_and_play, first_interval=0.15)
