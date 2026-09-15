from __future__ import annotations
import argparse, json, sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

# Blender is launched against files in pt_build.  Make the app root explicit so
# this helper does not depend on the caller's current working directory.
APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from pt_asset_tool.affine_factor import svd_affine_split

AFFINE_SPLIT_THRESHOLD = 1e-6
AFFINE_CONTROL_PREFIX = "PT_AFF_"
AFFINE_SECOND_TRS_THRESHOLD = 2e-5
AFFINE_REPRESENTATION = "SVD_BLENDER_RESIDUAL_TWO_BONE_TRS_V2"


def args_after_ddash():
    return sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []


def row_to_col(values):
    if len(values)!=16: raise ValueError("matrix must contain 16 values")
    r=Matrix((values[0:4],values[4:8],values[8:12],values[12:16]))
    return r.transposed()


def _max_abs(a, b):
    return max(abs(float(a[r][c])-float(b[r][c])) for r in range(4) for c in range(4))


def _trs_reconstruction_error(matrix):
    loc, rot, scale = matrix.decompose()
    return _max_abs(matrix, Matrix.LocRotScale(loc, rot, scale))


def find_armature():
    arms=[o for o in bpy.data.objects if o.type=='ARMATURE']
    if len(arms)!=1: raise RuntimeError(f"expected exactly one armature, found {len(arms)}")
    return arms[0]


def ensure_pose_mode(arm):
    bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object and bpy.context.object.mode!='OBJECT' else None
    bpy.context.view_layer.objects.active=arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='POSE')


def _desired_pose(arm, payload, bind, fr):
    desired={}
    for idx in payload['tm_sort']:
        bmeta=payload['bones'][idx]
        name=bmeta['name']
        current=row_to_col(fr['matrices'][idx])
        delta=current @ bind[name].inverted()
        desired[name]=delta @ arm.data.bones[name].matrix_local
    return desired


def _expected_basis(arm, desired_pose, name):
    pb=arm.pose.bones[name]
    bone=arm.data.bones[name]
    parent_pb=pb.parent
    target=desired_pose[name]
    if hasattr(bone,'convert_local_to_pose'):
        if parent_pb is None:
            return bone.convert_local_to_pose(target,bone.matrix_local,invert=True)
        parent_bone=arm.data.bones[parent_pb.name]
        return bone.convert_local_to_pose(
            target,bone.matrix_local,
            parent_matrix=desired_pose[parent_pb.name],
            parent_matrix_local=parent_bone.matrix_local,
            invert=True,
        )
    if parent_pb is None:
        return bone.matrix_local.inverted() @ target
    parent_bone=arm.data.bones[parent_pb.name]
    rest_local=parent_bone.matrix_local.inverted() @ bone.matrix_local
    pose_local=desired_pose[parent_pb.name].inverted() @ target
    return rest_local.inverted() @ pose_local


def _precompute_source_bases(arm, payload, bind):
    """Cache source local bases before inserting any affine helper bones."""
    cache={}
    max_nontrs={b['name']:0.0 for b in payload['bones']}
    for spec in payload['actions']:
        by_frame={}
        for fr in spec['frames']:
            desired=_desired_pose(arm,payload,bind,fr)
            bases={}
            for idx in payload['tm_sort']:
                name=payload['bones'][idx]['name']
                basis=_expected_basis(arm,desired,name)
                bases[name]=basis.copy()
                err=_trs_reconstruction_error(basis)
                if err>max_nontrs[name]: max_nontrs[name]=err
            by_frame[int(fr['frame'])]=bases
        cache[spec['name']]=by_frame
    split={name for name,err in max_nontrs.items() if err>AFFINE_SPLIT_THRESHOLD}
    return cache,max_nontrs,split


def _copy_inheritance(src, dst):
    for attr in ('inherit_scale','use_inherit_rotation','use_local_location','use_relative_parent'):
        if hasattr(src,attr) and hasattr(dst,attr):
            try: setattr(dst,attr,getattr(src,attr))
            except Exception: pass


def _set_helper_inheritance(bone):
    if hasattr(bone,'inherit_scale'):
        try: bone.inherit_scale='FULL'
        except Exception: pass
    for attr,val in (('use_inherit_rotation',True),('use_local_location',True),('use_relative_parent',False)):
        if hasattr(bone,attr):
            try: setattr(bone,attr,val)
            except Exception: pass


