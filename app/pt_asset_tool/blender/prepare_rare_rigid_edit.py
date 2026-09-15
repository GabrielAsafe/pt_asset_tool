from __future__ import annotations
import argparse, hashlib, json, pathlib, struct, sys
import bpy


def parse_args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True); p.add_argument('--report',required=True); p.add_argument('--logical',required=True); return p.parse_args(argv)

def qf(x): return int(round(float(x)*1000000000.0))
def f3(co): return [int(round(float(co[i])*256.0)) for i in range(3)]

def h_update(h, value):
    if isinstance(value,str): b=value.encode('utf-8','surrogatepass')
    elif isinstance(value,int): b=struct.pack('<q',value)
    else: b=repr(value).encode('ascii','replace')
    h.update(struct.pack('<I',len(b))); h.update(b)

def mesh_state_fingerprint(obj):
    """Fingerprint everything the V0.8.9 artist writer does NOT authorize, excluding positions and object transforms."""
    me=obj.data; h=hashlib.sha256()
    h_update(h,obj.name); h_update(h,len(me.vertices)); h_update(h,len(me.polygons)); h_update(h,len(me.loops))
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
    return {
        'location_q9':[qf(q) for q in obj.location],
        'rotation_euler_q9':[qf(q) for q in obj.rotation_euler],
        'scale_q9':[qf(q) for q in obj.scale],
    }

def main(argv):
    a=parse_args(argv); rares=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE']
    rares.sort(key=lambda o:int(o.get('pt_source_object_index',-1)))
    if not rares: raise RuntimeError('no rare meshes')
    rows=[]
    for o in rares:
        oi=int(o.get('pt_source_object_index',-1))
        if oi<0: raise RuntimeError('rare object missing source index')
        rows.append({
            'object_index':oi,
            'object_name':o.name,
            'vertex_count':len(o.data.vertices),
            'mesh_state_fingerprint':mesh_state_fingerprint(o),
            'transform_state':transform_state(o),
            'positions_fixed':[f3(v.co) for v in o.data.vertices],
        })
        o.hide_select=False
    for o in bpy.data.objects:
        if str(o.get('pt_rare_role',''))=='ROOT' or o.type=='ARMATURE': o.hide_select=True
    sc=bpy.context.scene
    sc['pt_rare_edit_logical']=a.logical
    sc['pt_rare_edit_scope']='ONE_TO_FOUR_VERTEX_MULTIBONE_INTERIOR_TRANSACTION'
    sc['pt_rare_edit_write_authorized']=False
    sc['pt_rare_edit_workspace_version']='0.8.9'
    out=pathlib.Path(a.out).resolve(); out.parent.mkdir(parents=True,exist_ok=True); bpy.ops.wm.save_as_mainfile(filepath=str(out))
    result={'check':'PASS','logical':a.logical,'rare_objects':len(rows),'rows':rows,'blend':str(out),'client_modified':False}
    rp=pathlib.Path(a.report).resolve(); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"PT_RARE_EDIT_BASELINE=PASS rare_objects={len(rows)} blend={out}")
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
