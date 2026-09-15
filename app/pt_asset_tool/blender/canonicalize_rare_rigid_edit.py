from __future__ import annotations
import pathlib, sys
import bpy


def main():
    # Force a stable persisted Object Mode representation. No geometry operation is performed.
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    path=pathlib.Path(bpy.data.filepath).resolve()
    if not str(path): raise RuntimeError('blend has no filepath')
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    print(f'PT_RARE_EDIT_CANONICALIZE=PASS blend={path}')
if __name__=='__main__': main()
