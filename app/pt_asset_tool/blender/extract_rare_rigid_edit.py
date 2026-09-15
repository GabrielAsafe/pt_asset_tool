from __future__ import annotations
import argparse, hashlib, json, pathlib, struct, sys
import bpy

UV_TOL = 2e-6
WEIGHT_TOL = 1e-6

def parse_args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--baseline',required=True); p.add_argument('--report',required=True); p.add_argument('--allow-no-change',action='store_true'); p.add_argument('--max-changed',type=int,default=4); return p.parse_args(argv)
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
def transform_state(obj): return {'location_q9':[qf(q) for q in obj.location],'rotation_euler_q9':[qf(q) for q in obj.rotation_euler],'scale_q9':[qf(q) for q in obj.scale]}
def semantic_state(obj):
    me=obj.data; group_names={int(g.index):g.name for g in obj.vertex_groups}
    return {'object_name':obj.name,'vertex_count':len(me.vertices),'edge_count':len(me.edges),'polygon_count':len(me.polygons),'loop_count':len(me.loops),'edges':[[int(x) for x in e.vertices] for e in me.edges],'polygons':[{'vertices':[int(x) for x in p.vertices],'material_index':int(p.material_index)} for p in me.polygons],'uv_layers':[{'name':uv.name,'values':[[float(d.uv[0]),float(d.uv[1])] for d in uv.data]} for uv in me.uv_layers],'material_slots':[s.material.name if s.material else '' for s in obj.material_slots],'vertex_groups':[g.name for g in obj.vertex_groups],'weights':[[[group_names.get(int(ref.group),''),float(ref.weight)] for ref in sorted(v.groups,key=lambda r:int(r.group))] for v in me.vertices]}
def force_object_mode():
    before=str(getattr(bpy.context,'mode','UNKNOWN')); changed=False
    if before!='OBJECT':
        if bpy.context.object is None: raise RuntimeError(f'cannot canonicalize Blender mode {before}: no active object')
        bpy.ops.object.mode_set(mode='OBJECT'); changed=True
    bpy.context.view_layer.update(); after=str(getattr(bpy.context,'mode','UNKNOWN'))
    if after!='OBJECT': raise RuntimeError(f'Blender mode canonicalization failed: {before}->{after}')
    return before,after,changed

def compare_semantic(base,cur,oi):
    errs=[]; diag=[]
    for k in ('object_name','vertex_count','edge_count','polygon_count','loop_count','edges','polygons','material_slots','vertex_groups'):
        if base.get(k)!=cur.get(k): errs.append(f'{k.upper()}_{oi}'); diag.append({'object_index':oi,'kind':k,'before':base.get(k) if k not in ('edges','polygons') else '<stored>','after':cur.get(k) if k not in ('edges','polygons') else '<current>'})
    bu=base.get('uv_layers') or []; cu=cur.get('uv_layers') or []
    uv_max=0.0; uv_struct=False
    if len(bu)!=len(cu): uv_struct=True
    else:
        for a,b in zip(bu,cu):
            if a.get('name')!=b.get('name') or len(a.get('values') or [])!=len(b.get('values') or []): uv_struct=True; break
            for av,bv in zip(a.get('values') or [],b.get('values') or []):
                if len(av)!=2 or len(bv)!=2: uv_struct=True; break
                uv_max=max(uv_max,abs(float(av[0])-float(bv[0])),abs(float(av[1])-float(bv[1])))
            if uv_struct: break
    if uv_struct or uv_max>UV_TOL:
        errs.append(f'UV_STATE_CHANGED_{oi}'); diag.append({'object_index':oi,'kind':'UV_STATE','max_abs_delta':uv_max,'tolerance':UV_TOL,'structural':uv_struct})
    bw=base.get('weights') or []; cw=cur.get('weights') or []
    weight_max=0.0; weight_struct=False
    if len(bw)!=len(cw): weight_struct=True
    else:
        for a,b in zip(bw,cw):
            if len(a)!=len(b): weight_struct=True; break
            for ar,br in zip(a,b):
                if len(ar)!=2 or len(br)!=2 or ar[0]!=br[0]: weight_struct=True; break
                weight_max=max(weight_max,abs(float(ar[1])-float(br[1])))
            if weight_struct: break
    if weight_struct or weight_max>WEIGHT_TOL:
        errs.append(f'PHYSIQUE_WEIGHT_STATE_CHANGED_{oi}'); diag.append({'object_index':oi,'kind':'PHYSIQUE_WEIGHT_STATE','max_abs_delta':weight_max,'tolerance':WEIGHT_TOL,'structural':weight_struct})
    return errs,diag,uv_max,weight_max