def _install_affine_controls(arm, payload, split_names, max_nontrs):
    """Insert one coincident non-deform control before each non-TRS source bone.

    The original source bone keeps its name and vertex groups.  The control has
    the same rest transform and inherits from the original parent; the source
    bone becomes its non-connected child with identity rest relation.  Therefore
    two ordinary TRS bases multiply into the exact legacy affine basis while the
    original deform bone still presents the expected global pose to the mesh.
    """
    if not split_names:
        arm['pt_affine_control_map']=json.dumps({},sort_keys=True)
        arm['pt_affine_split_mode']='NONE'
        return {}
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active=arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    ebones=arm.data.edit_bones
    mapping={}
    for idx,bmeta in enumerate(payload['bones']):
        name=bmeta['name']
        if name not in split_names:
            continue
        eb=ebones.get(name)
        if eb is None: raise RuntimeError(f"affine split source bone missing: {name}")
        ctrl_name=f"{AFFINE_CONTROL_PREFIX}{idx:04d}"
        if ebones.get(ctrl_name) is not None:
            raise RuntimeError(f"affine control name collision: {ctrl_name}")
        old_parent=eb.parent
        ctrl=ebones.new(ctrl_name)
        ctrl.head=eb.head.copy(); ctrl.tail=eb.tail.copy(); ctrl.roll=eb.roll
        # The helper must keep all 3 location DOFs.  A connected pose bone
        # constrains translation to its parent's tail, which breaks the first
        # affine factor whenever the source basis has a non-zero translation.
        # Keep the same rest transform/parent, but never mark the helper as
        # connected.  The original deform bone is also made non-connected
        # below; its rest relation to the coincident helper remains identity.
        ctrl.use_connect=False
        ctrl.use_deform=False
        _copy_inheritance(eb,ctrl)
        ctrl.parent=old_parent
        eb.parent=ctrl
        eb.use_connect=False
        _set_helper_inheritance(eb)
        mapping[name]=ctrl_name
    bpy.ops.object.mode_set(mode='OBJECT')
    # Persist the mapping/diagnostic on normal Bone/Object ID properties so it
    # survives save/reopen and the checker can explain the representation.
    for source,ctrl_name in mapping.items():
        src=arm.data.bones[source]
        ctrl=arm.data.bones[ctrl_name]
        ctrl.use_deform=False
        ctrl['pt_affine_role']='NONDEFORM_FIRST_FACTOR'
        ctrl['pt_source_bone']=source
        src['pt_affine_control']=ctrl_name
        src['pt_source_max_basis_trs_error']=float(max_nontrs[source])
    arm['pt_affine_control_map']=json.dumps(mapping,sort_keys=True)
    arm['pt_affine_split_mode']=AFFINE_REPRESENTATION
    ensure_pose_mode(arm)
    return mapping


def _matrix3_rows(m):
    return [[float(m[r][c]) for c in range(3)] for r in range(3)]


def _factor_basis(basis):
    factor=svd_affine_split(_matrix3_rows(basis))
    u=Matrix(tuple(tuple(x for x in row) for row in factor['first_rotation']))
    vt=Matrix(tuple(tuple(x for x in row) for row in factor['second_rotation']))
    q1=u.to_quaternion(); q1.normalize()
    q2=vt.to_quaternion(); q2.normalize()
    s1=Vector(tuple(float(x) for x in factor['first_scale']))
    loc=basis.to_translation().copy()
    first=Matrix.LocRotScale(loc,q1,s1)
    second=Matrix.LocRotScale(Vector((0.0,0.0,0.0)),q2,Vector((1.0,1.0,1.0)))
    reconstructed=first @ second
    residual=_max_abs(basis,reconstructed)
    if residual>2e-5:
        raise RuntimeError(f"Blender affine split residual too large: {residual}")
    return {
        'first_matrix':first,'second_matrix':second,'location':loc,
        'first_quaternion':q1,'first_scale':s1,'second_quaternion':q2,
        'rank':int(factor.get('rank',3)),'zero_singular_axis_count':int(factor.get('zero_singular_axis_count',0)),
        'residual':float(residual),
    }


