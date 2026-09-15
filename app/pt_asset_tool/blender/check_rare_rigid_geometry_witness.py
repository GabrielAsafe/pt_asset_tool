from __future__ import annotations
import argparse, json, pathlib, sys
import bpy

def args(argv):
    p=argparse.ArgumentParser(); p.add_argument('--plan',required=True); p.add_argument('--report',required=True); return p.parse_args(argv)
def fixed(co): return [int(round(float(co[i])*256.0)) for i in range(3)]
def main(argv):
    a=args(argv); plan=json.loads(pathlib.Path(a.plan).read_text(encoding='utf-8')); oi=int(plan['object_index']); vi=int(plan['vertex_index'])
    objs=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('pt_rare_role',''))=='RARE' and int(o.get('pt_source_object_index',-1))==oi]
    if len(objs)!=1: raise RuntimeError(f'rare object index {oi} unresolved: {len(objs)}')
    obj=objs[0]; actual=fixed(obj.data.vertices[vi].co); expected=list(plan['expected_reimport_world_fixed']); err=max(abs(actual[i]-expected[i]) for i in range(3))
    result={'check':'PASS' if actual==expected else 'FAIL','object_index':oi,'vertex_index':vi,'expected_world_fixed':expected,'actual_world_fixed':actual,'max_error_fixed':err,'client_modified':False}
    rp=pathlib.Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f"PT_RARE_RIGID_REIMPORT_WITNESS={result['check']} object={oi} vertex={vi} error_fixed={err}")
    if result['check']!='PASS': raise RuntimeError(result)
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
