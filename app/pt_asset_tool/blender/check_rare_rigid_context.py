from __future__ import annotations

import argparse
import importlib.util
import json
import math
import pathlib
import sys

import bpy


def load_importer(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("pt_rare_rigid_check_importer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load importer: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--importer", required=True)
    p.add_argument("--rare-smd", required=True)
    p.add_argument("--root-smd", required=True)
    p.add_argument("--skeleton", required=True)
    p.add_argument("--rare-model-info", required=True)
    p.add_argument("--root-model-info", required=True)
    p.add_argument("--root-lod", choices=("high", "default", "low"), required=True)
    p.add_argument("--rare-visibility-policy", choices=("SOURCE_INX_EXACT", "SOURCE_INX_EMPTY_SHOW_ALL_DIAGNOSTIC"), required=True)
    p.add_argument("--report", required=True)
    return p.parse_args(argv)


def source_bundle(m, smd: pathlib.Path, skeleton_bones):
    data = smd.read_bytes()
    meta = m.parse_header_and_infos(data)
    objs = m.parse_objects(data, meta)
    m.reconstruct_bind_pose(objs, skeleton_bones)
    return meta, objs


def role_objects(role: str):
    rows = [o for o in bpy.data.objects if o.type == "MESH" and str(o.get("pt_rare_role", "")) == role]
    return sorted(rows, key=lambda o: int(o.get("pt_source_object_index", -1)))


def max_position_error(src_objs, bl_objs):
    worst = 0.0
    mismatch = 0
    if len(src_objs) != len(bl_objs):
        return float("inf"), abs(len(src_objs) - len(bl_objs))
    for i, (src, obj) in enumerate(zip(src_objs, bl_objs)):
        if int(obj.get("pt_source_object_index", -1)) != i or len(obj.data.vertices) != len(src["vertices"]):
            mismatch += 1
            continue
        for v, exp in zip(obj.data.vertices, src["vertices"]):
            got = v.co
            err = max(abs(float(got[j]) - float(exp[j])) for j in range(3))
            worst = max(worst, err)
    return worst, mismatch


def max_uv_error(src_objs, bl_objs):
    worst = 0.0
    mismatch = 0
    if len(src_objs) != len(bl_objs):
        return float("inf"), abs(len(src_objs) - len(bl_objs))
    for src, obj in zip(src_objs, bl_objs):
        uv = obj.data.uv_layers.get("SMD_UV")
        if uv is None or len(obj.data.polygons) != len(src["faces"]):
            mismatch += 1
            continue
        for pi, fd in enumerate(src["faces"]):
            chain = fd.get("texlinks") or []
            if not chain:
                continue
            tl = src["texlinks"][chain[0]]
            exp = [(float(tl["u"][j]), 1.0 - float(tl["v"][j])) for j in range(3)]
            poly = obj.data.polygons[pi]
            if len(poly.loop_indices) != 3:
                mismatch += 1
                continue
            for li, e in zip(poly.loop_indices, exp):
                got = uv.data[li].uv
                err = max(abs(float(got[0]) - e[0]), abs(float(got[1]) - e[1]))
                worst = max(worst, err)
    return worst, mismatch


def physique_mismatches(src_objs, bl_objs):
    bad = 0
    checked = 0
    for src, obj in zip(src_objs, bl_objs):
        expected = src.get("bones")
        if expected is None:
            continue
        group_names = {g.index: g.name for g in obj.vertex_groups}
        for vi, bone in enumerate(expected):
            if not bone:
                continue
            checked += 1
            actual = []
            for ref in obj.data.vertices[vi].groups:
                if float(ref.weight) > 0.999:
                    actual.append(group_names.get(ref.group, ""))
            if actual != [bone]:
                bad += 1
    return checked, bad


def expected_visibility(src_objs, groups, lod, policy):
    if policy == "SOURCE_INX_EMPTY_SHOW_ALL_DIAGNOSTIC":
        return [True] * len(src_objs)
    active = [str(x) for x in (groups[lod].get("active") or []) if str(x)]
    def matches(slot, node):
        sk = slot.encode("latin-1", errors="replace").lower()
        nk = str(node).encode("latin-1", errors="replace").lower()
        return nk[:16] == sk if len(sk) == 16 else nk == sk
    return [any(matches(slot, o["name"]) for slot in active) for o in src_objs]


def visibility_mismatches(src_objs, bl_objs, expected):
    bad = 0
    for src, obj, exp in zip(src_objs, bl_objs, expected):
        # hide_render is persisted and context-independent; importer sets it together with viewport hiding.
        visible = not bool(obj.hide_render)
        if visible != bool(exp):
            bad += 1
    return bad


def material_index_mismatches(src_objs, bl_objs):
    bad = 0
    checked = 0
    for src, obj in zip(src_objs, bl_objs):
        if len(src["faces"]) != len(obj.data.polygons):
            bad += 1
            continue
        for fd, poly in zip(src["faces"], obj.data.polygons):
            checked += 1
            if int(poly.material_index) != int(fd["material"]):
                bad += 1
    return checked, bad


def main(argv):
    args = parse_args(argv)
    m = load_importer(pathlib.Path(args.importer).resolve())
    skel_data = pathlib.Path(args.skeleton).resolve().read_bytes()
    _, skeleton_bones = m.parse_skeleton_tms(skel_data)
    rare_meta, rare_src = source_bundle(m, pathlib.Path(args.rare_smd).resolve(), skeleton_bones)
    root_meta, root_src = source_bundle(m, pathlib.Path(args.root_smd).resolve(), skeleton_bones)
    rare_groups = m.parse_inx_model_groups(pathlib.Path(args.rare_model_info).resolve())
    root_groups = m.parse_inx_model_groups(pathlib.Path(args.root_model_info).resolve())

    rare_bl = role_objects("RARE")
    root_bl = role_objects("ROOT")
    pos_r, pos_struct_r = max_position_error(rare_src, rare_bl)
    pos_b, pos_struct_b = max_position_error(root_src, root_bl)
    uv_r, uv_struct_r = max_uv_error(rare_src, rare_bl)
    uv_b, uv_struct_b = max_uv_error(root_src, root_bl)
    phys_checked_r, phys_bad_r = physique_mismatches(rare_src, rare_bl)
    phys_checked_b, phys_bad_b = physique_mismatches(root_src, root_bl)
    mat_checked_r, mat_bad_r = material_index_mismatches(rare_src, rare_bl)
    mat_checked_b, mat_bad_b = material_index_mismatches(root_src, root_bl)

    expected_rare = expected_visibility(rare_src, rare_groups, args.root_lod, args.rare_visibility_policy)
    expected_root = expected_visibility(root_src, root_groups, args.root_lod, "SOURCE_INX_EXACT")
    vis_bad_r = visibility_mismatches(rare_src, rare_bl, expected_rare)
    vis_bad_b = visibility_mismatches(root_src, root_bl, expected_root)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE" and o.name == "PT_RARE_CONTEXT_ARMATURE"]
    arm_bad = 0
    missing_bones = []
    modifier_bad = 0
    if len(arms) != 1:
        arm_bad = 1
    else:
        arm = arms[0]
        arm_names = {b.name for b in arm.data.bones}
        rare_bones = sorted({b for o in rare_src for b in (o.get("bones") or []) if b}, key=str.lower)
        missing_bones = [b for b in rare_bones if b not in arm_names]
        for obj in rare_bl + root_bl:
            mods = [x for x in obj.modifiers if x.type == "ARMATURE" and x.object == arm]
            if len(mods) != 1:
                modifier_bad += 1

    texture_errors = []
    for mat in bpy.data.materials:
        if str(mat.get("pt_rare_role", "")) not in {"RARE", "ROOT"}:
            continue
        status = str(mat.get("pt_smd_texture_load", ""))
        if status.startswith("LOAD_ERROR"):
            texture_errors.append({"material": mat.name, "status": status, "texture": str(mat.get("pt_smd_texture_name", ""))})

    max_pos = max(pos_r, pos_b)
    max_uv = max(uv_r, uv_b)
    structural_bad = pos_struct_r + pos_struct_b + uv_struct_r + uv_struct_b
    physique_bad = phys_bad_r + phys_bad_b
    material_bad = mat_bad_r + mat_bad_b
    visibility_bad = vis_bad_r + vis_bad_b
    failures = {
        "object_structure_mismatch_count": structural_bad,
        "physique_mismatch_count": physique_bad,
        "material_index_mismatch_count": material_bad,
        "visibility_mismatch_count": visibility_bad,
        "armature_structure_mismatch_count": arm_bad,
        "armature_modifier_mismatch_count": modifier_bad,
        "missing_rare_bones": missing_bones,
        "texture_load_error_count": len(texture_errors),
    }
    ok = (
        structural_bad == 0 and physique_bad == 0 and material_bad == 0 and visibility_bad == 0 and
        arm_bad == 0 and modifier_bad == 0 and not missing_bones and not texture_errors and
        math.isfinite(max_pos) and max_pos <= 2e-5 and math.isfinite(max_uv) and max_uv <= 2e-6
    )
    result = {
        "check": "PASS" if ok else "FAIL",
        "rare_objects": len(rare_bl), "root_objects": len(root_bl),
        "rare_vertices": sum(len(o.data.vertices) for o in rare_bl),
        "root_vertices": sum(len(o.data.vertices) for o in root_bl),
        "rare_faces": sum(len(o.data.polygons) for o in rare_bl),
        "root_faces": sum(len(o.data.polygons) for o in root_bl),
        "max_position_abs_error": max_pos,
        "max_uv_abs_error": max_uv,
        "rare_physique_vertices_checked": phys_checked_r,
        "root_physique_vertices_checked": phys_checked_b,
        "physique_mismatch_count": physique_bad,
        "rare_material_faces_checked": mat_checked_r,
        "root_material_faces_checked": mat_checked_b,
        "material_index_mismatch_count": material_bad,
        "visibility_mismatch_count": visibility_bad,
        "armature_modifier_mismatch_count": modifier_bad,
        "missing_rare_bones": missing_bones,
        "texture_load_error_count": len(texture_errors),
        "texture_load_errors": texture_errors,
        "rare_visibility_policy": args.rare_visibility_policy,
        "root_lod": args.root_lod,
        "failures": failures,
        "write_authorized": False,
        "client_modified": False,
    }
    report = pathlib.Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "PT_RARE_RIGID_TRANSPORT=" + result["check"] +
        f" pos={max_pos:.9g} uv={max_uv:.9g} physique_bad={physique_bad}" +
        f" visibility_bad={visibility_bad} texture_errors={len(texture_errors)}"
    )
    if not ok:
        raise RuntimeError(f"rare rigid persisted transport failed: {failures}")


if __name__ == "__main__":
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    main(argv)
