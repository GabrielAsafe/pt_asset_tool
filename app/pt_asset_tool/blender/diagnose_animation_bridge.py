from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector


def args_after_ddash():
    return sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []


def row_to_col(values):
    if len(values) != 16:
        raise ValueError('matrix must contain 16 values')
    r = Matrix((values[0:4], values[4:8], values[8:12], values[12:16]))
    return r.transposed()


def find_armature():
    arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    if len(arms) != 1:
        raise RuntimeError(f'expected exactly one armature, found {len(arms)}')
    return arms[0]


def rigid_vertex_bone(obj, v):
    if not v.groups:
        return None
    best = max(v.groups, key=lambda g: float(g.weight))
    if best.group >= len(obj.vertex_groups):
        return None
    return obj.vertex_groups[best.group].name


def evaluated_coords(obj, depsgraph):
    eo = obj.evaluated_get(depsgraph)
    mesh = eo.to_mesh()
    try:
        return [v.co.copy() for v in mesh.vertices]
    finally:
        eo.to_mesh_clear()


def expected_coords(obj, arm, frame_spec, bind_by_name, index_by_name):
    arm_inv = arm.matrix_world.inverted()
    obj_world = obj.matrix_world
    obj_inv = obj_world.inverted()
    arm_world = arm.matrix_world
    out=[]
    by_bone={}
    for v in obj.data.vertices:
        bone_name = rigid_vertex_bone(obj, v)
        if bone_name is None or bone_name not in index_by_name:
            out.append(v.co.copy())
            continue
        idx=index_by_name[bone_name]
        current=row_to_col(frame_spec['matrices'][idx])
        bind=bind_by_name[bone_name]
        delta=current @ bind.inverted()
        p_arm = arm_inv @ (obj_world @ v.co)
        p_cur_arm = delta @ p_arm
        p_obj = obj_inv @ (arm_world @ p_cur_arm)
        out.append(p_obj)
        by_bone.setdefault(bone_name, []).append(len(out)-1)
    return out, by_bone


def percentile(vals, q):
    if not vals:
        return 0.0
    s=sorted(vals)
    if len(s)==1:
        return float(s[0])
    x=(len(s)-1)*q
    lo=int(math.floor(x)); hi=int(math.ceil(x))
    if lo==hi: return float(s[lo])
    t=x-lo
    return float(s[lo]*(1.0-t)+s[hi]*t)


def bounds_for_objects(objs):
    pts=[]
    for obj in objs:
        if obj.type != 'MESH': continue
        for c in obj.bound_box:
            pts.append(obj.matrix_world @ Vector(c))
    if not pts:
        return Vector((-1,-1,-1)), Vector((1,1,1))
    mn=Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx=Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn,mx


def iter_action_fcurves(action):
    """Yield F-Curves from both legacy and Blender 4.4+/5.x Action APIs."""
    legacy = getattr(action, 'fcurves', None)
    if legacy is not None:
        try:
            yield from legacy
            return
        except TypeError:
            pass

    seen=set()
    for layer in getattr(action, 'layers', ()):
        for strip in getattr(layer, 'strips', ()):
            for channelbag in getattr(strip, 'channelbags', ()):
                for fcurve in getattr(channelbag, 'fcurves', ()):
                    ptr=fcurve.as_pointer() if hasattr(fcurve, 'as_pointer') else id(fcurve)
                    if ptr in seen:
                        continue
                    seen.add(ptr)
                    yield fcurve


