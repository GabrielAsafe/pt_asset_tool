from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import bpy
import bmesh

FORMAT = "PT_STATIC_SEMANTIC_AUTOMATED_EDIT_V1"


def _argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _bbox(obj):
    pts=[obj.matrix_world @ v.co for v in obj.data.vertices]
    if not pts: return [[0.0,0.0,0.0],[0.0,0.0,0.0]]
    return [[min(p.x for p in pts),min(p.y for p in pts),min(p.z for p in pts)],[max(p.x for p in pts),max(p.y for p in pts),max(p.z for p in pts)]]


def _deform(obj, amplitude: float, seed: int):
    for vi,v in enumerate(obj.data.vertices):
        phase=(vi+1)*(seed+5)
        v.co.x += amplitude*math.sin(phase*0.61)
        v.co.y += amplitude*0.7*math.cos(phase*0.47)
        v.co.z += amplitude*0.5*math.sin(phase*0.31+0.2)
    obj.data.update()


def _subdivide_one_edge(obj):
    mesh=obj.data
    before=(len(mesh.vertices),len(mesh.polygons))
    bm=bmesh.new(); bm.from_mesh(mesh)
    bm.edges.ensure_lookup_table()
    edge=next((e for e in bm.edges if e.link_faces), None)
    if edge is None:
        bm.free(); raise RuntimeError(f"no subdividable edge: {obj.name}")
    bmesh.ops.subdivide_edges(bm, edges=[edge], cuts=1, use_grid_fill=False)
    bm.to_mesh(mesh); bm.free(); mesh.update()
    after=(len(mesh.vertices),len(mesh.polygons))
    if after == before:
        raise RuntimeError(f"topology edit did not change counts: {obj.name}")
    return before,after


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--plan',required=True); ap.add_argument('--out',required=True); ap.add_argument('--report',required=True)
    ns=ap.parse_args(_argv())
    plan=json.loads(pathlib.Path(ns.plan).read_text(encoding='utf-8'))
    objects=[str(x) for x in plan.get('objects') or []]
    modes=dict(plan.get('edit_modes') or {})
    amplitude=float(plan.get('amplitude') or 0.08)
    if not objects: raise RuntimeError('static semantic devtest has no targets')
    rows=[]; missing=[]
    for oi,name in enumerate(objects):
        obj=bpy.data.objects.get(name)
        if obj is None or obj.type!='MESH': missing.append(name); continue
        before_counts=[len(obj.data.vertices),len(obj.data.polygons)]
        before_bbox=_bbox(obj)
        mode=str(modes.get(name) or 'DEFORM').upper()
        if mode=='TOPOLOGY':
            _subdivide_one_edge(obj)
            # Also deform so the writer cannot pass on topology bookkeeping alone.
            _deform(obj, amplitude*0.35, oi)
        elif mode=='DEFORM':
            _deform(obj, amplitude, oi)
        else:
            raise RuntimeError(f'unknown static devtest edit mode: {mode}')
        after_counts=[len(obj.data.vertices),len(obj.data.polygons)]
        after_bbox=_bbox(obj)
        rows.append({'object':name,'mode':mode,'counts_before':before_counts,'counts_after':after_counts,'bbox_before':before_bbox,'bbox_after':after_bbox,'topology_changed':before_counts!=after_counts,'bbox_changed':before_bbox!=after_bbox})
    if missing: raise RuntimeError(f'static semantic devtest missing objects: {missing}')
    if any(not r['bbox_changed'] for r in rows): raise RuntimeError('one or more static targets did not receive a geometric edit')
    out=pathlib.Path(ns.out).resolve(); out.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out),check_existing=False)
    report={'format':FORMAT,'status':'PASS','target_count':len(rows),'targets':rows,'topology_edit_count':sum(1 for r in rows if r['topology_changed']),'materials_intentionally_changed':False,'client_modified':False}
    rp=pathlib.Path(ns.report).resolve(); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0

if __name__=='__main__': raise SystemExit(main())
