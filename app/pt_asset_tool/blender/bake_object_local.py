from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    import bpy
    from mathutils import Matrix, Vector
except Exception:
    bpy = None
    Matrix = Vector = None

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pt_asset_tool.object_local import (  # noqa: E402
    ENGINE_UNITS_PER_PREVIEW_FRAME,
    compact_report,
    matrix4_identity_error,
    normalized_sample,
    normalized_world_affine_delta,
    parse_object_local_smd,
)


def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--engine-step", type=int, default=ENGINE_UNITS_PER_PREVIEW_FRAME)
    return p.parse_args(argv)


def _numeric_suffix_rank(name: str, base: str):
    if name.casefold() == base.casefold():
        return (0, 0, name.casefold())
    prefix = base + "."
    if name.casefold().startswith(prefix.casefold()):
        tail = name[len(prefix):]
        if tail.isdigit():
            return (1, int(tail), name.casefold())
    return (2, 10**9, name.casefold())


def _map_source_meshes(parsed):
    """Map serialized objects to Blender meshes by source order, including duplicates.

    Blender renames duplicate object names to ``Name.001`` etc.  The client SMD
    format allows duplicate NodeName values, so name-only lookup is insufficient.
    """
    all_meshes = [o for o in bpy.data.objects if getattr(o, "type", None) == "MESH"]
    used = set()
    mapped = {}
    for src in parsed["objects"]:
        base = str(src["name"])
        hits = [o for o in all_meshes
                if id(o) not in used and
                (o.name.casefold() == base.casefold() or o.name.casefold().startswith((base + ".").casefold()))]
        hits.sort(key=lambda o: _numeric_suffix_rank(o.name, base))
        if not hits:
            raise RuntimeError(
                f"source object not present in Blender by serialized order: index={src['index']} name={base!r}"
            )
        obj = hits[0]
        used.add(id(obj))
        mapped[int(src["index"])] = obj
    return mapped


def _action_curves(action):
    try:
        return list(action.fcurves)
    except Exception:
        curves = []
        try:
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in getattr(strip, "channelbags", []):
                        curves.extend(list(getattr(bag, "fcurves", [])))
        except Exception:
            pass
        return curves


