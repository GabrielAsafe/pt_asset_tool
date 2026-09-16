#!/usr/bin/env python3
"""
Priston Tale SMD Model0.62 -> Blender V4 Generic

Modes:
- RIGID: delegates to the proven V3 path when every object has Physique.
- STATIC: imports a fully no-Physique Model0.62 without armature.

Mixed Physique/static SMD is intentionally rejected until a representative is
certified. No client files are modified.
"""
from __future__ import annotations
import argparse, importlib.util, pathlib, struct, sys

def load_v3():
    here = pathlib.Path(__file__).resolve()
    candidates = [
        here.parent / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py",
        here.with_name("pt_smd_blender_import_v3_static_armature.py"),
    ]
    p = next((x for x in candidates if x.is_file()), None)
    if p is None:
        raise FileNotFoundError("V3 importer not found")
    spec = importlib.util.spec_from_file_location("pt_import_v3_core", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--skeleton")
    p.add_argument("--model-info")
    p.add_argument("--lod", choices=("high", "default", "low"), default="default")
    p.add_argument("--client-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cache")
    p.add_argument("--no-pack", action="store_true")
    return p.parse_args(argv)

def physique_modes(data):
    def cs(b):
        return b.split(b"\0", 1)[0].decode("latin1", "replace")
    n = struct.unpack_from("<i", data, 24)[0]
    rows = []
    for i in range(n):
        off = 556 + i * 40
        name = cs(data[off : off + 32])
        start = struct.unpack_from("<i", data, off + 36)[0]
        ptr = struct.unpack_from("<I", data, start + 16)[0]
        rows.append((name, ptr != 0))
    return rows

def rigid_delegate(v3, a):
    if not a.skeleton or not a.model_info:
        raise RuntimeError(
            "rigid model requires --skeleton and --model-info for V3 parity"
        )
    args = [
        "--smd", a.smd,
        "--skeleton", a.skeleton,
        "--model-info", a.model_info,
        "--lod", a.lod,
        "--client-root", a.client_root,
        "--out", a.out,
    ]
    if a.cache:
        args += ["--cache", a.cache]
    if a.no_pack:
        args.append("--no-pack")
    v3.main(args)
    print("pt_import_mode=RIGID_DELEGATED_V3")
    print("generic_import_check=PASS")

def static_import(v3, a, smd_path, data):
    if v3.bpy is None:
        raise RuntimeError("This script must run inside Blender")

    client_root = pathlib.Path(a.client_root).expanduser().resolve()
    out_path = pathlib.Path(a.out).expanduser().resolve()
    cache_dir = (
        pathlib.Path(a.cache).expanduser().resolve()
        if a.cache else out_path.parent / "_pt_smd_texture_cache"
    )

    meta = v3.parse_header_and_infos(data)
    materials = v3.parse_materials(data, meta)
    objects = v3.parse_objects(data, meta)
    if any(o["has_physique"] for o in objects):
        raise RuntimeError("static path received Physique object")

    v3.clear_scene()
    collection = v3.ensure_collection("PT_SMD_IMPORT_V4_STATIC")
    blender_materials = v3.create_blender_materials(
        materials, client_root, cache_dir, pack_images=not a.no_pack
    )

    stats = []
    blender_objects = []
    for src_obj in objects:
        obj, info = v3.create_mesh_object(src_obj, collection, blender_materials)
        blender_objects.append(obj)
        stats.append(info)

    if a.model_info:
        groups = v3.parse_inx_model_groups(
            pathlib.Path(a.model_info).expanduser().resolve()
        )
        visible, hidden = v3.apply_lod_visibility(
            blender_objects, groups, a.lod
        )
    else:
        visible = [o.name for o in blender_objects]
        hidden = []
        for o in blender_objects:
            o.hide_viewport = False
            o.hide_render = False

    total_v = sum(x["vertices"] for x in stats)
    total_f = sum(x["faces"] for x in stats)
    total_uv = sum(x["uv_faces"] for x in stats)

    scene = v3.bpy.context.scene
    scene["pt_smd_source"] = str(smd_path)
    scene["pt_smd_version"] = "SMD Model data Ver 0.62"
    scene["pt_smd_import_mode"] = "STATIC_NO_PHYSIQUE"
    scene["pt_smd_object_count"] = len(objects)
    scene["pt_smd_material_count"] = len(materials)
    scene["pt_smd_total_vertices"] = total_v
    scene["pt_smd_total_faces"] = total_f
    scene["pt_smd_total_uv_faces"] = total_uv
    scene["pt_inx_lod"] = a.lod if a.model_info else "NONE"
    scene["pt_inx_visible_nodes"] = ",".join(visible)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    v3.bpy.ops.wm.save_as_mainfile(filepath=str(out_path))

    print("PT_SMD_BLENDER_IMPORT_V4_GENERIC")
    print("pt_import_mode=STATIC_NO_PHYSIQUE")
    print(f"objects={len(objects)}")
    print(f"materials={len(materials)}")
    print(f"vertices={total_v}")
    print(f"faces={total_f}")
    print(f"uv_faces={total_uv}")
    print("armature_bones=0")
    print("mesh_armature_modifiers=0")
    print(f"visible_objects={visible!r}")
    print(f"hidden_objects={hidden!r}")
    print(f"blend={out_path}")
    print("client_modified=False")
    print("generic_import_check=PASS")

def main(argv):
    a = parse_args(argv)
    v3 = load_v3()
    smd_path = pathlib.Path(a.smd).expanduser().resolve()
    data = smd_path.read_bytes()
    modes = physique_modes(data)
    any_phys = any(x[1] for x in modes)
    all_phys = all(x[1] for x in modes)

    if any_phys and not all_phys:
        raise RuntimeError(
            "mixed Physique/static Model0.62 is not certified by V4 generic"
        )
    if all_phys:
        rigid_delegate(v3, a)
    else:
        static_import(v3, a, smd_path, data)

if __name__ == "__main__":
    try:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
        main(argv)
    except Exception as exc:
        print(f"generic_import_check=FAIL: {type(exc).__name__}: {exc}")
        raise
