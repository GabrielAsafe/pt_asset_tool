from __future__ import annotations
import argparse, hashlib, json, pathlib, struct, sys
import bpy

UV_TOL = 2e-6
WEIGHT_TOL = 1e-6

def parse_args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--report',required=True); p.add_argument('--logical',required=True); return p.parse_args(argv)
def qf(x): return int(round(float(x)*1000000000.0))
def f3(co): return [int(round(float(co[i])*256.0)) for i in range(3)]
def h_update(h,value):
    if isinstance(value,str): b=value.encode('utf-8','surrogatepass')
    elif isinstance(value,int): b=struct.pack('<q',value)
    else: b=repr(value).encode('ascii','replace')
    h.update(struct.pack('<I',len(b))); h.update(b)
def mesh_state_fingerprint(obj):
    me=obj.data; h=hashlib.sha256(); h_update(h,obj.name); h_update(h,len(me.vertices)); h_update(h,len(me.polygons)); h_update(h,len(me.loops))
    for p in me.polygons:
        h_update(h,len(p.vertices))
        for v in p.vertices: h_update(h,int(v))
        h_update(h,int(p.material_index))
    h_update(h,len(me.uv_layers))
    for uv in me.uv_layers:
        h_update(h,uv.name); h_update(h,len(uv.data))
        for d in uv.data: h_update(h,qf(d.uv[0])); h_update(h,qf(d.uv[1]))
    h_update(h,len(obj.material_slots))
    for s in obj.material_slots: h_update(h,s.material.name if s.material else '')
    h_update(h,len(obj.vertex_groups))
    for vg in obj.vertex_groups: h_update(h,vg.index); h_update(h,vg.name)
    for v in me.vertices:
        rows=[]
        for g in v.groups: rows.append((int(g.group),qf(g.weight)))
        for gi,w in sorted(rows): h_update(h,gi); h_update(h,w)
    return h.hexdigest()
def transform_state(obj):
    return {'location_q9':[qf(q) for q in obj.location], 'rotation_euler_q9':[qf(q) for q in obj.rotation_euler], 'scale_q9':[qf(q) for q in obj.scale]}
def semantic_state(obj):
    me=obj.data
    group_names={int(g.index):g.name for g in obj.vertex_groups}
    return {
        'object_name':obj.name,
        'vertex_count':len(me.vertices), 'edge_count':len(me.edges), 'polygon_count':len(me.polygons), 'loop_count':len(me.loops),
        'edges':[[int(x) for x in e.vertices] for e in me.edges],
        'polygons':[{'vertices':[int(x) for x in p.vertices], 'material_index':int(p.material_index)} for p in me.polygons],
        'uv_layers':[{'name':uv.name, 'values':[[float(d.uv[0]),float(d.uv[1])] for d in uv.data]} for uv in me.uv_layers],
        'material_slots':[s.material.name if s.material else '' for s in obj.material_slots],
        'vertex_groups':[g.name for g in obj.vertex_groups],
        'weights':[[[group_names.get(int(ref.group),''),float(ref.weight)] for ref in sorted(v.groups,key=lambda r:int(r.group))] for v in me.vertices],
    }
def force_object_mode():
    before=str(getattr(bpy.context,'mode','UNKNOWN')); changed=False
    if before != 'OBJECT':
        if bpy.context.object is None: raise RuntimeError(f'cannot canonicalize Blender mode {before}: no active object')
        bpy.ops.object.mode_set(mode='OBJECT'); changed=True
    bpy.context.view_layer.update()
    after=str(getattr(bpy.context,'mode','UNKNOWN'))
    if after != 'OBJECT': raise RuntimeError(f'Blender mode canonicalization failed: {before}->{after}')
    return before, after, changed

def main(argv):
    a=parse_args(argv); mode_before,mode_after,mode_changed=force_object_mode()
    rares=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE']
    rares.sort(key=lambda o:int(o.get('pt_source_object_index',-1)))
    if not rares: raise RuntimeError('no rare meshes')
    rows=[]
    for o in rares:
        oi=int(o.get('pt_source_object_index',-1))
        if oi<0: raise RuntimeError('rare object missing source index')
        rows.append({'object_index':oi,'object_name':o.name,'vertex_count':len(o.data.vertices),'mesh_state_fingerprint':mesh_state_fingerprint(o),'semantic_state':semantic_state(o),'transform_state':transform_state(o),'positions_fixed':[f3(v.co) for v in o.data.vertices]})
    result={'check':'PASS','logical':a.logical,'rare_objects':len(rows),'rows':rows,'baseline_source':'PERSISTED_BLEND_REOPENED_OBJECT_MODE','mode_before':mode_before,'mode_after':mode_after,'object_mode_canonicalized':mode_changed,'semantic_policy':{'uv_tolerance':UV_TOL,'weight_tolerance':WEIGHT_TOL,'selection_state':'ignored UI-only state','authority':'component semantic comparison; monolithic hash is diagnostic only'},'client_modified':False}
    rp=pathlib.Path(a.report).resolve(); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"PT_RARE_EDIT_BASELINE_CAPTURE=PASS rare_objects={len(rows)} source=PERSISTED_BLEND_REOPENED_OBJECT_MODE mode_before={mode_before} canonicalized={str(mode_changed).lower()}")
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
