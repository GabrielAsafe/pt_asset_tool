from __future__ import annotations
import argparse, sys
from pathlib import Path
import bpy

def args_after_ddash():
    return sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []

def resolve_action(value):
    q=str(value or "").strip()
    a=bpy.data.actions.get(q)
    if a is not None:
        return a
    uq=q.upper()
    matches=[x for x in bpy.data.actions if x.name.upper()==uq or str(x.get("pt_state_name","")).upper()==uq]
    if len(matches)==1:
        return matches[0]
    raise RuntimeError(f"action not found/ambiguous: {value}; available={[x.name for x in bpy.data.actions]}")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--action",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args(args_after_ddash())
    action=resolve_action(a.action)
    arms=[o for o in bpy.data.objects if o.type=="ARMATURE"]
    if not arms:
        raise RuntimeError("no armature in animation workspace")
    for arm in arms:
        arm.data.pose_position='POSE'
        if arm.animation_data:
            arm.animation_data.action=action
            if hasattr(action,'slots') and len(action.slots):
                try: arm.animation_data.action_slot=action.slots[0]
                except Exception: pass
        for b in arm.data.bones:
            if b.name.startswith("PT_AFF_") or bool(b.get("pt_affine_role")):
                b.hide=True
        arm.hide_select=True
    lo,hi=action.frame_range
    bpy.context.scene.frame_start=max(1,int(lo))
    bpy.context.scene.frame_end=max(bpy.context.scene.frame_start,int(hi))
    bpy.context.scene.frame_set(bpy.context.scene.frame_start)
    for obj in bpy.data.objects:
        if obj.type=="MESH":
            for mod in obj.modifiers:
                if mod.type=="ARMATURE":
                    try: mod.show_in_editmode=True
                    except Exception: pass
                    try: mod.show_on_cage=True
                    except Exception: pass
    out=Path(a.out).resolve()
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    print("PT_SELECT_ANIMATION_ACTION_V1")
    print(f"selected_action={action.name}")
    print(f"out={out}")
    print("client_modified=false")

if __name__=="__main__":
    main()
