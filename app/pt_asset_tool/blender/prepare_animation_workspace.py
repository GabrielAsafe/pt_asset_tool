from __future__ import annotations
import argparse, sys
from pathlib import Path
import bpy

def args_after_ddash():
    return sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []

def action_by_name(name):
    if not name:
        return None
    a=bpy.data.actions.get(name)
    if a is not None:
        return a
    q=str(name).upper()
    for x in bpy.data.actions:
        if x.name.upper()==q or str(x.get("pt_state_name","")).upper()==q:
            return x
    return None

def find_armatures():
    return [o for o in bpy.data.objects if o.type=="ARMATURE"]

def find_primary_mesh():
    meshes=[o for o in bpy.data.objects if o.type=="MESH"]
    if not meshes:
        return None
    def score(o):
        arm_mod=sum(1 for m in o.modifiers if m.type=="ARMATURE")
        verts=len(o.data.vertices) if getattr(o,"data",None) else 0
        return (arm_mod,verts)
    return max(meshes,key=score)

def configure(action_name):
    action=action_by_name(action_name)
    for arm in find_armatures():
        arm.data.pose_position='POSE'
        try: arm.data.display_type='STICK'
        except Exception: pass
        try: arm.show_in_front=True
        except Exception: pass
        # Prevent accidental armature Edit Mode in a paint/visual workspace.
        # The user can re-enable selection manually from the Outliner if needed.
        arm.hide_select=True
        for b in arm.data.bones:
            if b.name.startswith("PT_AFF_") or bool(b.get("pt_affine_role")):
                b.hide=True
        if action is not None and arm.animation_data:
            arm.animation_data.action=action
            if hasattr(action,'slots') and len(action.slots):
                try: arm.animation_data.action_slot=action.slots[0]
                except Exception: pass

    for obj in bpy.data.objects:
        if obj.type!="MESH":
            continue
        for mod in obj.modifiers:
            if mod.type=="ARMATURE":
                try: mod.show_viewport=True
                except Exception: pass
                try: mod.show_in_editmode=True
                except Exception: pass
                # Keep armature evaluation visible in Edit Mode without
                # forcing it onto Blender's editable cage.  show_on_cage can
                # destabilize mode/paint transitions on this legacy rig.
                try: mod.show_on_cage=False
                except Exception: pass

    if action is not None:
        lo,hi=action.frame_range
        bpy.context.scene.frame_start=max(1,int(lo))
        bpy.context.scene.frame_end=max(bpy.context.scene.frame_start,int(hi))
        bpy.context.scene.frame_set(bpy.context.scene.frame_start)

    try:
        if bpy.context.object and bpy.context.object.mode!="OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    for o in bpy.context.selected_objects:
        o.select_set(False)
    mesh=find_primary_mesh()
    if mesh is not None:
        mesh.hide_select=False
        mesh.hide_set(False)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active=mesh

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True)
    ap.add_argument("--action",default="")
    a=ap.parse_args(args_after_ddash())
    configure(a.action)
    out=Path(a.out).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    print("PT_PREPARE_ANIMATION_WORKSPACE_V1")
    print(f"action={a.action}")
    print(f"out={out}")
    print("affine_helpers_hidden=true")
    print("mesh_edit_deform_cage=true")
    print("images_packed=false")
    print("paint_storage=PT_BUILD_OVERLAY_FILES")
    print("client_modified=false")

if __name__=="__main__":
    main()
