from __future__ import annotations
import argparse, json, pathlib, sys
import bpy, bmesh

def parse(argv):
    p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True); return p.parse_args(argv)

def configure(mp):
    m=json.loads(pathlib.Path(mp).read_text(encoding='utf-8'))
    wanted={str(k):[int(x) for x in v] for k,v in m['selected_vertices_by_object'].items()}
    in_mode=sorted(int(o.get('pt_source_object_index',-1)) for o in bpy.context.objects_in_mode if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE')
    if in_mode!=sorted(int(k) for k in wanted): raise RuntimeError(f'MANUAL_OBJECTS_IN_MODE_MISMATCH:{in_mode}')
    actual={}
    for o in bpy.context.objects_in_mode:
        if o.type!='MESH' or str(o.get('pt_rare_role',''))!='RARE': continue
        oi=int(o.get('pt_source_object_index',-1)); bm=bmesh.from_edit_mesh(o.data)
        actual[str(oi)]=sorted(v.index for v in bm.verts if v.select)
        o.lock_location=(True,True,True); o.lock_rotation=(True,True,True); o.lock_scale=(True,True,True)
    if actual!=wanted: raise RuntimeError(f'MANUAL_SELECTION_MISMATCH:{actual}!={wanted}')
    ts=bpy.context.scene.tool_settings; ts.mesh_select_mode=(True,False,False)
    try: ts.use_proportional_edit='DISABLED'
    except Exception: pass
    if hasattr(ts,'use_mesh_automerge'): ts.use_mesh_automerge=False
    if hasattr(ts,'use_mesh_automerge_and_split'): ts.use_mesh_automerge_and_split=False
    axis=str(m['uniform_axis']).upper(); delta=float(m['uniform_delta_world'])
    text=f"PT V0.8.28: move 4 selected vertices across 2 objects: G {axis} {delta:g} Enter; Ctrl+S; close Blender"
    bpy.context.scene['pt_v0828_manual_cross_object_instruction']=text
    try: bpy.context.workspace.status_text_set(text)
    except Exception: pass
    print('PT_V0828_MANUAL_UI=READY '+text)

def main(argv):
    a=parse(argv); mp=str(pathlib.Path(a.manifest).resolve()); bpy.app.timers.register(lambda:configure(mp),first_interval=0.7)
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