def _derive_blender_residual_basis(arm, source_name, ctrl_name, target_pose, represented_pose, first_basis):
    """Solve the second TRS basis using Blender's hierarchy conversion.

    ``first_basis @ second_basis`` is not a sufficient contract for pose bones:
    Blender applies rest matrices and inheritance options when converting a
    bone's local channels into pose space.  The first factor remains a normal
    SVD/TRS basis on the non-deform helper, but the residual for the deform bone
    is solved by Blender itself against the authoritative target pose.

    This is deliberately limited to full-rank first factors.  Inverting a
    singular parent transform is not a certified Blender operation; a physical
    rank-deficient non-TRS source therefore fails closed instead of receiving an
    approximate pose.
    """
    ctrl_pb = arm.pose.bones[ctrl_name]
    ctrl_bone = arm.data.bones[ctrl_name]
    source_bone = arm.data.bones[source_name]
    parent_pb = ctrl_pb.parent
    if parent_pb is None:
        helper_pose = ctrl_bone.convert_local_to_pose(first_basis, ctrl_bone.matrix_local, invert=False)
    else:
        parent_bone = arm.data.bones[parent_pb.name]
        # PT_RC6_11_REPRESENTED_PARENT_CHAIN: solve against the pose the parent
        # can actually represent after its TRS decomposition, not the ideal
        # mathematical source pose.  This prevents small parent residuals from
        # accumulating down affine-split chains.
        parent_target = represented_pose[parent_pb.name]
        helper_pose = ctrl_bone.convert_local_to_pose(
            first_basis,
            ctrl_bone.matrix_local,
            parent_matrix=parent_target,
            parent_matrix_local=parent_bone.matrix_local,
            invert=False,
        )
    second_basis = source_bone.convert_local_to_pose(
        target_pose,
        source_bone.matrix_local,
        parent_matrix=helper_pose,
        parent_matrix_local=ctrl_bone.matrix_local,
        invert=True,
    )
    trs_error = _trs_reconstruction_error(second_basis)
    if trs_error > AFFINE_SECOND_TRS_THRESHOLD:
        raise RuntimeError(
            f"Blender affine residual is not TRS for {source_name}: "
            f"error={trs_error} threshold={AFFINE_SECOND_TRS_THRESHOLD}"
        )
    loc, rot, scale = second_basis.decompose()
    rot.normalize()
    rebuilt = Matrix.LocRotScale(loc, rot, scale)
    represented = source_bone.convert_local_to_pose(
        rebuilt,
        source_bone.matrix_local,
        parent_matrix=helper_pose,
        parent_matrix_local=ctrl_bone.matrix_local,
        invert=False,
    )
    return {
        'basis': second_basis,
        'location': loc.copy(),
        'quaternion': rot.copy(),
        'scale': scale.copy(),
        'trs_error': float(_max_abs(second_basis, rebuilt)),
        'helper_pose': helper_pose.copy(),
        'represented_pose': represented.copy(),
    }


def _represented_pose_from_trs_basis(arm, name, basis, represented_pose):
    """Convert one already-TRS basis through the represented parent chain."""
    bone=arm.data.bones[name]
    pb=arm.pose.bones[name]
    parent_pb=pb.parent
    if parent_pb is None:
        return bone.convert_local_to_pose(basis,bone.matrix_local,invert=False)
    parent_bone=arm.data.bones[parent_pb.name]
    return bone.convert_local_to_pose(
        basis,bone.matrix_local,
        parent_matrix=represented_pose[parent_pb.name],
        parent_matrix_local=parent_bone.matrix_local,
        invert=False,
    )


def _apply_trs(pb, location, quaternion, scale):
    pb.location=location
    pb.rotation_mode='QUATERNION'
    pb.rotation_quaternion=quaternion
    pb.scale=scale


