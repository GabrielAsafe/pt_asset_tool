from __future__ import annotations
import argparse, json, pathlib, sys
import bpy, bmesh

def parse(argv):
    p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True); return p.parse_args(argv)

def configure(mp):
    m=json.loads(pathlib.Path(mp).read_text(encoding='utf-8'))
    oi=int(m['object_index']); vi=int(m['vertex_index'])
    rows=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE' and int(o.get('pt_source_object_index',-1))==oi]
    if len(rows)!=1: raise RuntimeError(f'MANUAL_OBJECT_UNRESOLVED:{oi}:{len(rows)}')
    o=rows[0]; active=bpy.context.view_layer.objects.active
    if str(getattr(bpy.context,'mode','UNKNOWN'))!='EDIT_MESH' or active!=o: raise RuntimeError(f'MANUAL_MODE_ACTIVE_MISMATCH:{getattr(bpy.context,"mode","UNKNOWN")}:{getattr(active,"name",None)}')
    bm=bmesh.from_edit_mesh(o.data); bm.verts.ensure_lookup_table(); actual=sorted(v.index for v in bm.verts if v.select)
    if actual!=[vi]: raise RuntimeError(f'MANUAL_SELECTION_MISMATCH:{actual}!=[{vi}]')
    o.lock_location=(True,True,True); o.lock_rotation=(True,True,True); o.lock_scale=(True,True,True)
    ts=bpy.context.scene.tool_settings; ts.mesh_select_mode=(True,False,False)
    try: ts.use_proportional_edit='DISABLED'
    except Exception: pass
    if hasattr(ts,'use_mesh_automerge'): ts.use_mesh_automerge=False
    if hasattr(ts,'use_mesh_automerge_and_split'): ts.use_mesh_automerge_and_split=False
    axis=str(m['manual_axis']).upper(); delta=float(m['manual_delta_world'])
    text=f"PT V0.8.35: move the one selected vertex outward: G {axis} {delta:.9g} Enter; Ctrl+S; close Blender"
    bpy.context.scene['pt_v0835_manual_multibone_extent_instruction']=text
    try: bpy.context.workspace.status_text_set(text)
    except Exception: pass
    print('PT_V0835_MANUAL_UI=READY '+text)

def main(argv):
    a=parse(argv); mp=str(pathlib.Path(a.manifest).resolve()); bpy.app.timers.register(lambda:configure(mp),first_interval=0.7)
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
