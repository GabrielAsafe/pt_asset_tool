from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import bpy


def args_after_ddash():
    return sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--part', required=True, help='animated/pristine head .blend to append')
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', required=True)
    ap.add_argument('--prefix', default='PT_HEAD__')
    a=ap.parse_args(args_after_ddash())

    base_arms=[o for o in bpy.data.objects if o.type=='ARMATURE']
    if len(base_arms)!=1:
        raise RuntimeError(f'expected exactly one base armature, found {len(base_arms)}')
    base_arm=base_arms[0]
    part_path=str(Path(a.part).resolve())
    with bpy.data.libraries.load(part_path, link=False) as (src, dst):
        # Import only scene objects. Object dependencies (mesh, armature data,
        # materials, images and Actions referenced by animation_data) are pulled
        # in by Blender automatically.
        dst.objects=list(src.objects)
    imported=[]
    for obj in dst.objects:
        if obj is None:
            continue
        bpy.context.scene.collection.objects.link(obj)
        imported.append(obj)
    if not imported:
        raise RuntimeError('head blend contained no importable objects')
    head_arms=[o for o in imported if o.type=='ARMATURE']
    head_meshes=[o for o in imported if o.type=='MESH']
    if len(head_arms)!=1:
        raise RuntimeError(f'expected exactly one head armature, found {len(head_arms)}')
    if not head_meshes:
        raise RuntimeError('head blend contained no mesh objects')

    # Keep both armatures. The client loads body and head as distinct animated
    # models; preserving two overlapping rigs mirrors that independence while
    # allowing a single scene to prove alignment and motion coherence.
    for obj in imported:
        if not obj.name.startswith(a.prefix):
            obj.name=a.prefix+obj.name
    head_arm=head_arms[0]
    head_arm['pt_player_part']='HEAD'
    base_arm['pt_player_part']='BODY'
    bpy.context.scene['pt_player_assembly']='BODY_PLUS_INDEPENDENT_HEAD'
    bpy.context.scene['pt_head_source_blend']=part_path

    out=Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    report={
        'tool':'PT_ASSEMBLE_PLAYER_PARTS_V1',
        'base_armature':base_arm.name,
        'head_armature':head_arm.name,
        'head_mesh_count':len(head_meshes),
        'imported_object_count':len(imported),
        'assembly_mode':'BODY_PLUS_INDEPENDENT_HEAD',
        'head_source_blend':part_path,
        'client_modified':False,
        'check':'PASS',
    }
    Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PT_ASSEMBLE_PLAYER_PARTS_V1')
    print(f'head_meshes={len(head_meshes)}')
    print('assembly_mode=BODY_PLUS_INDEPENDENT_HEAD')
    print('client_modified=False')
    print('player_assembly_check=PASS')


if __name__=='__main__':
    main()
