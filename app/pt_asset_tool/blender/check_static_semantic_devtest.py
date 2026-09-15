from __future__ import annotations
import argparse,json,math,pathlib,sys
import bpy
FORMAT='PT_STATIC_SEMANTIC_AUTOMATED_REIMPORT_CHECK_V1'

def _argv(): return sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--expected',required=True); ap.add_argument('--report',required=True); ns=ap.parse_args(_argv())
    expected=json.loads(pathlib.Path(ns.expected).read_text(encoding='utf-8')); errors=[]; rows=[]
    for name,contract in dict(expected.get('objects') or {}).items():
        obj=bpy.data.objects.get(name)
        if obj is None or obj.type!='MESH': errors.append(f'MISSING_MESH:{name}'); continue
        got=[len(obj.data.vertices),len(obj.data.polygons)]; exp=[int(contract['vertices']),int(contract['faces'])]
        if got!=exp: errors.append(f'COUNT_MISMATCH:{name}:{got}!={exp}')
        nonfinite=sum(1 for v in obj.data.vertices if not all(math.isfinite(float(x)) for x in v.co))
        if nonfinite: errors.append(f'NONFINITE_VERTEX:{name}:{nonfinite}')
        rows.append({'object':name,'vertices':got[0],'faces':got[1],'material_slots':len(obj.material_slots),'nonfinite_vertices':nonfinite})
    report={'format':FORMAT,'status':'PASS' if not errors else 'FAIL','expected_object_count':len(expected.get('objects') or {}),'checked_object_count':len(rows),'objects':rows,'errors':errors}
    rp=pathlib.Path(ns.report).resolve(); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if errors: raise RuntimeError('; '.join(errors))
if __name__=='__main__': main()
