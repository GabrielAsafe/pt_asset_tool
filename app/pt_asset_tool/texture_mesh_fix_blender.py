"""Blender-only, topology-preserving mesh lighting fix candidate (never exports SMD).

Usage: blender --background --disable-autoexec --python THIS_FILE -- --input source.blend
       --output staged.blend --mode recalc-normals|smooth-shading

Verify geometry/UV/material invariants before writing a separate .blend.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def inventory(bpy):
    result={}
    for obj in bpy.data.objects:
        if obj.type!='MESH': continue
        mesh=obj.data
        result[obj.name]={'vertices':len(mesh.vertices),'edges':len(mesh.edges),
                          'polygons':len(mesh.polygons),'uv_layers':len(mesh.uv_layers),
                          'materials':len(mesh.materials),
                          'vertex_positions':hashlib.sha256(b''.join(bytes(str(tuple(v.co)), 'ascii') for v in mesh.vertices)).hexdigest(),
                          'uv_values':hashlib.sha256(b''.join(bytes(str(tuple(loop.uv)), 'ascii') for layer in mesh.uv_layers for loop in layer.data)).hexdigest()}
    return result


def stage(input_file: Path, output_file: Path, mode: str) -> dict:
    import bpy
    import bmesh
    input_file=input_file.expanduser().resolve();output_file=output_file.expanduser().resolve()
    if not input_file.is_file() or input_file.suffix.lower()!='.blend' or output_file.suffix.lower()!='.blend':
        raise ValueError('BLEND_INPUT_AND_OUTPUT_REQUIRED')
    if output_file==input_file or input_file in output_file.parents or output_file.exists():
        raise ValueError('OUTPUT_MUST_BE_NEW_AND_SEPARATE')
    if mode not in ('recalc-normals','smooth-shading'):
        raise ValueError('INVALID_LIGHTING_FIX_MODE')
    bpy.ops.wm.open_mainfile(filepath=str(input_file),load_ui=False)
    before=inventory(bpy)
    if not before:
        raise ValueError('NO_MESHES_IN_WORKSPACE')
    faces_touched=0
    for obj in bpy.data.objects:
        if obj.type!='MESH': continue
        mesh=obj.data
        if mode=='recalc-normals':
            bm=bmesh.new()
            try:
                bm.from_mesh(mesh)
                bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
                faces_touched+=len(bm.faces)
                bm.to_mesh(mesh)
            finally:
                bm.free()
        else:
            for face in mesh.polygons:
                face.use_smooth=True
                faces_touched+=1
        mesh.update()
    after=inventory(bpy)
    if before!=after:
        raise RuntimeError('MESH_GEOMETRY_OR_UV_INVARIANTS_CHANGED')
    output_file.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_file),compress=True)
    witness={'format':'PT_MESH_LIGHTING_WORKSPACE_CANDIDATE_V1',
             'mode':mode,'source':str(input_file),'source_sha256':hashlib.sha256(input_file.read_bytes()).hexdigest(),
             'output':str(output_file),'output_sha256':hashlib.sha256(output_file.read_bytes()).hexdigest(),
             'faces_visited':faces_touched,'geometry_and_uv_byte_semantics_preserved':True,
             'topology_changed':False,'client_modified':False,'smd_exported':False,
             'in_game_shader_mesh_certified':False,'requires_artistic_inspection':True,
             'notes':'Candidate .blend for normal orientation or face shading only. Use existing PT asset tool certified import/export/deploy workflow after manual in-engine validation.'}
    (output_file.with_suffix('.meshfix.json')).write_text(json.dumps(witness,indent=2)+'\n',encoding='utf-8')
    return witness


def main():
    args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--mode',choices=('recalc-normals','smooth-shading'),required=True)
    a=parser.parse_args(args)
    print(json.dumps(stage(a.input,a.output,a.mode),indent=2))

if __name__=='__main__':
    main()
