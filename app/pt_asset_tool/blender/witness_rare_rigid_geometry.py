from __future__ import annotations
import argparse, json, pathlib, sys
import bpy


def args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--plan',required=True); p.add_argument('--out',required=True); p.add_argument('--report',required=True); return p.parse_args(argv)

def fixed(co): return [int(round(float(co[i])*256.0)) for i in range(3)]

def main(argv):
    a=args(argv); plan=json.loads(pathlib.Path(a.plan).read_text(encoding='utf-8'))
    oi=int(plan['object_index']); vi=int(plan['vertex_index'])
    objs=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE' and int(o.get('pt_source_object_index',-1))==oi]
    if len(objs)!=1: raise RuntimeError(f'rare object index {oi} unresolved: {len(objs)}')
    obj=objs[0]
    if not 0<=vi<len(obj.data.vertices): raise RuntimeError('vertex OOB')
    v=obj.data.vertices[vi]; before=fixed(v.co)
    if before != list(plan['before_world_fixed']): raise RuntimeError(f'before mismatch {before} != {plan["before_world_fixed"]}')
    after=list(plan['requested_after_world_fixed']); v.co=[x/256.0 for x in after]; obj.data.update(); actual=fixed(v.co)
    if actual != after: raise RuntimeError(f'Blender quantized witness mismatch {actual} != {after}')
    out=pathlib.Path(a.out).resolve(); out.parent.mkdir(parents=True,exist_ok=True); bpy.ops.wm.save_as_mainfile(filepath=str(out))
    result={'check':'PASS','object_index':oi,'object_name':obj.name,'vertex_index':vi,'before_world_fixed':before,'after_world_fixed':actual,'blend':str(out),'client_modified':False}
    rp=pathlib.Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f"PT_RARE_RIGID_WITNESS=PASS object={oi} vertex={vi} after={actual}")

if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
