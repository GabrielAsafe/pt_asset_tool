from __future__ import annotations
import argparse,json,pathlib,sys
import bpy

def args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--plan',required=True); p.add_argument('--report',required=True); return p.parse_args(argv)
def fixed(co): return [int(round(float(co[i])*256.0)) for i in range(3)]
def main(argv):
    a=args(argv); plan=json.loads(pathlib.Path(a.plan).read_text(encoding='utf-8')); oi=int(plan['object_index']); changes=list(plan.get('changed_vertices') or [])
    objs=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE' and int(o.get('pt_source_object_index',-1))==oi]
    if len(objs)!=1: raise RuntimeError(f'rare object index {oi} unresolved: {len(objs)}')
    obj=objs[0]; rows=[]; maxerr=0; ok=True
    for ch in changes:
        vi=int(ch['vertex_index']); actual=fixed(obj.data.vertices[vi].co); expected=list(ch['expected_reimport_world_fixed']); err=max(abs(actual[i]-expected[i]) for i in range(3)); maxerr=max(maxerr,err); good=actual==expected; ok=ok and good
        rows.append({'vertex_index':vi,'expected_world_fixed':expected,'actual_world_fixed':actual,'max_error_fixed':err,'check':'PASS' if good else 'FAIL'})
    result={'check':'PASS' if ok else 'FAIL','object_index':oi,'changed_vertex_count':len(changes),'rows':rows,'max_error_fixed':maxerr,'client_modified':False}
    rp=pathlib.Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f"PT_RARE_RIGID_TRANSACTION_REIMPORT={result['check']} object={oi} changed_vertices={len(changes)} max_error_fixed={maxerr}")
    if not ok: raise RuntimeError(result)
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
