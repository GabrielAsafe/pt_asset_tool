from __future__ import annotations
import argparse, json, pathlib, sys
import bpy, bmesh

FORMAT='PT_RARE_RIGID_CROSS_OBJECT_MANUAL_SELECTION_V1'

def args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--plan',required=True); p.add_argument('--report',required=True); p.add_argument('--verify-only',action='store_true'); return p.parse_args(argv)

def rare(oi:int):
    rows=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE' and int(o.get('pt_source_object_index',-1))==oi]
    if len(rows)!=1: raise RuntimeError(f'RARE_OBJECT_UNRESOLVED_{oi}:{len(rows)}')
    return rows[0]

def selected_map(objs):
    out={}
    for oi,o in objs:
        bm=bmesh.from_edit_mesh(o.data)
        out[str(oi)]=sorted(v.index for v in bm.verts if v.select)
    return out

def main(argv):
    a=args(argv); plan=json.loads(pathlib.Path(a.plan).read_text(encoding='utf-8'))
    per=list(plan.get('per_object_plans') or [])
    if len(per)!=2: raise RuntimeError(f'MANUAL_OBJECT_COUNT_NOT_2:{len(per)}')
    wanted={int(p['object_index']):sorted(int(v) for v in p['changed_vertex_indices']) for p in per}
    if any(len(v)!=2 for v in wanted.values()): raise RuntimeError(f'MANUAL_VERTICES_PER_OBJECT_NOT_2:{wanted}')
    if a.verify_only:
        in_mode=sorted(int(o.get('pt_source_object_index',-1)) for o in getattr(bpy.context,'objects_in_mode',[]) if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE')
        if str(getattr(bpy.context,'mode','UNKNOWN'))!='EDIT_MESH' or in_mode!=sorted(wanted): raise RuntimeError(f'REOPEN_MODE_OBJECTS_MISMATCH:{getattr(bpy.context,"mode","UNKNOWN")}:{in_mode}!={sorted(wanted)}')
        objs=[(oi,rare(oi)) for oi in sorted(wanted)]
        actual=selected_map(objs); expected={str(k):v for k,v in sorted(wanted.items())}
        if actual!=expected: raise RuntimeError(f'REOPEN_SELECTION_MISMATCH:{actual}!={expected}')
        res={'format':FORMAT,'status':'PASS','verify_only':True,'object_indices':sorted(wanted),'selected_vertices_by_object':actual,'objects_in_mode':in_mode,'saved_mode_raw':str(bpy.context.object.mode),'saved_mode':str(bpy.context.mode),'visible_selection_persisted':True,'popup_used':False}
        rp=pathlib.Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(res,indent=2)+'\n',encoding='utf-8')
        print('PT_CROSS_OBJECT_MANUAL_SELECTION_VERIFY=PASS')
        return
    if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    for o in bpy.data.objects:
        if o.type!='MESH': continue
        o.select_set(False)
        for v in o.data.vertices: v.select=False
        for e in o.data.edges: e.select=False
        for f in o.data.polygons: f.select=False
        o.data.update()
    objs=[]
    for oi in sorted(wanted):
        o=rare(oi); o.hide_set(False); o.select_set(True)
        o.lock_location=(True,True,True); o.lock_rotation=(True,True,True); o.lock_scale=(True,True,True)
        objs.append((oi,o))
    bpy.context.view_layer.objects.active=objs[0][1]
    bpy.context.tool_settings.mesh_select_mode=(True,False,False)
    bpy.ops.object.mode_set(mode='EDIT')
    if str(getattr(bpy.context,'mode','UNKNOWN'))!='EDIT_MESH': raise RuntimeError('MULTI_OBJECT_EDIT_MODE_NOT_ENTERED')
    in_mode=sorted(int(o.get('pt_source_object_index',-1)) for o in bpy.context.objects_in_mode if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE')
    if in_mode!=sorted(wanted): raise RuntimeError(f'OBJECTS_IN_MODE_MISMATCH:{in_mode}!={sorted(wanted)}')
    for oi,o in objs:
        bm=bmesh.from_edit_mesh(o.data)
        # Blender 5.2 may expose an outdated BMElemSeq index table immediately
        # after entering multi-object Edit Mode.  Iteration is valid, but direct
        # bm.verts[index] access is not until the lookup table is rebuilt.
        bm.verts.ensure_lookup_table()
        for f in bm.faces: f.select_set(False)
        for e in bm.edges: e.select_set(False)
        for v in bm.verts: v.select_set(False)
        for vi in wanted[oi]:
            if vi<0 or vi>=len(bm.verts): raise RuntimeError(f'VERTEX_RANGE_{oi}_{vi}')
            bm.verts[vi].select_set(True)
        bmesh.update_edit_mesh(o.data,loop_triangles=False,destructive=False)
    before=selected_map(objs)
    expected={str(k):v for k,v in sorted(wanted.items())}
    if before!=expected: raise RuntimeError(f'SELECTION_BEFORE_SAVE_MISMATCH:{before}!={expected}')
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    after=selected_map(objs)
    if after!=expected: raise RuntimeError(f'SELECTION_AFTER_SAVE_MISMATCH:{after}!={expected}')
    res={'format':FORMAT,'status':'PASS','object_indices':sorted(wanted),'selected_vertices_by_object':after,'objects_in_mode':in_mode,'saved_mode_raw':str(bpy.context.object.mode),'saved_mode':str(bpy.context.mode),'selection_only_change':True,'popup_used':False}
    rp=pathlib.Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(res,indent=2)+'\n',encoding='utf-8')
    print('PT_CROSS_OBJECT_MANUAL_SELECTION=PASS objects='+','.join(map(str,sorted(wanted))))
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