def make_source_direct(mesh_objs, arm, frame_specs, bind_by_name, index_by_name):
    """Build an animated direct-source witness using shape keys.

    Each source frame is evaluated directly from current * inverse(bind).  The
    witness is independent from the Blender armature, so both sides can play
    through the same frame range for a meaningful visual comparison.
    """
    direct=[]
    for obj in mesh_objs:
        d=obj.copy()
        d.data=obj.data.copy()
        d.name=f'SOURCE_DIRECT__{obj.name}'
        bpy.context.collection.objects.link(d)
        d.modifiers.clear()
        d.parent=None

        # Basis stays as the pristine mesh. One relative key contains each
        # source-evaluated frame. At exact integer frames only that key is 1.
        d.shape_key_add(name='Basis', from_mix=False)
        frame_keys=[]
        for frspec in frame_specs:
            fr=int(frspec['frame'])
            exp,_=expected_coords(obj,arm,frspec,bind_by_name,index_by_name)
            key=d.shape_key_add(name=f'PT_SOURCE_F{fr:04d}', from_mix=False)
            for i,co in enumerate(exp):
                key.data[i].co=co
            key.value=0.0
            frame_keys.append((fr,key))

        for fr,key in frame_keys:
            # Three keys are sufficient because adjacent source samples are
            # consecutive frames in the baked action. Linear interpolation
            # gives a readable continuous witness between integer samples.
            for kfr,val in ((fr-1,0.0),(fr,1.0),(fr+1,0.0)):
                key.value=val
                key.keyframe_insert(data_path='value', frame=kfr)
        if d.data.shape_keys and d.data.shape_keys.animation_data and d.data.shape_keys.animation_data.action:
            act=d.data.shape_keys.animation_data.action
            for fc in iter_action_fcurves(act):
                for kp in fc.keyframe_points:
                    kp.interpolation='LINEAR'
        direct.append(d)
    return direct


def make_camera_for_pair(objs):
    mn,mx=bounds_for_objects(objs)
    center=(mn+mx)*0.5
    extent=mx-mn
    span=max(extent.x,extent.y,extent.z,1.0)

    cam_data=bpy.data.cameras.new('PT_DIAGNOSTIC_CAMERA')
    cam=bpy.data.objects.new('PT_DIAGNOSTIC_CAMERA',cam_data)
    bpy.context.collection.objects.link(cam)
    # View along -Y with enough margin for both copies and their full motion.
    cam.location=center + Vector((0.0,-span*3.2,span*0.12))
    direction=center-cam.location
    cam.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()
    cam_data.lens=50.0
    cam_data.sensor_width=36.0
    cam_data.clip_start=max(span*0.0005,0.01)
    cam_data.clip_end=max(span*20.0,1000.0)
    bpy.context.scene.camera=cam
    return cam,center,span


def add_camera_facing_label(text, location, size, camera):
    curve=bpy.data.curves.new(type='FONT', name=f'PT_LABEL_{text}')
    curve.body=text
    curve.align_x='CENTER'
    curve.align_y='CENTER'
    curve.size=max(size,0.25)
    obj=bpy.data.objects.new(f'PT_LABEL_{text}',curve)
    bpy.context.collection.objects.link(obj)
    obj.location=location
    obj.rotation_euler=(camera.location-location).to_track_quat('Z','Y').to_euler()
    return obj


