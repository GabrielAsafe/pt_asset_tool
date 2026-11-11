"""V23 Blender tree workbench — separate *disposable* inspection meshes and GLB preview.

Never writes SMD, modifies original stage vertices, or publishes game assets.
The only persistent output is source-locked .v23_trees.json.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
from bpy.props import CollectionProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector

from pt_asset_tool.stage072_semantic_core import atomic_write_json, source_to_view
from pt_asset_tool.stage072_trees_v23 import (
    TreeFace, build_tree_plan, check_tree_plan, preserve_tree_review, tree_plan_path,
)

CONFIG = {}
PLAN = None
LOCK = False
ISOLATE_COLLECTION = 'PT_V23_ARVORES_INSPECAO_SO_COPIA'
PREVIEW_COLLECTION = 'PT_V23_NOVAS_ARVORES_PREVIEW'
LIB_COLLECTION = 'PT_V23_GLB_BIBLIOTECA_PRIVADA'
MASK_OBJECT = 'PT_V23_STAGE_MASCARADO_SO_PREVIEW'
MAX_PREVIEW_INSTANCES = 25
MAX_GLB_BYTES = 150_000_000
MAX_GLB_VERTICES = 700_000


def _proxies():
    return CONFIG['proxies']() if CONFIG else []


def _v22():
    return CONFIG['v22']() if CONFIG else None


def _plan_path():
    return tree_plan_path(CONFIG['v22_path']())


def _source():
    objs = _proxies()
    if len(objs) != 1:
        raise RuntimeError('V23_NEEDS_ONE_V19_STAGE_PROXY')
    return objs[0]


def _save():
    if PLAN is None:
        return
    original = _source()
    check_tree_plan(PLAN, asset=CONFIG['asset'], source_sha256=CONFIG['sha'],
                    vertex_count=len(original.data.vertices), face_count=len(original.data.polygons))
    atomic_write_json(_plan_path(), PLAN)


def _collection(name, *, linked=True):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if linked and col not in bpy.context.scene.collection.children[:]:
        bpy.context.scene.collection.children.link(col)
    return col


def _remove_collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        return
    for obj in list(col.objects):
        data = obj.data if obj.type == 'MESH' else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)
    bpy.data.collections.remove(col)


def _tree_faces():
    original = _source()
    me, mw = original.data, original.matrix_world.copy()
    normal_matrix = mw.to_3x3().inverted_safe().transposed()
    mats = [slot.material.name if slot.material else 'NO_MATERIAL' for slot in original.material_slots]
    result = []
    for poly in me.polygons:
        vs = [mw @ me.vertices[vi].co for vi in poly.vertices]
        if len(vs) < 3:
            continue
        lo = tuple(min(v[k] for v in vs) for k in range(3))
        hi = tuple(max(v[k] for v in vs) for k in range(3))
        c = tuple((mw @ poly.center)[k] for k in range(3))
        n = (normal_matrix @ poly.normal).normalized()
        area = sum((vs[j]-vs[0]).cross(vs[j+1]-vs[0]).length/2
                   for j in range(1, len(vs)-1))
        material = mats[poly.material_index] if poly.material_index < len(mats) else 'NO_MATERIAL'
        result.append(TreeFace(poly.index, material, c, lo, hi, float(n.z), area,
                               tuple(int(x) for x in poly.vertices)))
    return result


def _refresh_ui(context):
    global LOCK
    LOCK = True
    try:
        scene = context.scene
        previous = scene.pt_v23_active
        scene.pt_v23_items.clear()
        for t in PLAN['trees'] if PLAN else []:
            item = scene.pt_v23_items.add()
            item.tree_id = t['id']
            item.name = f"{t['status'][:1]} Árvore · {len(t['foliage_faces'])}+{len(t['trunk_faces'])} faces"
            item.status = t['status']
            item.completion = t['completion']
        scene.pt_v23_active = min(previous, max(0,len(scene.pt_v23_items)-1))
    finally:
        LOCK = False
    _focus_selected(context)


def _selected(context):
    if PLAN is None:
        return None
    i = context.scene.pt_v23_active
    return PLAN['trees'][i] if 0 <= i < len(PLAN['trees']) else None


def _focus_selected(context):
    col = bpy.data.collections.get(ISOLATE_COLLECTION)
    if col is None:
        return
    current = _selected(context)
    current_id = current['id'] if current else ''
    for ob in col.objects:
        is_active = ob.get('pt_v23_tree_id') == current_id
        ob.hide_set(not is_active)
        ob.select_set(is_active)
    if current_id:
        ob = next((o for o in col.objects if o.get('pt_v23_tree_id')==current_id),None)
        if ob:
            context.view_layer.objects.active = ob


def _active_update(self, context):
    if not LOCK:
        _focus_selected(context)


class PT_V23TreeRow(bpy.types.PropertyGroup):
    tree_id: StringProperty()
    status: StringProperty()
    completion: StringProperty()


def _create_inspection_mesh(original, face_ids, name):
    """Extract a mesh from a *single source object's* face IDs; no source splitting."""
    verts = []
    polys = []
    remap = {}
    matids = []
    src_loops = []
    src_verts = []
    for face_id in sorted(set(face_ids)):
        if not 0 <= face_id < len(original.data.polygons):
            raise ValueError('TREE_FACE_INDEX_OUT_OF_RANGE')
        f = original.data.polygons[face_id]
        polygon = []
        for vi in f.vertices:
            if vi not in remap:
                remap[vi] = len(verts)
                verts.append(tuple(original.data.vertices[vi].co))
                src_verts.append(vi)
            polygon.append(remap[vi])
        if len(polygon) >= 3:
            polys.append(polygon)
            matids.append(f.material_index)
            src_loops.extend(f.loop_indices)
    if not polys:
        return None
    mesh = bpy.data.meshes.new(name+'_MESH')
    mesh.from_pydata(verts, [], polys)
    for mat in original.data.materials:
        mesh.materials.append(mat)
    mesh.update()
    for i,idx in enumerate(matids):
        mesh.polygons[i].material_index = idx
    if len(mesh.loops) != len(src_loops):
        raise RuntimeError('V23_ISOLATION_LOOP_MAPPING_MISMATCH')
    # Restore every UV layer of this visual copy. Original SMD texlinks and
    # the original proxy mesh remain completely untouched.
    for src_layer in original.data.uv_layers:
        dst_layer = mesh.uv_layers.new(name=src_layer.name)
        for out_idx, in_idx in enumerate(src_loops):
            dst_layer.data[out_idx].uv = src_layer.data[in_idx].uv
    for color in original.data.color_attributes:
        if color.domain not in {'CORNER','POINT'} or color.data_type not in {'BYTE_COLOR','FLOAT_COLOR'}:
            continue
        dst = mesh.color_attributes.new(name=color.name, domain=color.domain, type=color.data_type)
        indices = src_loops if color.domain == 'CORNER' else src_verts
        for out_idx,in_idx in enumerate(indices):
            dst.data[out_idx].color = color.data[in_idx].color
    ob = bpy.data.objects.new(name, mesh)
    ob.matrix_world = original.matrix_world.copy()
    ob.display_type = 'TEXTURED'
    ob.show_in_front = True
    ob.hide_render = True
    ob.color = (0.17, 0.9, 0.4, 1.0)
    ob['pt_v23_inspection_only'] = True
    return ob


