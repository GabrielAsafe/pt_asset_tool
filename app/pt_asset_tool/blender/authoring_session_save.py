from __future__ import annotations
import argparse, sys
from pathlib import Path
import bpy
from bpy.app.handlers import persistent

WORKSPACE=Path(".").resolve()

def args_after_ddash():
    return sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []

def under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False

@persistent
def save_overlay_images(_dummy):
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
        except Exception:
            raw=""
        if not raw:
            blocked.append(img.name); continue
        p=Path(raw).expanduser().resolve()
        if not under(p,WORKSPACE):
            blocked.append(img.name); continue
        try:
            p.parent.mkdir(parents=True,exist_ok=True)
            img.save()
            saved.append(img.name)
        except Exception as exc:
            print(f"PT_AUTHORING_SAVE image_error={img.name} {type(exc).__name__}:{exc}")
    if saved:
        print("PT_AUTHORING_SAVE overlay_images_saved="+",".join(saved[:16]))
    if blocked:
        print("PT_AUTHORING_SAVE blocked_outside_workspace="+",".join(blocked[:16]))

def main():
    global WORKSPACE
    ap=argparse.ArgumentParser()
    ap.add_argument("--workspace",required=True)
    a=ap.parse_args(args_after_ddash())
    WORKSPACE=Path(a.workspace).resolve()
    if save_overlay_images not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_overlay_images)
    print("PT_AUTHORING_SESSION_SAVE_V1")
    print(f"workspace={WORKSPACE}")
    print("trigger=BLENDER_SAVE_ONLY")
    print("overlay_policy=PT_BUILD_MATERIALIZED_FILES_ONLY")
    print("timers=false")
    print("mode_watchers=false")
    print("action_watchers=false")
    print("client_modified=false")

if __name__=="__main__":
    main()