def _key_pose_bone(pb,scene_frame,previous_quat):
    q=pb.rotation_quaternion.copy()
    prev=previous_quat.get(pb.name)
    if prev is not None and q.dot(prev)<0.0:
        q.negate(); pb.rotation_quaternion=q
    previous_quat[pb.name]=q.copy()
    pb.keyframe_insert(data_path='location',frame=scene_frame,group=pb.name)
    pb.keyframe_insert(data_path='rotation_quaternion',frame=scene_frame,group=pb.name)
    pb.keyframe_insert(data_path='scale',frame=scene_frame,group=pb.name)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--payload',required=True); ap.add_argument('--out',required=True); ap.add_argument('--report',required=True)
    a=ap.parse_args(args_after_ddash())
    payload=json.loads(Path(a.payload).read_text(encoding='utf-8'))
    arm=find_armature(); ensure_pose_mode(arm)
    bind={b['name']:row_to_col(b['bind_tm']) for b in payload['bones']}
    missing=[n for n in bind if n not in arm.pose.bones]
    if missing: raise RuntimeError(f"armature missing source bones: {missing[:20]}")

    # Diagnose and cache bases while the armature still has the source hierarchy.
    basis_cache,max_nontrs,split_names=_precompute_source_bases(arm,payload,bind)
    control_map=_install_affine_controls(arm,payload,split_names,max_nontrs)
    for pb in arm.pose.bones: pb.rotation_mode='QUATERNION'

    created=[]; global_split_residual=0.0; affine_second_trs_max_error=0.0; affine_rank_counts={}; live_pose_max_error=0.0; live_pose_mismatch_sample=[]
    for spec in payload['actions']:
        old=bpy.data.actions.get(spec['name'])
        if old is not None: bpy.data.actions.remove(old)
        action=bpy.data.actions.new(spec['name']); action.use_fake_user=True
        arm.animation_data_create(); arm.animation_data.action=action
        if hasattr(action,'slots'):
            slot=action.slots.new(id_type='OBJECT',name=arm.name); arm.animation_data.action_slot=slot
        previous_quat={}
        for fr in spec['frames']:
            scene_frame=int(fr['frame']); bpy.context.scene.frame_set(scene_frame)
            bases=basis_cache[spec['name']][scene_frame]
            desired=_desired_pose(arm,payload,bind,fr)
            represented_pose={}
            keyed=[]
            for idx in payload['tm_sort']:
                name=payload['bones'][idx]['name']; basis=bases[name]
                ctrl_name=control_map.get(name)
                if ctrl_name:
                    fac=_factor_basis(basis)
                    global_split_residual=max(global_split_residual,fac['residual'])
                    affine_rank_counts[str(fac['rank'])]=affine_rank_counts.get(str(fac['rank']),0)+1
                    if fac['rank'] < 3:
                        raise RuntimeError(
                            f"rank-deficient non-TRS affine basis is not Blender-certified: "
                            f"bone={name} action={spec['name']} frame={scene_frame} rank={fac['rank']}"
                        )
                    residual=_derive_blender_residual_basis(
                        arm,name,ctrl_name,desired[name],represented_pose,fac['first_matrix']
                    )
                    affine_second_trs_max_error=max(affine_second_trs_max_error,residual['trs_error'])
                    _apply_trs(arm.pose.bones[ctrl_name],fac['location'],fac['first_quaternion'],fac['first_scale'])
                    _apply_trs(arm.pose.bones[name],residual['location'],residual['quaternion'],residual['scale'])
                    represented_pose[name]=residual['represented_pose']
                    keyed.extend((ctrl_name,name))
                else:
                    loc,rot,scale=basis.decompose(); rot.normalize()
                    rebuilt_basis=Matrix.LocRotScale(loc,rot,scale)
                    _apply_trs(arm.pose.bones[name],loc,rot,scale)
                    represented_pose[name]=_represented_pose_from_trs_basis(arm,name,rebuilt_basis,represented_pose)
                    keyed.append(name)
            bpy.context.view_layer.update()
            # Validate the live rig before keying.  This does not replace the
            # save/reopen checker; it distinguishes hierarchy/rest-reparenting
            # mistakes from Action persistence/evaluation mistakes.
            desired_live=desired
            for idx in payload['tm_sort']:
                source_name=payload['bones'][idx]['name']
                err=_max_abs(arm.pose.bones[source_name].matrix,desired_live[source_name])
                live_pose_max_error=max(live_pose_max_error,err)
                if err>2e-4 and len(live_pose_mismatch_sample)<20:
                    live_pose_mismatch_sample.append({
                        'action':spec['name'],'frame':scene_frame,'bone':source_name,
                        'max_abs_error':float(err),'affine_split_active':source_name in control_map,
                    })
            for name in keyed:
                _key_pose_bone(arm.pose.bones[name],scene_frame,previous_quat)

        if hasattr(action,'layers') and hasattr(action,'slots') and len(action.slots):
            slot=action.slots[0]
            for layer in action.layers:
                for strip in layer.strips:
                    if hasattr(strip,'channelbag'):
                        bag=strip.channelbag(slot,ensure=False)
                        if bag is not None:
                            for fcu in bag.fcurves:
                                for kp in fcu.keyframe_points: kp.interpolation='LINEAR'
        elif hasattr(action,'fcurves'):
            for fcu in action.fcurves:
                for kp in fcu.keyframe_points: kp.interpolation='LINEAR'
        action['pt_motion_index']=int(spec['index']); action['pt_state_name']=spec['state_name']; action['pt_repeat']=int(spec['repeat'])
        action['pt_affine_split_mode']=AFFINE_REPRESENTATION if control_map else 'NONE'
        action.use_frame_range=True; action.frame_start=1; action.frame_end=max(1,int(spec['frame_count']))
        if hasattr(action,'use_cyclic'): action.use_cyclic=bool(spec['repeat'])
        action['pt_engine_start']=int(spec['engine_start']); action['pt_engine_end']=int(spec['engine_end'])
        created.append({'name':action.name,'frames':int(spec['frame_count']),'state':spec['state_name'],'index':int(spec['index'])})

    selected=bpy.data.actions.get(payload['selected_action'])
    if selected is None: raise RuntimeError(f"selected action missing: {payload['selected_action']}")
    arm.animation_data.action=selected
    if hasattr(selected,'slots') and len(selected.slots): arm.animation_data.action_slot=selected.slots[0]
    sel=next(x for x in payload['actions'] if x['name']==payload['selected_action'])
    bpy.context.scene.frame_start=1; bpy.context.scene.frame_end=max(1,int(sel['frame_count'])); bpy.context.scene.frame_set(1)
    bpy.context.scene.render.fps=int(payload.get('fps',30))
    arm['pt_animation_source_inx']=payload['inx']; arm['pt_animation_source_smb']=payload['smb']; arm['pt_selected_action']=payload['selected_action']
    bpy.ops.object.mode_set(mode='OBJECT')
    Path(a.out).parent.mkdir(parents=True,exist_ok=True); bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.out)))
    live_ok = not live_pose_mismatch_sample
    report={
        'tool':'PT_BLENDER_BAKE_ACTIONS_V2','armature':arm.name,'actions':created,'selected_action':selected.name,
        'scene_frame_start':bpy.context.scene.frame_start,'scene_frame_end':bpy.context.scene.frame_end,'fps':bpy.context.scene.render.fps,
        'quaternion_null_semantics':payload.get('quaternion_null_semantics','UNKNOWN'),'quaternion_sign_continuity':True,'interpolation':'LINEAR',
        'affine_representation':AFFINE_REPRESENTATION if control_map else 'DIRECT_TRS',
        'affine_split_bone_count':len(control_map),'affine_split_bones':sorted(control_map),'affine_control_map':control_map,
        'max_source_basis_trs_error':max(max_nontrs.values()) if max_nontrs else 0.0,
        'max_affine_factor_reconstruction_error':global_split_residual,
        'max_affine_second_basis_trs_error':affine_second_trs_max_error,
        'affine_split_rank_counts':dict(sorted(affine_rank_counts.items())),
        'live_source_pose_max_error':float(live_pose_max_error),
        'live_source_pose_mismatch_sample':live_pose_mismatch_sample,
        'live_source_pose_check':'PASS' if live_ok else 'FAIL',
        'client_modified':False,'check':'PASS' if live_ok else 'FAIL'
    }
    Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not live_ok:
        raise RuntimeError(f"live source pose check failed before Action persistence: {live_pose_mismatch_sample[:8]}")
    print('PT_BLENDER_BAKE_ACTIONS_V2'); print(f"actions={len(created)}"); print(f"selected_action={selected.name}")
    print(f"affine_split_bones={len(control_map)}"); print('client_modified=False'); print('animation_bake_check=PASS')

if __name__=='__main__': main()