class PT_OT_V23Build(bpy.types.Operator):
    bl_idname = 'pt_semantic.v23_analyze_trees'
    bl_label = 'Reconstruir árvores'
    bl_description = 'Associa copas V22 a troncos prováveis, sem modificar SMD ou aprovadas anteriores'

    def execute(self, context):
        global PLAN
        try:
            doc = _v22()
            if doc is None:
                raise ValueError('PRIMEIRO_DETETAR_FOLHAGEM_NA_V22')
            original = _source()
            faces = _tree_faces()
            scene = context.scene
            center = tuple(scene['pt_stage072_source_bounds_center'])
            scale = float(scene['pt_stage072_view_scale'])
            new = build_tree_plan(v22=doc, faces=faces, center_xyz=center, view_scale=scale)
            # V23.1: do not overwrite a useful 103-tree review plan with an
            # accidental zero-tree plan (e.g., V22 was redetected without seeds).
            if not new['trees']:
                if PLAN is not None and PLAN.get('trees'):
                    raise ValueError('V23_EMPTY_RESULT_PRESERVED_EXISTING_TREES')
                raise ValueError('V23_NO_TREES_NO_SAVE_RESTORE_V22_PROPOSALS')
            if PLAN is not None:
                new = preserve_tree_review(new, PLAN)
            PLAN = new
            _save()
            _refresh_ui(context)
            self.report({'INFO'}, f"V23: {new['counts']['trees']} árvores, {new['counts']['with_trunk']} troncos candidatos")
            print(f"PT_V23_TREES=PASS trees={new['counts']['trees']} "
                  f"trunk_candidates={new['counts']['with_trunk']} "
                  f"leaves_only={new['counts']['leaves_only']} path={_plan_path()}",flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'V23: {type(exc).__name__}: {exc}')
            print(f'PT_V23_TREES=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V23Separate(bpy.types.Operator):
    bl_idname = 'pt_semantic.v23_separate_trees'
    bl_label = 'Criar objetos de inspeção'
    bl_description = 'Cada árvore proposta vira um objeto separado, WIRE e só na cópia temporária'

    def execute(self, context):
        try:
            if PLAN is None:
                raise ValueError('ANALISAR_ARVORES_PRIMEIRO')
            original = _source()
            _remove_collection(ISOLATE_COLLECTION)
            col = _collection(ISOLATE_COLLECTION)
            n = 0
            for t in PLAN['trees']:
                ob = _create_inspection_mesh(original, t['faces'], 'PT_ARVORE_V23_'+t['id'])
                if ob is None:
                    continue
                col.objects.link(ob)
                ob['pt_v23_tree_id'] = t['id']
                n += 1
            _focus_selected(context)
            self.report({'INFO'}, f'{n} objetos de árvore na coleção {ISOLATE_COLLECTION}')
            print(f'PT_V23_SEPARATE=PASS objects={n} source_mesh_unchanged=true',flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'V23: {exc}')
            return {'CANCELLED'}


class PT_OT_V23Decide(bpy.types.Operator):
    bl_idname = 'pt_semantic.v23_decide'
    bl_label = 'Rever árvore'
    decision: StringProperty(default='PENDING')

    def execute(self, context):
        tree = _selected(context)
        if tree is None or self.decision not in {'PENDING','APPROVED','REJECTED','NEEDS_REVIEW'}:
            return {'CANCELLED'}
        tree['status'] = self.decision
        _save()
        _refresh_ui(context)
        self.report({'INFO'}, 'Estado guardado apenas na proposta V23')
        return {'FINISHED'}


def _clear_preview():
    _remove_collection(PREVIEW_COLLECTION)
    _remove_collection(LIB_COLLECTION)
    obj = bpy.data.objects.get(MASK_OBJECT)
    if obj is not None:
        me = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    for original in _proxies():
        original.hide_set(False)


class PT_OT_V23Clear(bpy.types.Operator):
    bl_idname = 'pt_semantic.v23_clear_preview'
    bl_label = 'Restaurar visual original'
    def execute(self, context):
        _clear_preview()
        self.report({'INFO'}, 'Pré-visualização removida; Stage original restaurado')
        return {'FINISHED'}


def _import_glb_library(path: Path):
    if not path.is_file() or path.suffix.lower() != '.glb' or path.is_symlink():
        raise ValueError('ESCOLHER_FICHEIRO_GLB_LOCAL_VALIDO')
    if path.stat().st_size > MAX_GLB_BYTES:
        raise ValueError('GLB_MUITO_GRANDE')
    if not hasattr(bpy.ops.import_scene, 'gltf'):
        raise RuntimeError('BLENDER_GLTF_IMPORT_NAO_DISPONIVEL')
    existing = set(bpy.data.objects[:])
    imported = []
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
        imported = list(set(bpy.data.objects[:]) - existing)
        source_meshes = [o for o in imported if o.type == 'MESH']
        if not source_meshes:
            raise ValueError('GLB_SEM_MALHAS')
        if len(source_meshes) > 128 or sum(len(o.data.vertices) for o in source_meshes) > MAX_GLB_VERTICES:
            raise ValueError('GLB_COMPLEXIDADE_EXCESSIVA')
        if any(o.find_armature() is not None or o.data.shape_keys for o in source_meshes):
            raise ValueError('V23_APENAS_GLB_ESTATICO_SEM_ARMATURE_OU_SHAPE_KEYS')
        # Bake world transform into independent mesh copies. This handles GLB
        # parent hierarchies without moving any mesh of the original Stage.
        all_positions = [o.matrix_world @ v.co for o in source_meshes for v in o.data.vertices]
        if not all_positions:
            raise ValueError('GLB_SEM_VERTICES')
        lo = [min(p[k] for p in all_positions) for k in range(3)]
        hi = [max(p[k] for p in all_positions) for k in range(3)]
        height = hi[2]-lo[2]
        if height < 1.e-6:
            raise ValueError('GLB_ALTURA_NULA')
        origin = Vector(((lo[0]+hi[0])/2, (lo[1]+hi[1])/2, lo[2]))
        library = _collection(LIB_COLLECTION, linked=False)
        for i,o in enumerate(source_meshes):
            mesh = o.data.copy()
            mesh.transform(Matrix.Translation(-origin) @ o.matrix_world)
            mesh.update()
            item = bpy.data.objects.new(f'PT_V23_GLB_PART_{i:03d}', mesh)
            library.objects.link(item)
            item['pt_v23_library_only'] = True
        return library, height
    finally:
        # Imported originals would otherwise sit in the viewport, unrelated to
        # any individual tree. Keep only normalized private mesh copies.
        for ob in imported or list(set(bpy.data.objects[:]) - existing):
            if bpy.data.objects.get(ob.name) is not None:
                bpy.data.objects.remove(ob, do_unlink=True)


def _mask_preview(original, remove_face_ids):
    import bmesh
    new_mesh = original.data.copy()
    bm = bmesh.new()
    try:
        bm.from_mesh(new_mesh)
        bm.faces.ensure_lookup_table()
        if any(i < 0 or i >= len(bm.faces) for i in remove_face_ids):
            raise ValueError('MASK_FACES_INVALIDAS')
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(remove_face_ids)], context='FACES')
        bm.to_mesh(new_mesh)
        new_mesh.update()
    finally:
        bm.free()
    duplicate = bpy.data.objects.new(MASK_OBJECT, new_mesh)
    context_scene = bpy.context.scene
    context_scene.collection.objects.link(duplicate)
    duplicate.matrix_world = original.matrix_world.copy()
    duplicate['pt_v23_mask_preview_only'] = True
    original.hide_set(True)