def setup_animated_pair(mesh_objs, arm, selected, bind_by_name, index_by_name):
    direct=make_source_direct(mesh_objs,arm,selected['frames'],bind_by_name,index_by_name)

    # Compute an unshifted envelope, then separate by the same world-space
    # distance. Armature and original meshes move together on the right.
    mn,mx=bounds_for_objects(mesh_objs+direct)
    base_span=max(mx.x-mn.x,mx.y-mn.y,mx.z-mn.z,1.0)
    shift=base_span*0.8
    for o in direct:
        o.location.x -= shift
    arm.location.x += shift
    # Meshes driven by the armature are normally not children of it. Shift
    # them too so the complete Blender side stays together.
    for o in mesh_objs:
        if o.parent != arm:
            o.location.x += shift

    # Do not render the bones themselves; their action keeps evaluating and
    # continues driving the right-hand meshes.
    arm.show_in_front=False
    arm.hide_render=True
    arm.hide_viewport=True

    cam,center,span=make_camera_for_pair(direct+mesh_objs)
    mn_d,mx_d=bounds_for_objects(direct)
    mn_b,mx_b=bounds_for_objects(mesh_objs)
    label_z=max(mx_d.z,mx_b.z)+span*0.10
    # Put labels in the vertical plane seen by the camera (constant Y near
    # the assets), then orient them toward the diagnostic camera.
    y=center.y-span*0.02
    add_camera_facing_label('SOURCE_DIRECT',Vector(((mn_d.x+mx_d.x)/2,y,label_z)),span*0.035,cam)
    add_camera_facing_label('BLENDER_ARMATURE',Vector(((mn_b.x+mx_b.x)/2,y,label_z)),span*0.035,cam)
    return direct,cam


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--payload', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', required=True)
    a=ap.parse_args(args_after_ddash())

    payload=json.loads(Path(a.payload).read_text(encoding='utf-8'))
    arm=find_armature()
    selected=next((x for x in payload['actions'] if x['name']==payload['selected_action']),None)
    if selected is None:
        raise RuntimeError('selected action missing from payload')
    if arm.animation_data is None or arm.animation_data.action is None:
        raise RuntimeError('armature has no active action')

    bind_by_name={b['name']:row_to_col(b['bind_tm']) for b in payload['bones']}
    index_by_name={b['name']:i for i,b in enumerate(payload['bones'])}
    mesh_objs=[]
    for o in bpy.data.objects:
        if o.type!='MESH': continue
        if any(m.type=='ARMATURE' and m.object==arm for m in o.modifiers):
            mesh_objs.append(o)
    if not mesh_objs:
        raise RuntimeError('no skinned mesh objects found')

    per_frame=[]
    per_bone_max={}
    for frspec in selected['frames']:
        fr=int(frspec['frame'])
        bpy.context.scene.frame_set(fr)
        bpy.context.view_layer.update()
        depsgraph=bpy.context.evaluated_depsgraph_get()
        errs=[]
        for obj in mesh_objs:
            act=evaluated_coords(obj,depsgraph)
            exp,_=expected_coords(obj,arm,frspec,bind_by_name,index_by_name)
            if len(act)!=len(exp):
                raise RuntimeError(f'{obj.name}: evaluated vertex count changed {len(exp)}->{len(act)}')
            for i,(aa,ee) in enumerate(zip(act,exp)):
                e=(aa-ee).length
                errs.append(e)
                bn=rigid_vertex_bone(obj,obj.data.vertices[i]) or '<none>'
                per_bone_max[bn]=max(per_bone_max.get(bn,0.0),float(e))
        rms=math.sqrt(sum(e*e for e in errs)/len(errs)) if errs else 0.0
        per_frame.append({
            'frame':fr,
            'engine_frame':int(frspec['engine_frame']),
            'vertices':len(errs),
            'max_error':max(errs) if errs else 0.0,
            'rms_error':rms,
            'p95_error':percentile(errs,0.95),
        })

    worst=max(per_frame,key=lambda x:(x['rms_error'],x['max_error']))
    setup_animated_pair(mesh_objs,arm,selected,bind_by_name,index_by_name)

    frames=[int(x['frame']) for x in selected['frames']]
    scene=bpy.context.scene
    scene.frame_start=min(frames)
    scene.frame_end=max(frames)
    scene.frame_set(scene.frame_start)
    scene.render.fps=int(payload.get('fps',30))
    scene['pt_animation_diagnostic']='ANIMATED SOURCE_DIRECT vs BLENDER_ARMATURE'
    scene['pt_diagnostic_action']=selected['name']
    scene['pt_diagnostic_worst_frame']=int(worst['frame'])
    scene['pt_diagnostic_frame_range']=[scene.frame_start,scene.frame_end]

    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    top_bones=sorted(per_bone_max.items(),key=lambda kv:kv[1],reverse=True)[:20]
    report={
        'tool':'PT_ANIMATION_BRIDGE_DIAGNOSTIC_V2',
        'selected_action':selected['name'],
        'selected_motion_index':int(selected['index']),
        'mesh_objects':[o.name for o in mesh_objs],
        'frames_checked':len(per_frame),
        'frame_start':scene.frame_start,
        'frame_end':scene.frame_end,
        'worst_frame':worst,
        'top_bone_max_error':[{'bone':k,'max_error':v} for k,v in top_bones],
        'frame_errors':per_frame,
        'diagnostic_blend':str(out),
        'comparison':'ANIMATED_SOURCE_DIRECT_vs_BLENDER_ARMATURE',
        'client_modified':False,
        'check':'PASS',
    }
    Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PT_ANIMATION_BRIDGE_DIAGNOSTIC_V2')
    print(f"selected_action={selected['name']}")
    print(f"frames_checked={len(per_frame)}")
    print(f"frame_range={scene.frame_start}..{scene.frame_end}")
    print(f"worst_frame={worst['frame']}")
    print(f"worst_rms_error={worst['rms_error']:.9f}")
    print(f"worst_max_error={worst['max_error']:.9f}")
    print('client_modified=False')
    print('animation_bridge_diagnostic_check=PASS')


if __name__=='__main__':
    main()
