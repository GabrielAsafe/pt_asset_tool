from __future__ import annotations

import argparse
import json
import pathlib
import sys

import bpy


def _parse(argv):
    p = argparse.ArgumentParser()
    p.add_argument('--plan', required=True)
    p.add_argument('--report', required=True)
    return p.parse_args(argv)


def _fixed(co):
    return [int(round(float(co[i]) * 256.0)) for i in range(3)]


def _rare_object(object_index: int):
    rows = [
        o for o in bpy.data.objects
        if o.type == 'MESH'
        and str(o.get('pt_rare_role', '')) == 'RARE'
        and int(o.get('pt_source_object_index', -1)) == object_index
    ]
    if len(rows) != 1:
        raise RuntimeError(f'rare object unresolved {object_index}: {len(rows)}')
    return rows[0]


def main(argv):
    a = _parse(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text(encoding='utf-8'))
    per_object = list(plan.get('per_object_plans') or [])
    if len(per_object) < 2:
        raise RuntimeError('cross-object transaction requires >=2 object plans')

    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    if str(getattr(bpy.context, 'mode', 'UNKNOWN')) != 'OBJECT':
        raise RuntimeError(f'cannot canonicalize to OBJECT:{getattr(bpy.context, "mode", "UNKNOWN")}')

    target_objects = []
    before = []
    after = []
    total = 0
    seen_objects = set()

    # Clear selection state globally before preparing a multi-object edit-mode save.
    for o in bpy.data.objects:
        if o.type == 'MESH':
            o.select_set(False)
            for v in o.data.vertices:
                v.select = False
            for e in o.data.edges:
                e.select = False
            for p in o.data.polygons:
                p.select = False
            o.data.update()

    for obj_plan in per_object:
        oi = int(obj_plan['object_index'])
        if oi in seen_objects:
            raise RuntimeError(f'duplicate object plan {oi}')
        seen_objects.add(oi)
        o = _rare_object(oi)
        target_objects.append((oi, o))
        changes = list(obj_plan.get('changed_vertices') or [])
        if len(changes) < 1:
            raise RuntimeError(f'object {oi} has no changed vertices')
        for ch in changes:
            vi = int(ch['vertex_index'])
            v = o.data.vertices[vi]
            actual_before = _fixed(v.co)
            expected_before = [int(x) for x in ch['before_world_fixed']]
            if actual_before != expected_before:
                raise RuntimeError(f'before mismatch object={oi} vertex={vi}: {actual_before}!={expected_before}')
            target = [int(x) for x in ch['requested_after_world_fixed']]
            v.co = [x / 256.0 for x in target]
            actual_after = _fixed(v.co)
            if actual_after != target:
                raise RuntimeError(f'fixed quantization mismatch object={oi} vertex={vi}: {actual_after}!={target}')
            v.select = True
            before.append({'object_index': oi, 'vertex_index': vi, 'world_fixed': actual_before})
            after.append({'object_index': oi, 'vertex_index': vi, 'world_fixed': actual_after})
            total += 1
        o.data.update()

    # Select all affected mesh objects, then enter multi-object mesh edit mode. The
    # coordinates were already installed in OBJECT mode; EDIT_MESH is the persisted
    # artist-state transport being tested here.
    for oi, o in target_objects:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = target_objects[0][1]
    bpy.ops.object.mode_set(mode='EDIT')
    raw_mode = str(getattr(bpy.context.object, 'mode', 'UNKNOWN')) if bpy.context.object else 'NONE'
    semantic_mode = str(getattr(bpy.context, 'mode', 'UNKNOWN'))
    in_mode = sorted(
        int(o.get('pt_source_object_index', -1))
        for o in getattr(bpy.context, 'objects_in_mode', [])
        if o.type == 'MESH' and str(o.get('pt_rare_role', '')) == 'RARE'
    )
    expected_objects = sorted(seen_objects)
    if raw_mode != 'EDIT' or semantic_mode != 'EDIT_MESH':
        raise RuntimeError(f'multi-object edit mode failed raw={raw_mode} semantic={semantic_mode}')
    if in_mode != expected_objects:
        raise RuntimeError(f'objects_in_mode mismatch:{in_mode}!={expected_objects}')

    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    saved_raw_mode = str(getattr(bpy.context.object, 'mode', 'UNKNOWN')) if bpy.context.object else 'NONE'
    saved_semantic_mode = str(getattr(bpy.context, 'mode', 'UNKNOWN'))
    saved_in_mode = sorted(
        int(o.get('pt_source_object_index', -1))
        for o in getattr(bpy.context, 'objects_in_mode', [])
        if o.type == 'MESH' and str(o.get('pt_rare_role', '')) == 'RARE'
    )
    if saved_raw_mode != 'EDIT' or saved_semantic_mode != 'EDIT_MESH' or saved_in_mode != expected_objects:
        raise RuntimeError(
            f'saved multi-object edit state mismatch raw={saved_raw_mode} semantic={saved_semantic_mode} '
            f'objects={saved_in_mode} expected={expected_objects}'
        )

    result = {
        'format': 'PT_RARE_RIGID_CROSS_OBJECT_SAVED_BLENDER_APPLY_V1',
        'check': 'PASS',
        'object_count': len(target_objects),
        'object_indices': expected_objects,
        'changed_vertex_count': total,
        'before': before,
        'after': after,
        'blend': bpy.data.filepath,
        'saved_mode_raw': saved_raw_mode,
        'saved_mode': saved_semantic_mode,
        'objects_in_mode': saved_in_mode,
        'selection_only_non_position_state': True,
        'client_modified': False,
    }
    rp = pathlib.Path(a.report).resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(
        'PT_RARE_CROSS_OBJECT_SAVE=PASS '
        f'objects={len(target_objects)} changed_vertices={total} mode={saved_semantic_mode}'
    )


if __name__ == '__main__':
    av = sys.argv
    av = av[av.index('--') + 1:] if '--' in av else []
    main(av)
