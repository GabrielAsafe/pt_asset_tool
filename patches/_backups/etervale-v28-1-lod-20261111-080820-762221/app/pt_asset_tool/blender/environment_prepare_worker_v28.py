"""V28 background Blender worker: create source-hash keyed preview LOD .blend files.

Launch from host with `blender --background --factory-startup --python ... -- args`.
This worker must NEVER open or save an Etervale Stage and must never write
outside its dedicated per-asset temporary output directory.
"""
from __future__ import annotations

import argparse
import json
from math import inf, isfinite
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

LOD_BUDGETS = {'LOD0': 120_000, 'LOD1': 35_000, 'LOD2': 7_000}
MAX_SOURCE_VERTICES = 8_000_000
MAX_SOURCE_FACES = 10_000_000
MAX_OBJECTS = 256


def _args():
    rest = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--result', required=True, type=Path)
    return p.parse_args(rest)


def _read_source(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('V28_SOURCE_INEXISTENTE_OU_LINK')
    if path.suffix.casefold() == '.blend':
        # Library append: avoid executing a downloaded scene's scripts/handlers.
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            if len(source.objects) > MAX_OBJECTS:
                raise ValueError('V28_SOURCE_OBJETOS_DEMAIS')
            target.objects = list(source.objects)
        return [o for o in target.objects if o and o.type == 'MESH']
    if path.suffix.casefold() == '.glb':
        bpy.ops.import_scene.gltf(filepath=str(path))
        return [o for o in bpy.data.objects if o.type == 'MESH']
    raise ValueError('V28_FORMATO_NAO_SUPORTADO')


def _fix_material_images(meshes, source_path):
    missing = set()
    materials = {m for obj in meshes for m in obj.data.materials if m}
    for material in materials:
        if not material.use_nodes or not material.node_tree:
            continue
        for node in material.node_tree.nodes:
            image = getattr(node, 'image', None)
            if not image or image.packed_file:
                continue
            raw = image.filepath or ''
            if not raw:
                continue
            if raw.startswith('//'):
                candidate = (source_path.parent / raw[2:]).resolve()
            else:
                candidate = Path(raw).expanduser()
                if not candidate.is_absolute():
                    candidate = (source_path.parent / candidate).resolve()
            if candidate.is_file():
                image.filepath = str(candidate)
            else:
                missing.add(image.name)
    return sorted(missing)[:100]


def _measure(meshes):
    vertices = sum(len(o.data.vertices) for o in meshes)
    faces = sum(len(o.data.polygons) for o in meshes)
    if not vertices or not faces:
        raise ValueError('V28_MODELO_SEM_GEOMETRIA')
    if vertices > MAX_SOURCE_VERTICES or faces > MAX_SOURCE_FACES:
        raise ValueError(f'V28_SOURCE_EXCESSIVA:{vertices}_vertices_{faces}_faces')
    lo = Vector((inf, inf, inf))
    hi = Vector((-inf, -inf, -inf))
    # Transform all source points with the original object matrices. The
    # normalized preview uses ground at z=0, x/y centre at the origin.
    for obj in meshes:
        if obj.data.shape_keys or obj.find_armature() is not None:
            raise ValueError('V28_APENAS_MODELOS_ESTATICOS')
        m = obj.matrix_world
        for v in obj.data.vertices:
            p = m @ v.co
            for axis in range(3):
                lo[axis] = min(lo[axis], p[axis])
                hi[axis] = max(hi[axis], p[axis])
    height = float(hi.z - lo.z)
    if not isfinite(height) or not 1e-6 < height < 1e8:
        raise ValueError('V28_ALTURA_INVALIDA')
    origin = Vector(((lo.x + hi.x)*.5, (lo.y + hi.y)*.5, lo.z))
    return vertices, faces, height, origin


def _save_level(meshes, source_faces, origin, name, budget, output):
    ratio = min(1., budget / source_faces)
    col = bpy.data.collections.new(f'PT_V28_{name}_ASSET_LIBRARY')
    bpy.context.scene.collection.children.link(col)
    result_faces = 0
    result_vertices = 0
    created = []
    try:
        for number, source in enumerate(meshes):
            if not source.data.polygons:
                continue
            raw = source.data.copy()
            raw.transform(Matrix.Translation(-origin) @ source.matrix_world)
            raw.update()
            obj = bpy.data.objects.new(f'PT_V28_{name}_PART_{number:03d}', raw)
            col.objects.link(obj)
            created.append(obj)
            if ratio < .999 and len(raw.polygons) > 20:
                # Decimation only on private copy, preserving source and UVs.
                mod = obj.modifiers.new('PT_V28_GEOMETRY_ONLY_LOD', 'DECIMATE')
                mod.ratio = max(0.00005, ratio)
                depsgraph = bpy.context.evaluated_depsgraph_get()
                depsgraph.update()
                evaluated = obj.evaluated_get(depsgraph)
                reduced = bpy.data.meshes.new_from_object(
                    evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
                obj.modifiers.clear()
                obj.data = reduced
                if raw.users == 0:
                    bpy.data.meshes.remove(raw)
            obj['pt_v28_preview_only'] = True
            result_faces += len(obj.data.polygons)
            result_vertices += len(obj.data.vertices)
        if not result_faces or result_faces > budget * 1.5:
            raise ValueError(f'V28_LOD_NAO_ATINGE_ORCAMENTO:{name}:{result_faces}/{budget}')
        # Only this collection and dependencies get written to the library;
        # other objects, scenes, source meshes and Stage data are not exported.
        bpy.data.libraries.write(str(output / f'{name}.blend'), {col}, compress=True)
        return {'faces': result_faces, 'vertices': result_vertices}
    finally:
        for o in created:
            me = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if me and me.users == 0:
                bpy.data.meshes.remove(me)
        bpy.data.collections.remove(col)


def main():
    options = _args()
    source = options.input.resolve(strict=True)
    output = options.output.resolve(strict=True)
    result = options.result.resolve()
    if result.parent != output or not output.is_dir():
        raise ValueError('V28_OUTPUT_INVALIDO')
    meshes = _read_source(source)
    if not meshes or len(meshes) > MAX_OBJECTS:
        raise ValueError('V28_MALHAS_INVALIDAS')
    source_vertices, source_faces, height, origin = _measure(meshes)
    missing = _fix_material_images(meshes, source)
    levels = {}
    for name, budget in LOD_BUDGETS.items():
        levels[name] = _save_level(meshes, source_faces, origin, name, budget, output)
        print(f'PT_V28_LOD={name} faces={levels[name]["faces"]} '
              f'vertices={levels[name]["vertices"]}', flush=True)
    report = {
        'format': 'PT_ETERVALE_LOD_WORKER_V28',
        'source_vertices': source_vertices, 'source_faces': source_faces,
        'mesh_parts': len(meshes), 'height': height,
        'missing_textures': missing, 'levels': levels,
    }
    result.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print('PT_V28_WORKER=PASS originals_unchanged=true publish=false', flush=True)


if __name__ == '__main__':
    main()
