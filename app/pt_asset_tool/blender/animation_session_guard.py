from __future__ import annotations
import argparse
import sys
from pathlib import Path
import bpy

WORKSPACE = Path(".").resolve()
_last_actions = {}
_last_paint_mode = False

def args_after_ddash():
    return sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []

def resolve_action(value):
    if not value:
        return None
    a=bpy.data.actions.get(value)
    if a is not None:
        return a
    uq=str(value).upper()
    matches=[x for x in bpy.data.actions if x.name.upper()==uq or str(x.get("pt_state_name","")).upper()==uq]
    return matches[0] if len(matches)==1 else None

def armatures():
    return [o for o in bpy.data.objects if o.type=="ARMATURE"]

def primary_mesh():
    meshes=[o for o in bpy.data.objects if o.type=="MESH"]
    if not meshes:
        return None
    return max(meshes,key=lambda o:(sum(1 for m in o.modifiers if m.type=="ARMATURE"),len(o.data.vertices)))

def _apply_action_state(arm, action):
    if action is None or arm.animation_data is None:
        return
    if hasattr(action,'slots') and len(action.slots):
        try:
            current=getattr(arm.animation_data,"action_slot",None)
            if current not in list(action.slots):
                arm.animation_data.action_slot=action.slots[0]
        except Exception:
            try: arm.animation_data.action_slot=action.slots[0]
            except Exception: pass
    try:
        lo,hi=action.frame_range
        start=max(1,int(lo)); end=max(start,int(hi))
        bpy.context.scene.frame_start=start
        bpy.context.scene.frame_end=end
        cur=int(bpy.context.scene.frame_current)
        bpy.context.scene.frame_set(start if cur < start or cur > end else cur)
        bpy.context.view_layer.update()
    except Exception as exc:
        print(f"PT_ANIM_SESSION action_state_error={type(exc).__name__}:{exc}")

def configure(action_name):
    action=resolve_action(action_name)
    for arm in armatures():
        arm.data.pose_position='POSE'
        try: arm.data.display_type='STICK'
        except Exception: pass
        try: arm.show_in_front=True
        except Exception: pass
        arm.hide_select=True
        for b in arm.data.bones:
            if b.name.startswith("PT_AFF_") or bool(b.get("pt_affine_role")):
                b.hide=True
        if action is not None and arm.animation_data:
            arm.animation_data.action=action
            _apply_action_state(arm,action)

    for obj in bpy.data.objects:
        if obj.type!="MESH":
            continue
        for mod in obj.modifiers:
            if mod.type=="ARMATURE":
                try: mod.show_viewport=True
                except Exception: pass
                try: mod.show_in_editmode=True
                except Exception: pass
                try: mod.show_on_cage=False
                except Exception: pass

    try:
        if bpy.context.object and bpy.context.object.mode!="OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    for o in list(bpy.context.selected_objects):
        o.select_set(False)
    mesh=primary_mesh()
    if mesh is not None:
        mesh.hide_select=False
        mesh.hide_set(False)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active=mesh

def maintain_action_and_mode_state():
    for arm in armatures():
        arm.data.pose_position='POSE'
        ad=arm.animation_data
        action=ad.action if ad else None
        name=action.name if action else None
        if name != _last_actions.get(arm.name):
            _apply_action_state(arm,action)
            _last_actions[arm.name]=name
            if name:
                arm["pt_selected_action"]=name
                print(f"PT_ANIM_SESSION action_changed={name}")
        for b in arm.data.bones:
            if b.name.startswith("PT_AFF_") or bool(b.get("pt_affine_role")):
                b.hide=True
    for obj in bpy.data.objects:
        if obj.type=="MESH":
            for mod in obj.modifiers:
                if mod.type=="ARMATURE":
                    try: mod.show_viewport=True
                    except Exception: pass
                    try: mod.show_in_editmode=True
                    except Exception: pass
                    try: mod.show_on_cage=False
                    except Exception: pass
    return 0.35

def _safe_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False

def persist_paint_after_leaving_mode():
    global _last_paint_mode
    mode=str(getattr(bpy.context,"mode",""))
    in_paint=(mode=="PAINT_TEXTURE")

    # Do absolutely no disk write while Texture Paint is active. When the user
    # leaves paint mode, save only dirty images whose physical paths are under
    # this pt_build workspace. Never save/pack the .blend from the timer.
    if _last_paint_mode and not in_paint:
        saved=[]; blocked=[]
        for img in bpy.data.images:
            try:
                dirty=bool(img.is_dirty)
            except Exception:
                dirty=False
            if not dirty:
                continue
            try:
                raw=bpy.path.abspath(img.filepath)
                p=Path(raw).expanduser().resolve() if raw else None
            except Exception:
                p=None
            if p is None or not _safe_under(p,WORKSPACE):
                blocked.append(img.name)
                continue
            try:
                p.parent.mkdir(parents=True,exist_ok=True)
                img.save()
                saved.append(img.name)
            except Exception as exc:
                print(f"PT_ANIM_SESSION image_save_error image={img.name} error={type(exc).__name__}:{exc}")
        if saved:
            print("PT_ANIM_SESSION paint_overlay_saved=true images="+",".join(saved[:8]))
        if blocked:
            print("PT_ANIM_SESSION paint_save_blocked_outside_workspace="+",".join(blocked[:8]))

    _last_paint_mode=in_paint
    return 0.35

def main():
    global WORKSPACE,_last_paint_mode
    ap=argparse.ArgumentParser()
    ap.add_argument("--workspace",required=True)
    ap.add_argument("--action",default="")
    a=ap.parse_args(args_after_ddash())
    WORKSPACE=Path(a.workspace).resolve()
    configure(a.action)
    _last_paint_mode=(str(getattr(bpy.context,"mode",""))=="PAINT_TEXTURE")
    for arm in armatures():
        ad=arm.animation_data
        action=ad.action if ad else None
        _last_actions[arm.name]=action.name if action else None
        _apply_action_state(arm,action)
    if not bpy.app.timers.is_registered(maintain_action_and_mode_state):
        bpy.app.timers.register(maintain_action_and_mode_state,first_interval=0.35,persistent=True)
    if not bpy.app.timers.is_registered(persist_paint_after_leaving_mode):
        bpy.app.timers.register(persist_paint_after_leaving_mode,first_interval=0.35,persistent=True)
    print("PT_ANIMATION_SESSION_GUARD_V2")
    print(f"workspace={WORKSPACE}")
    print(f"action={a.action}")
    print("affine_helpers_hidden=true")
    print("armature_selection_locked=true")
    print("mesh_edit_deform_visible=true")
    print("modifier_show_on_cage=false")
    print("action_slot_autofix=true")
    print("paint_persistence=OVERLAY_FILE_SAVE_AFTER_LEAVING_TEXTURE_PAINT")
    print("blend_timer_save=false")
    print("client_modified=false")

if __name__=="__main__":
    main()
