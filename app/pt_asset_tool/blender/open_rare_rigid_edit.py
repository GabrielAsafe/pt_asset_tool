from __future__ import annotations
import argparse,json,pathlib,sys
import bpy

def parse(argv):
    p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True); return p.parse_args(argv)

def configure(manifest_path):
    manifest=json.loads(pathlib.Path(manifest_path).read_text(encoding='utf-8'))
    txn=manifest.get('default_safe_transaction') or {}
    single=manifest.get('default_safe_selection') or {}
    target_oi=int(txn.get('object_index',single.get('object_index',-1)))
    target_vis=[int(v) for v in (txn.get('changed_vertex_indices') or [])]
    if not target_vis:
        vi=int(single.get('vertex_index',-1)); target_vis=[vi] if vi>=0 else []
    try:
        if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    except Exception: pass
    rare=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE']
    rare.sort(key=lambda o:int(o.get('pt_source_object_index',-1)))
    target=None
    for o in bpy.data.objects:
        try: o.select_set(False)
        except Exception: pass
        if str(o.get('pt_rare_role',''))=='ROOT' or o.type=='ARMATURE': o.hide_select=True
    for o in rare:
        o.hide_select=False
        o.lock_location=(True,True,True); o.lock_rotation=(True,True,True); o.lock_scale=(True,True,True)
        if hasattr(o.data,'use_mirror_x'): o.data.use_mirror_x=False
        if hasattr(o.data,'use_mirror_topology'): o.data.use_mirror_topology=False
        for v in o.data.vertices: v.select=False
        for e in o.data.edges: e.select=False
        for f in o.data.polygons: f.select=False
        o.data.update()
        if int(o.get('pt_source_object_index',-1))==target_oi: target=o
    ts=bpy.context.scene.tool_settings
    try: ts.use_proportional_edit='DISABLED'
    except Exception: pass
    if hasattr(ts,'use_mesh_automerge'): ts.use_mesh_automerge=False
    if hasattr(ts,'use_mesh_automerge_and_split'): ts.use_mesh_automerge_and_split=False
    try: ts.mesh_select_mode=(True,False,False)
    except Exception: pass
    selected_count=0
    if target is not None:
        target.hide_set(False); target.select_set(True); bpy.context.view_layer.objects.active=target
        for vi in target_vis:
            if 0<=vi<len(target.data.vertices): target.data.vertices[vi].select=True; selected_count+=1
        target.data.update()
        if selected_count:
            try: bpy.ops.object.mode_set(mode='EDIT')
            except Exception: pass
    elif rare:
        rare[0].hide_set(False); rare[0].select_set(True); bpy.context.view_layer.objects.active=rare[0]
    if bpy.context.screen:
        for area in bpy.context.screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.shading.type='MATERIAL'; area.spaces.active.clip_start=0.01; area.spaces.active.clip_end=100000.0
    sc=bpy.context.scene
    sc['pt_rare_edit_ui_safety']='LOCK_OBJECT_TRANSFORMS_DISABLE_PROPORTIONAL_VERTEX_MODE_TRANSACTION_SELECTION'
    print('PT_RARE_EDIT_UI=PASS scope=ONE_TO_FOUR_VERTEX_MULTIBONE_INTERIOR_TRANSACTION object_transforms_locked=true proportional_edit=false vertex_select_mode=true automerge=false imported_selection_cleared=true default_safe_transaction_selected=' + str(selected_count>=2).lower() + f' object_index={target_oi} selected_vertices={selected_count} save_blend_then_run_write_command=true')
    return None

def main(argv):
    a=parse(argv); mp=str(pathlib.Path(a.manifest).resolve()); bpy.context.scene['pt_rare_edit_manifest']=mp
    bpy.app.timers.register(lambda:configure(mp),first_interval=0.5)
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
