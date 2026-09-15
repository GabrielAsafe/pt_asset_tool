from __future__ import annotations
import argparse,json,pathlib,sys
import bpy,bmesh

def args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--plan',required=True); p.add_argument('--report',required=True); return p.parse_args(argv)
def fixed(co): return [int(round(float(co[i])*256.0)) for i in range(3)]
def main(argv):
    a=args(argv); plan=json.loads(pathlib.Path(a.plan).read_text(encoding='utf-8')); oi=int(plan['object_index']); changes=list(plan.get('changed_vertices') or [])
    if len(changes)<2: raise RuntimeError('transaction witness requires >=2 changed vertices')
    try:
        if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    except Exception: pass
    objs=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE' and int(o.get('pt_source_object_index',-1))==oi]
    if len(objs)!=1: raise RuntimeError(f'rare object unresolved {oi}: {len(objs)}')
    o=objs[0]
    for x in bpy.context.selected_objects: x.select_set(False)
    o.hide_set(False); o.select_set(True); bpy.context.view_layer.objects.active=o
    for v in o.data.vertices: v.select=False
    for e in o.data.edges: e.select=False
    for p in o.data.polygons: p.select=False
    for ch in changes:
        vi=int(ch['vertex_index']); o.data.vertices[vi].select=True
    o.data.update(); bpy.ops.object.mode_set(mode='EDIT')
    bm=bmesh.from_edit_mesh(o.data); bm.verts.ensure_lookup_table()
    before=[]; after=[]
    for ch in changes:
        vi=int(ch['vertex_index']); v=bm.verts[vi]; b=fixed(v.co); expected_before=list(ch['before_world_fixed'])
        if b!=expected_before: raise RuntimeError(f'before mismatch v{vi}: {b} != {expected_before}')
        target=list(ch['requested_after_world_fixed']); v.co=[x/256.0 for x in target]; actual=fixed(v.co)
        if actual!=target: raise RuntimeError(f'fixed quantization mismatch v{vi}: {actual} != {target}')
        before.append({'vertex_index':vi,'world_fixed':b}); after.append({'vertex_index':vi,'world_fixed':actual})
    bmesh.update_edit_mesh(o.data,loop_triangles=False,destructive=False)
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    saved_mode=str(getattr(bpy.context,'mode','UNKNOWN'))
    result={'check':'PASS','object_index':oi,'changed_vertex_count':len(changes),'before':before,'after':after,'blend':bpy.data.filepath,'artist_path':'EDIT_MESH_MULTI_VERTEX_TRANSACTION_SAVED_WITH_EDIT_MODE_ACTIVE','saved_mode':saved_mode,'client_modified':False}
    rp=pathlib.Path(a.report).resolve(); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f"PT_RARE_ARTIST_TRANSACTION=PASS changed_vertices={len(changes)} mode={saved_mode} path=EDIT_MESH")
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