def _set_id_linear_interpolation(idblock):
    ad = getattr(idblock, "animation_data", None)
    if ad is None or ad.action is None:
        return
    for fc in _action_curves(ad.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"


def _set_linear_interpolation(obj):
    _set_id_linear_interpolation(obj)


def _relative_shape_crossfade_keyframes(sample_frames, index: int):
    """Return (frame, value) keys for one sampled relative shape key.

    The schedule forms a linear hat function.  Across every interval between
    adjacent samples, exactly two keys are active and their weights sum to 1.
    """
    frames = [float(x) for x in sample_frames]
    if not (0 <= index < len(frames)):
        raise IndexError(index)
    out = []
    if index > 0:
        out.append((frames[index - 1], 0.0))
    out.append((frames[index], 1.0))
    if index + 1 < len(frames):
        out.append((frames[index + 1], 0.0))
    return out


def _global_engine_frames(animated_sources, step: int):
    global_ref = min(int(o["reference_engine_frame"]) for o in animated_sources)
    global_end = max(int(o["max_engine_frame"]) for o in animated_sources)
    frames = {global_ref, global_end}
    for src in animated_sources:
        frames.update(int(x) for x in src.get("source_key_frames") or [])
    f = global_ref
    while f <= global_end:
        frames.add(f)
        f += step
    return global_ref, global_end, sorted(x for x in frames if global_ref <= x <= global_end)


def _bake_legacy_affine_shape_preview(parsed, blender_by_index, frames, global_ref, engine_step):
    """Bake full affine runtime deltas as sampled relative shape keys.

    Blender object TRS channels cannot represent arbitrary accumulated shear.
    Blender 5.1 also exposes ``ShapeKey.frame`` as read-only, so the previous
    absolute-shape/eval_time path cannot be authored reliably.  V0.5.1 keeps
    the exact same sampled world-affine matrices, but stores each sample as a
    *relative* shape key and linearly crossfades consecutive keys:

    - exact sample frame: current key value=1, neighbours=0;
    - between samples: previous key fades 1->0 while next fades 0->1.

    Vertex positions therefore interpolate linearly between the same affine
    samples without writing any read-only ShapeKey properties.  This remains a
    preview-only representation; source SMD and export semantics are untouched.
    """
    static_world = {idx: obj.matrix_world.copy() for idx, obj in blender_by_index.items()}
    base_coords = {idx: [v.co.copy() for v in obj.data.vertices] for idx, obj in blender_by_index.items()}
    affected = []
    sample_rows = []

    # Precompute deltas so inherited motion is included even for children that
    # have no local curves of their own.
    deltas = {}
    for idx, obj in blender_by_index.items():
        per = []
        changed = False
        for ef in frames:
            d = normalized_world_affine_delta(parsed, idx, ef, global_ref)
            err = matrix4_identity_error(d)
            if err > 1e-7:
                changed = True
            per.append((ef, d, err))
        deltas[idx] = per
        if changed:
            affected.append(idx)

    for idx in affected:
        obj = blender_by_index[idx]
        if obj.data.shape_keys is not None:
            raise RuntimeError(f"legacy affine preview refuses pre-existing shape keys: object={obj.name}")

        basis = obj.shape_key_add(name="Basis", from_mix=False)
        keys = obj.data.shape_keys
        keys.use_relative = True
        w0 = static_world[idx]
        w0_inv = w0.inverted()
        original = base_coords[idx]
        samples = []

        for ef, dcol, err in deltas[idx]:
            bf = 1.0 + (float(ef) - float(global_ref)) / float(engine_step)
            kb = obj.shape_key_add(name=f"PT_AFFINE_{int(round(bf)):04d}", from_mix=False)
            kb.relative_key = basis
            kb.value = 0.0
            local = w0_inv @ Matrix(dcol) @ w0
            for vi, co in enumerate(original):
                kb.data[vi].co = local @ co
            samples.append((bf, kb))
            if ef in {frames[0], frames[len(frames)//2], frames[-1]}:
                sample_rows.append({
                    "object": parsed["objects"][idx]["name"], "object_index": idx,
                    "engine_frame": ef, "blender_frame": bf,
                    "affine_identity_error": err,
                    "affine_matrix_blender_column": [list(r) for r in dcol],
                })

        # Crossfade adjacent samples.  Between sample i and i+1 exactly two
        # weights are active and their sum is 1, yielding a linear interpolation
        # of vertex positions.  No ShapeKey.frame/eval_time API is used.
        sample_frames = [bf for bf, _kb in samples]
        for i, (_bf, kb) in enumerate(samples):
            for kf_frame, kf_value in _relative_shape_crossfade_keyframes(sample_frames, i):
                kb.value = kf_value
                kb.keyframe_insert(data_path="value", frame=kf_frame, group="PT_LEGACY_AFFINE")

        _set_id_linear_interpolation(keys)

    return affected, sample_rows


def bake(a):
    if bpy is None:
        raise RuntimeError("bake_object_local.py must run inside Blender")
    if a.fps <= 0 or a.fps > 240:
        raise ValueError("fps must be 1..240")
    if a.engine_step <= 0:
        raise ValueError("engine-step must be positive")

    smd = pathlib.Path(a.smd).expanduser().resolve()
    out = pathlib.Path(a.out).expanduser().resolve()
    report_path = pathlib.Path(a.report).expanduser().resolve()
    parsed = parse_object_local_smd(smd, strict_v1=True)

    animated_sources = [o for o in parsed["objects"] if o["motion_class"] == "ANIMATED"]
    zero_scale_spawn_sources = [o for o in animated_sources if o.get("zero_scale_reference_axes")]
    if not animated_sources:
        raise RuntimeError("object-local source contains no moving transforms (HOLD/NONE only)")
    blender_by_index = _map_source_meshes(parsed)
    legacy_affine = bool(parsed.get("legacy_affine_object_count"))
    for src in parsed["objects"]:
        obj = blender_by_index[int(src["index"])]
        obj.animation_data_clear()
        obj.rotation_mode = "QUATERNION"
        obj.delta_location = (0.0, 0.0, 0.0)
        obj.delta_scale = (1.0, 1.0, 1.0)
        obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)

    global_ref, global_end, frames = _global_engine_frames(animated_sources, int(a.engine_step))
    previous_q = {}
    sample_rows = []
    animated_names = [o["name"] for o in animated_sources]
    affine_affected_names=[]

    if legacy_affine:
        # V4 affine path: do not parent Blender objects.  Each mesh receives its
        # complete sampled world delta, which includes inherited parent motion.
        affected, sample_rows = _bake_legacy_affine_shape_preview(
            parsed, blender_by_index, frames, global_ref, int(a.engine_step)
        )
        affine_affected_names=[parsed["objects"][i]["name"] for i in affected]
    else:
        # V3 normal path: recreate resolved runtime parent edges and animate local
        # deltas over the imported static bind.
        for src in parsed["objects"]:
            pi = src.get("parent_index")
            if pi is None:
                continue
            child = blender_by_index[int(src["index"])]
            parent = blender_by_index[int(pi)]
            world = child.matrix_world.copy()
            child.parent = parent
            child.matrix_world = world

        for src in animated_sources:
            obj = blender_by_index[int(src["index"])]
            src_key = int(src["index"])
            ref = int(src["reference_engine_frame"])
            for ef in frames:
                sample = normalized_sample(src, ef, ref)
                qx, qy, qz, qw = (float(v) for v in sample["rotation_xyzw"])
                q_xyzw = (qx, qy, qz, qw)
                prev = previous_q.get(src_key)
                if prev is not None and sum(x*y for x, y in zip(prev, q_xyzw)) < 0.0:
                    q_xyzw = tuple(-x for x in q_xyzw)
                    qx, qy, qz, qw = q_xyzw
                previous_q[src_key] = q_xyzw

                bf = 1.0 + (float(ef)-float(global_ref))/float(a.engine_step)
                obj.delta_location = tuple(float(v) for v in sample["location"])
                obj.delta_scale = tuple(float(v) for v in sample["scale"])
                obj.delta_rotation_quaternion = (qw, qx, qy, qz)
                obj.keyframe_insert(data_path="delta_location", frame=bf, group="PT_OBJECT_LOCAL")
                obj.keyframe_insert(data_path="delta_scale", frame=bf, group="PT_OBJECT_LOCAL")
                obj.keyframe_insert(data_path="delta_rotation_quaternion", frame=bf, group="PT_OBJECT_LOCAL")
                if ef in {frames[0], frames[len(frames)//2], frames[-1]}:
                    sample_rows.append({"object": src["name"], "object_index": src_key, "engine_frame": ef, "blender_frame": bf, **sample})
            _set_linear_interpolation(obj)

    scene = bpy.context.scene
    scene.render.fps = int(a.fps)
    scene.frame_start = 1
    scene.frame_end = int(round(1.0 + (global_end-global_ref)/float(a.engine_step)))
    scene.frame_set(1)
    scene["pt_object_local_preview"] = True
    scene["pt_object_local_preview_version"] = 6 if zero_scale_spawn_sources else (5 if legacy_affine else 3)
    scene["pt_object_local_source"] = str(smd)
    scene["pt_object_local_animated_objects"] = json.dumps(animated_names, ensure_ascii=False)
    scene["pt_object_local_parent_edge_count"] = int(parsed.get("parent_edge_count", 0))
    scene["pt_object_local_hierarchy_semantics"] = "LOCAL_QMAT_TIMES_PARENT_TMRESULT"
    scene["pt_object_local_preview_reference"] = (
        "FIRST_KEY_NORMALIZED_FULL_AFFINE_SHAPEKEY" if legacy_affine else
        ("FIRST_KEY_NORMALIZED_WITH_ZERO_SCALE_SPAWN_ABSOLUTE_OVER_STATIC_BIND" if zero_scale_spawn_sources else
         "FIRST_KEY_NORMALIZED_PER_OBJECT_DELTA_OVER_STATIC_BIND")
    )
    scene["pt_object_local_zero_scale_spawn_count"] = len(zero_scale_spawn_sources)
    scene["pt_object_local_rotation_semantics"] = "RAW_NONUNIT_QUATERNION_AFFINE" if legacy_affine else "ACCUMULATED_TM_PREV_ROT"
    scene["pt_object_local_source_rot_key_semantics"] = "INCREMENTAL_LOCAL_QUATERNION"
    scene["pt_object_local_engine_units_per_frame"] = int(a.engine_step)
    scene["pt_object_local_max_engine_frame"] = int(global_end)
    scene["pt_object_local_timing_status"] = "PREVIEW_NOT_RUNTIME_SPEED_CERTIFIED"

    out.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))

    source_summary = compact_report(parsed)
    channels = sorted({c for src in animated_sources for c in src["channels_animated"]})
    preview_version = 6 if zero_scale_spawn_sources else (5 if legacy_affine else 3)
    report = {
        "format": f"PT_OBJECT_LOCAL_BLENDER_PREVIEW_V{preview_version}",
        "preview_version": preview_version,
        "status": "PASS",
        "source": str(smd),
        "blend": str(out),
        "object_count": parsed["object_count"],
        "animated_object_count": len(animated_sources),
        "animated_objects": animated_names,
        "parent_edge_count": parsed.get("parent_edge_count", 0),
        "parent_edges": parsed.get("parent_edges", []),
        "root_objects": parsed.get("root_objects", []),
        "unresolved_parent_count": parsed.get("unresolved_parent_count", 0),
        "unresolved_parents": parsed.get("unresolved_parents", []),
        "duplicate_node_name_group_count": parsed.get("duplicate_node_name_group_count", 0),
        "duplicate_node_name_groups": parsed.get("duplicate_node_name_groups", {}),
        "parent_resolution_semantics": parsed.get("parent_resolution_semantics"),
        "channels_animated": channels,
        "reference_engine_frame": global_ref,
        "max_engine_frame": global_end,
        "engine_units_per_preview_frame": int(a.engine_step),
        "preview_frame_start": scene.frame_start,
        "preview_frame_end": scene.frame_end,
        "preview_fps": scene.render.fps,
        "preview_reference": (
            "FIRST_KEY_NORMALIZED_FULL_AFFINE_SHAPEKEY" if legacy_affine else
            ("FIRST_KEY_NORMALIZED_WITH_ZERO_SCALE_SPAWN_ABSOLUTE_OVER_STATIC_BIND" if zero_scale_spawn_sources else
             "FIRST_KEY_NORMALIZED_PER_OBJECT_DELTA_OVER_STATIC_BIND")
        ),
        "blender_transform_semantics": "AFFINE_WORLD_DELTA_RELATIVE_SHAPE_KEY_CROSSFADE" if legacy_affine else "DELTA_TRANSFORMS_OVER_STATIC_BIND",
        "zero_scale_spawn_object_count": len(zero_scale_spawn_sources),
        "zero_scale_spawn_objects": [o["name"] for o in zero_scale_spawn_sources],
        "scale_reference_semantics": "ZERO_SCALE_SPAWN_EXCEPTION_WHEN_REFERENCE_AXIS_IS_ZERO",
        "legacy_affine_object_count": parsed.get("legacy_affine_object_count",0),
        "legacy_affine_objects": parsed.get("legacy_affine_objects",[]),
        "affine_affected_objects": affine_affected_names,
        "hierarchy_semantics": "LOCAL_QMAT_TIMES_PARENT_TMRESULT",
        "hierarchy_sourcecode_proof": "smOBJ3D::TmAnimation qmat * pParent->TmResult; smPAT3D::LinkObject parent-first TmSort",
        "rotation_semantics": "RAW_NONUNIT_QUATERNION_MATRIX" if legacy_affine else "ACCUMULATED_TM_PREV_ROT",
        "source_rot_key_semantics": "INCREMENTAL_LOCAL_QUATERNION",
        "legacy_affine_interpolation": "D3DMATH_ZERO_TO_NEXT_INCREMENTAL_SLERP_COMPAT_SAMPLED_EVERY_SOURCE_TICK" if legacy_affine else None,
        "quaternion_sign_continuity": True,
        "interpolation": "LINEAR_SAMPLED_EVERY_SOURCE_TICK",
        "timing_status": "PREVIEW_NOT_RUNTIME_SPEED_CERTIFIED",
        "samples": sample_rows,
        "source_summary": source_summary,
        "client_modified": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"PT_OBJECT_LOCAL_BLENDER_PREVIEW_V{preview_version}")
    print(f"objects={parsed['object_count']} animated={len(animated_sources)} parent_edges={parsed.get('parent_edge_count',0)}")
    print(f"animated_objects={animated_names}")
    print(f"source_frames={global_ref}..{global_end}")
    print(f"preview_frames={scene.frame_start}..{scene.frame_end}")
    print(f"preview_fps={scene.render.fps}")
    print("hierarchy_semantics=LOCAL_QMAT_TIMES_PARENT_TMRESULT")
    print("blender_transform_semantics=" + ("AFFINE_WORLD_DELTA_RELATIVE_SHAPE_KEY_CROSSFADE" if legacy_affine else "DELTA_TRANSFORMS_OVER_STATIC_BIND"))
    print("timing_status=PREVIEW_NOT_RUNTIME_SPEED_CERTIFIED")
    print("client_modified=False")
    print("object_local_preview_check=PASS")


def main(argv):
    a = parse_args(argv)
    bake(a)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    main(argv)