class PT_OT_V23Preview(bpy.types.Operator):
    bl_idname = 'pt_semantic.v23_preview_glb'
    bl_label = 'Pré-visualizar árvore GLB'
    bl_description = 'Instâncias GLB e mascaramento apenas VISUAL da malha temporária; jogo intacto'
    scope: StringProperty(default='SELECTED')

    def execute(self, context):
        try:
            if PLAN is None:
                raise ValueError('PRIMEIRO_RECONSTRUIR_ARVORES')
            scene = context.scene
            path = Path(bpy.path.abspath(scene.pt_v23_glb)).expanduser().resolve()
            if self.scope == 'SELECTED':
                sel = _selected(context)
                targets = [sel] if sel and sel['status'] != 'REJECTED' else []
                if not targets:
                    raise ValueError('SELECIONAR_UMA_ARVORE_NAO_REJEITADA')
            elif self.scope == 'APPROVED':
                targets = [t for t in PLAN['trees'] if t['status'] == 'APPROVED']
                if not targets:
                    raise ValueError('PREVIA_APROVADAS_REQUER_APROVAR_ARVORES_NA_LISTA')
            else:
                raise ValueError('ESCOPO_DESCONHECIDO')
            if len(targets) > MAX_PREVIEW_INSTANCES:
                raise ValueError(f'MAXIMO_{MAX_PREVIEW_INSTANCES}_ARVORES_POR_PREVIEW')
            # Validate all claims before hiding anything. Approvals only affect
            # local preview, not Stage collision or any future publishing pipeline.
            seen=set()
            for t in targets:
                if not set(t['faces']).isdisjoint(seen):
                    raise ValueError('PREVIEW_FACES_SOBREPOSTAS_REVER_ANTES')
                seen.update(t['faces'])
            _clear_preview()
            try:
                lib,height = _import_glb_library(path)
                col = _collection(PREVIEW_COLLECTION)
                center = tuple(scene['pt_stage072_source_bounds_center'])
                scale = float(scene['pt_stage072_view_scale'])
                for idx,t in enumerate(targets):
                    off = t.get('offset_game',[0.,0.,0.])
                    p = [t['anchor_game'][i] + off[i] for i in range(3)]
                    position = source_to_view(tuple(p), center, scale)
                    instance = bpy.data.objects.new(f'PT_V23_NOVA_ARVORE_{idx+1:03d}_{t["id"]}', None)
                    col.objects.link(instance)
                    instance.instance_type = 'COLLECTION'
                    instance.instance_collection = lib
                    instance.location = position
                    instance.rotation_euler[2] = math.radians(-float(t.get('yaw_degrees',0.)))
                    target_height = max(.5, float(t.get('height_view') or 2.0))
                    factor = target_height / height * float(t.get('asset_scale',1.)) * scene.pt_v23_size_factor
                    instance.scale = (factor,factor,factor)
                    instance['pt_v23_tree_id']=t['id']
                    instance['pt_v23_preview_only']=True
                if scene.pt_v23_mask_original:
                    _mask_preview(_source(), seen)
            except Exception:
                _clear_preview()
                raise
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024), b''):
                    digest.update(chunk)
            print(f'PT_V23_PREVIEW=PASS instances={len(targets)} hide_old={scene.pt_v23_mask_original} '
                  f'glb_sha256={digest.hexdigest()} game_assets_modified=false',flush=True)
            self.report({'INFO'}, f'{len(targets)} árvores GLB no preview; não publica no jogo')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'V23: {type(exc).__name__}: {exc}')
            print(f'PT_V23_PREVIEW=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_PT_V23Panel(bpy.types.Panel):
    bl_label = 'V23 · Árvores completas e GLB'
    bl_idname = 'PT_PT_ETERVALE_V23_TREES'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Etervale'
    bl_parent_id = 'PT_PT_ETERVALE_SEMANTIC_V21'

    def draw(self, context):
        lay = self.layout
        scene = context.scene
        lay.label(text='Uma árvore = faces, não slot de material')
        lay.operator('pt_semantic.v23_analyze_trees',text='1. Reconstruir árvores',icon='OUTLINER_OB_MESH')
        if PLAN is None:
            lay.label(text='Executar primeiro V22 e reconstruir')
            return
        approved = sum(t['status'] == 'APPROVED' for t in PLAN['trees'])
        lay.label(text=f"Árvores: {PLAN['counts']['trees']} · troncos: {PLAN['counts']['with_trunk']}")
        lay.label(text=f'Aprovadas: {approved} · proposta é apenas análise')
        lay.operator('pt_semantic.v23_separate_trees',text='2. Criar objetos no Outliner',icon='OUTLINER_COLLECTION')
        lay.template_list('UI_UL_list','PT_V23_LIST',scene,'pt_v23_items',scene,'pt_v23_active',rows=5)
        t = _selected(context)
        if t:
            b=lay.box()
            b.label(text=f"{len(t['foliage_faces'])} folhas · {len(t['trunk_faces'])} tronco")
            b.label(text=t['completion'][:32])
            b.label(text=f"Altura proposta: {float(t.get('height_view') or 0.):.2f}")
            r=b.row(align=True)
            r.operator('pt_semantic.v23_decide',text='Aprovar').decision='APPROVED'
            r.operator('pt_semantic.v23_decide',text='Rever').decision='NEEDS_REVIEW'
            b.operator('pt_semantic.v23_decide',text='Rejeitar').decision='REJECTED'
        lay.separator()
        lay.label(text='3. Escolher árvore 3D local (.glb)')
        lay.prop(scene,'pt_v23_glb',text='Modelo GLB')
        lay.prop(scene,'pt_v23_size_factor',text='Fator tamanho')
        lay.prop(scene,'pt_v23_mask_original',text='Ocultar faces antigas na cópia')
        row = lay.row()
        row.enabled = bool(t and t['status'] != 'REJECTED')
        row.operator('pt_semantic.v23_preview_glb',text='Prévia árvore selecionada',icon='MESH_DATA').scope='SELECTED'
        row = lay.row()
        row.enabled = approved > 0
        row.operator('pt_semantic.v23_preview_glb',text=f'Prévia {approved} aprovadas (máx. 25)',icon='OUTLINER_COLLECTION').scope='APPROVED'
        lay.operator('pt_semantic.v23_clear_preview',text='Restaurar original',icon='LOOP_BACK')
        lay.label(text='Preview apenas: sem exportação para jogo')
        lay.label(text='WALL/colisão ficam intactos')


CLASSES = (PT_V23TreeRow, PT_OT_V23Build, PT_OT_V23Separate, PT_OT_V23Decide,
           PT_OT_V23Preview, PT_OT_V23Clear, PT_PT_V23Panel)


def configure(*, asset, sha, v22_provider, v22_path_provider, proxies_provider):
    global CONFIG, PLAN
    CONFIG = {'asset':asset, 'sha':sha, 'v22':v22_provider,
              'v22_path':v22_path_provider, 'proxies':proxies_provider}
    PLAN = None
    orig = _source()
    p = _plan_path()
    if p.is_file():
        plan = json.loads(p.read_text(encoding='utf-8'))
        check_tree_plan(plan, asset=asset, source_sha256=sha,
                        vertex_count=len(orig.data.vertices), face_count=len(orig.data.polygons))
        PLAN = plan
    scene = bpy.context.scene
    if not hasattr(bpy.types.Scene, 'pt_v23_items'):
        bpy.types.Scene.pt_v23_items = CollectionProperty(type=PT_V23TreeRow)
        bpy.types.Scene.pt_v23_active = IntProperty(default=0, min=0, update=_active_update)
        bpy.types.Scene.pt_v23_glb = StringProperty(name='Modelo GLB', subtype='FILE_PATH')
        bpy.types.Scene.pt_v23_size_factor = FloatProperty(name='Fator escala',default=1.,min=.1,max=8.)
        bpy.types.Scene.pt_v23_mask_original = bpy.props.BoolProperty(name='Esconder original no preview',default=False)
    _refresh_ui(bpy.context)
    print(f'PT_V23=READY asset={asset} trees={len(PLAN["trees"]) if PLAN else 0} '
          f'output={p} source_unchanged=true',flush=True)
