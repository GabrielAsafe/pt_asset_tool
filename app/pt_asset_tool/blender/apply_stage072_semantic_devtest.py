from __future__ import annotations

import argparse
import json
import pathlib
import sys

import bpy


def _args():
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True)
    p.add_argument('--report',required=True)
    return p.parse_args(argv)


def main():
    a=_args()
    meshes=[o for o in bpy.data.objects if o.type=='MESH' and o.get('pt_stage072_source_sha256')]
    if len(meshes)!=1:
        raise RuntimeError(f'expected one Stage0.72 mesh, got {len(meshes)}')
    obj=meshes[0]; mesh=obj.data
    if len(mesh.vertices)<3:
        raise RuntimeError('Stage0.72 automated devtest needs at least three vertices')
    indices=[]
    for i in (0,len(mesh.vertices)//2,len(mesh.vertices)-1):
        if i not in indices: indices.append(i)
    deltas=[(32,0,0),(0,-24,0),(0,0,16)]
    rows=[]
    for k,vi in enumerate(indices):
        v=mesh.vertices[vi]
        before=[float(v.co[j]) for j in range(3)]
        raw=[int(round(before[j]*256.0)) for j in range(3)]
        d=deltas[k % len(deltas)]
        after_raw=[raw[j]+int(d[j]) for j in range(3)]
        after=[x/256.0 for x in after_raw]
        v.co=after
        rows.append({'vertex_index':vi,'before_world':before,'after_world':after,'delta_raw':list(d)})
    mesh.update()
    out=pathlib.Path(a.out).expanduser().resolve(); report=pathlib.Path(a.report).expanduser().resolve()
    out.parent.mkdir(parents=True,exist_ok=True); report.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    payload={'format':'PT_STAGE072_SEMANTIC_AUTOMATED_EDIT_V1','status':'PASS','edit_count':len(rows),'edits':rows,'blend':str(out),'client_modified':False}
    report.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