def main(argv):
    a=parse_args(argv); base=json.loads(pathlib.Path(a.baseline).read_text(encoding='utf-8')); errors=[]; changed=[]; diagnostics=[]
    mode_before,mode_after,mode_changed=force_object_mode()
    bmap={int(r['object_index']):r for r in base.get('rows') or []}; rares=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE']; omap={int(o.get('pt_source_object_index',-1)):o for o in rares}
    if set(omap)!=set(bmap): errors.append('RARE_OBJECT_SET_CHANGED')
    volatile=[]; max_uv=0.0; max_weight=0.0
    for oi,br in sorted(bmap.items()):
        o=omap.get(oi)
        if o is None: continue
        if len(o.data.vertices)!=int(br['vertex_count']): errors.append(f'VERTEX_COUNT_{oi}'); continue
        current_transform=transform_state(o)
        if current_transform!=br.get('transform_state'):
            errors.append(f'OBJECT_TRANSFORM_CHANGED_{oi}'); diagnostics.append({'object_index':oi,'kind':'OBJECT_TRANSFORM','before':br.get('transform_state'),'after':current_transform})
        current_fp=mesh_state_fingerprint(o); baseline_fp=br.get('mesh_state_fingerprint') or br.get('fingerprint')
        cur_sem=semantic_state(o); base_sem=br.get('semantic_state')
        if base_sem is None:
            errors.append(f'BASELINE_SEMANTIC_STATE_MISSING_{oi}')
        else:
            se,sd,uv_delta,w_delta=compare_semantic(base_sem,cur_sem,oi); errors.extend(se); diagnostics.extend(sd); max_uv=max(max_uv,uv_delta); max_weight=max(max_weight,w_delta)
        if current_fp!=baseline_fp:
            volatile.append(oi); diagnostics.append({'object_index':oi,'kind':'MONOLITHIC_FINGERPRINT_MISMATCH_DIAGNOSTIC_ONLY','baseline_fingerprint':baseline_fp,'current_fingerprint':current_fp})
        before=br['positions_fixed']
        for vi,v in enumerate(o.data.vertices):
            after=f3(v.co)
            if after!=before[vi]: changed.append({'object_index':oi,'object_name':o.name,'vertex_index':vi,'before_world_fixed':before[vi],'after_world_fixed':after})
    if len(changed)==0 and not a.allow_no_change: errors.append('NO_VERTEX_POSITION_CHANGE')
    changed_objects=sorted({int(r['object_index']) for r in changed})
    if len(changed)>int(a.max_changed):
        errors.append(f'TOO_MANY_VERTEX_POSITION_CHANGES_{len(changed)}'); diagnostics.append({'kind':'TOO_MANY_VERTEX_POSITIONS','count':len(changed),'max_changed':int(a.max_changed),'hint':'V0.8.9 authorizes at most four vertices in one atomic transaction.'})
    if len(changed_objects)>1:
        errors.append('MULTI_OBJECT_VERTEX_TRANSACTION_DEFERRED'); diagnostics.append({'kind':'MULTI_OBJECT_VERTEX_TRANSACTION','object_indices':changed_objects,'hint':'V0.8.9 transaction scope is one rare mesh object per write.'})
    semantic_errors=[x for x in errors if any(x.startswith(p) for p in ('OBJECT_NAME_','VERTEX_COUNT_','EDGE_COUNT_','POLYGON_COUNT_','LOOP_COUNT_','EDGES_','POLYGONS_','MATERIAL_SLOTS_','VERTEX_GROUPS_','UV_STATE_CHANGED_','PHYSIQUE_WEIGHT_STATE_CHANGED_','BASELINE_SEMANTIC_STATE_MISSING_'))]
    result={'check':'PASS' if not errors else 'FAIL','errors':errors,'changed_vertex_count':len(changed),'changed_vertices':changed,'changed_object_indices':changed_objects,'transaction_single_object':len(changed_objects)<=1,'max_changed_authorized':int(a.max_changed),'diagnostics':diagnostics,'guard_scope':'ONE_TO_FOUR_VERTEX_POSITIONS_SINGLE_OBJECT_TRANSACTION','allow_no_change':bool(a.allow_no_change),'writer_input_mode_before':mode_before,'writer_input_mode_after':mode_after,'writer_input_object_mode_canonicalized':mode_changed,'non_position_semantic_state_pass':len(semantic_errors)==0,'volatile_fingerprint_mismatch_objects':volatile,'max_uv_state_delta':max_uv,'uv_state_tolerance':UV_TOL,'max_physique_weight_delta':max_weight,'physique_weight_tolerance':WEIGHT_TOL,'selection_state_ignored':True,'client_modified':False}
    rp=pathlib.Path(a.report).resolve(); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"PT_RARE_EDIT_EXTRACT={result['check']} changed_vertices={len(changed)} changed_objects={len(changed_objects)} max_changed={int(a.max_changed)} mode_before={mode_before} object_mode_canonicalized={str(mode_changed).lower()} semantic_state={str(result['non_position_semantic_state_pass']).lower()} volatile_fp={len(volatile)} transform_errors={sum(1 for x in errors if x.startswith('OBJECT_TRANSFORM_CHANGED_'))} semantic_errors={len(semantic_errors)}")
    if errors: raise RuntimeError(','.join(errors))
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
