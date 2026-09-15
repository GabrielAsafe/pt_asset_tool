from __future__ import annotations
import argparse, json, pathlib, sys
import bpy, bmesh

FORMAT='PT_RARE_RIGID_MULTIBONE_EXTENT_MANUAL_SELECTION_V1'

def args(argv):
    p=argparse.ArgumentParser()
    p.add_argument('--object-index',type=int,required=True)
    p.add_argument('--vertex-index',type=int,required=True)
    p.add_argument('--report',required=True)
    p.add_argument('--verify-only',action='store_true')
    return p.parse_args(argv)

def rare(oi:int):
    rows=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE' and int(o.get('pt_source_object_index',-1))==oi]
    if len(rows)!=1: raise RuntimeError(f'RARE_OBJECT_UNRESOLVED_{oi}:{len(rows)}')
    return rows[0]

def selected(o):
    bm=bmesh.from_edit_mesh(o.data)
    return sorted(v.index for v in bm.verts if v.select)

def main(argv):
    a=args(argv); oi=int(a.object_index); vi=int(a.vertex_index); o=rare(oi)
    if vi<0 or vi>=len(o.data.vertices): raise RuntimeError(f'VERTEX_RANGE_{oi}_{vi}')
    if a.verify_only:
        active=bpy.context.view_layer.objects.active
        in_mode=[x for x in getattr(bpy.context,'objects_in_mode',[]) if x.type=='MESH' and str(x.get('pt_rare_role',''))=='RARE']
        if str(getattr(bpy.context,'mode','UNKNOWN'))!='EDIT_MESH' or len(in_mode)!=1 or in_mode[0]!=o or active!=o:
            raise RuntimeError(f'REOPEN_MODE_OBJECT_MISMATCH:{getattr(bpy.context,"mode","UNKNOWN")}:{[x.name for x in in_mode]}:{getattr(active,"name",None)}')
        actual=selected(o)
        if actual!=[vi]: raise RuntimeError(f'REOPEN_SELECTION_MISMATCH:{actual}!=[{vi}]')
        res={'format':FORMAT,'status':'PASS','verify_only':True,'object_index':oi,'vertex_index':vi,'selected_vertex_indices':actual,'saved_mode_raw':str(o.mode),'saved_mode':str(bpy.context.mode),'visible_selection_persisted':True,'popup_used':False}
        rp=pathlib.Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(res,indent=2)+'\n',encoding='utf-8')
        print('PT_MULTIBONE_EXTENT_MANUAL_SELECTION_VERIFY=PASS')
        return
    if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    before={x.index:tuple(x.co) for x in o.data.vertices}
    bpy.ops.object.select_all(action='DESELECT')
    for x in bpy.data.objects:
        if x.type!='MESH': continue
        x.select_set(False)
        for v in x.data.vertices: v.select=False
        for e in x.data.edges: e.select=False
        for f in x.data.polygons: f.select=False
        x.data.update()
    o.hide_set(False); o.select_set(True); bpy.context.view_layer.objects.active=o
    o.lock_location=(True,True,True); o.lock_rotation=(True,True,True); o.lock_scale=(True,True,True)
    bpy.context.tool_settings.mesh_select_mode=(True,False,False)
    bpy.ops.object.mode_set(mode='EDIT')
    if str(getattr(bpy.context,'mode','UNKNOWN'))!='EDIT_MESH': raise RuntimeError('EDIT_MODE_NOT_ENTERED')
    bm=bmesh.from_edit_mesh(o.data); bm.verts.ensure_lookup_table()
    for f in bm.faces: f.select_set(False)
    for e in bm.edges: e.select_set(False)
    for v in bm.verts: v.select_set(False)
    bm.verts[vi].select_set(True)
    bmesh.update_edit_mesh(o.data,loop_triangles=False,destructive=False)
    if selected(o)!=[vi]: raise RuntimeError(f'SELECTION_BEFORE_SAVE_MISMATCH:{selected(o)}!=[{vi}]')
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    bm2=bmesh.from_edit_mesh(o.data); bm2.verts.ensure_lookup_table()
    after_sel=sorted(v.index for v in bm2.verts if v.select)
    if after_sel!=[vi]: raise RuntimeError(f'SELECTION_AFTER_SAVE_MISMATCH:{after_sel}!=[{vi}]')
    after={v.index:tuple(v.co) for v in bm2.verts}
    if any(after[i]!=co for i,co in before.items()): raise RuntimeError('GEOMETRY_CHANGED_DURING_SELECTION_PREP')
    res={'format':FORMAT,'status':'PASS','verify_only':False,'object_index':oi,'vertex_index':vi,'selected_vertex_indices':after_sel,'saved_mode_raw':str(o.mode),'saved_mode':str(bpy.context.mode),'visible_selection_persisted':True,'geometry_positions_unchanged':True,'selection_only_change':True,'popup_used':False,'bmesh_lookup_table_ensured':True}
    rp=pathlib.Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(res,indent=2)+'\n',encoding='utf-8')
    print('PT_MULTIBONE_EXTENT_MANUAL_SELECTION=PASS')
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
