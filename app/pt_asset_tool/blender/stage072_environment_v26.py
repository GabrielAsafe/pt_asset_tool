"""V26 simplified Blender workbench for Stage072 forest replacement.

One visible panel, one proxy, one selected tree and a *private* asset preview.
All game-space metadata and V22–V25 decisions remain in their own JSON files.
This script intentionally does not implement SMD export or runtime deployment.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector

from pt_asset_tool.environment_library_v26 import model_entries, prepare_model
from pt_asset_tool.environment_lod_v27 import lod_plan, TARGET_PREVIEW_VERTICES
from pt_asset_tool.environment_lods_v28 import (
    ROOT_REL as V28_CACHE_REL, MAX_SCENE_INSTANCES, validate_prepared, sha256_file,
)
from pt_asset_tool.stage072_semantic_core import atomic_write_json
from pt_asset_tool.environment_batch_v29 import plan_tree_instances, preview_record
from pt_asset_tool.environment_batch_v30 import (
    plan_complete_preview, preview_record as v30_preview_record,
)
from pt_asset_tool.blender import environment_wall_probe_v30 as wall_v30
from pt_asset_tool.stage072_tree_review_v25 import virtual_groups
from pt_asset_tool.blender import stage072_tree_v23 as v23
from pt_asset_tool.blender import stage072_tree_group_v24 as v24
from pt_asset_tool.blender import stage072_tree_review_v25 as v25

SELECT_COLLECTION = 'PT_V26_ARVORE_EM_INSPECAO'
PREVIEW_COLLECTION = 'PT_V26_MODELO_COMPARACAO'
LIB_COLLECTION = 'PT_V26_BIBLIOTECA_PRIVADA'
BATCH_COLLECTION = 'PT_V28_INSTANCIAS_APROVADAS'
V29_BATCH_COLLECTION = 'PT_V29_ARVORES_LOD0_TODAS_PREVIEW'
V30_BATCH_COLLECTION = 'PT_V30_COBERTURA_COMPLETA_SO_PREVIEW'
V29_MASK_MOD = 'PT_V29_ESCONDER_ARVORES_MODIFIER'
V29_MASK_ATTR = 'pt_v29_arvores_antigas_mask'
V29_MASK_NODE = 'PT_V29_APENAS_PREVIEW_NODES'
PREPARED_PREFIX = 'PT_V28_LIBRARY_'
SESSION = None
GROUPS = []
DECISIONS = {}
MODEL_ENUM_ITEMS = []
LOCK = False
MAX_VERTICES = 2_500_000  # bounded *input* mesh; previews use private decimated LOD
MAX_OBJECTS = 256


def _root():
    return Path(__file__).resolve().parents[3]


def _library_root():
    return _root() / 'AssetsForAutomaticSubstitution'


def _cache_root():
    return _root() / 'app/pt_build/etervale/environment_v26/asset_cache'


def _state_path():
    # lives alongside V24 without modifying or migrating V24/V25.
    return v24._plan_path().with_suffix('.v26_environment.json')


def _assert_native_hidden():
    v25._hide_native_stage_sources()


def _get_groups():
    if v24.PLAN is None:
        return []  # V27 material classification works on maps without V24 trees
    if v25.PLAN:
        groups = virtual_groups(v25.PLAN, v24=v24.PLAN)
    else:
        groups = v24.PLAN['groups']
    return [g for g in groups if g.get('trunk_faces') and g.get('category') == 'ARVORE']


def _model_items(self, context):
    # Blender may keep references to string buffers used by dynamic Enum items.
    # Store the tuples for the lifetime of the UI rather than returning fresh ones.
    return MODEL_ENUM_ITEMS


def _selected(context):
    if not GROUPS:
        return None
    i = context.scene.pt_v26_active
    return GROUPS[i] if 0 <= i < len(GROUPS) else None


def _load_state():
    path = _state_path()
    sha = v23.CONFIG['sha']
    if path.is_file():
        doc = json.loads(path.read_text(encoding='utf-8'))
        if (doc.get('format') != 'PT_ETERVALE_ENVIRONMENT_V26' or
            doc.get('source_sha256') != sha or doc.get('asset') != v23.CONFIG['asset'] or
            doc.get('publish_enabled') is not False):
            raise ValueError('V26_ESTADO_INCOMPATIVEL_PRESERVADO')
        if not isinstance(doc.get('approvals'), dict):
            raise ValueError('V26_APROVACOES_INVALIDAS')
        return doc
    return {'format':'PT_ETERVALE_ENVIRONMENT_V26', 'version':1,
            'source_sha256':sha, 'asset':v23.CONFIG['asset'],
            'publish_enabled':False, 'game_assets_modified':False,
            'approvals':{}}


def _save():
    if SESSION is not None:
        atomic_write_json(_state_path(), SESSION)


def _clear_col(name):
    v23._remove_collection(name)


def _clear_v28_libs():
    for col in list(bpy.data.collections):
        if col.name.startswith(PREPARED_PREFIX):
            v23._remove_collection(col.name)


def _remove_visuals():
    _clear_v29_preview()
    _clear_col(SELECT_COLLECTION)
    _clear_col(PREVIEW_COLLECTION)
    _clear_col(BATCH_COLLECTION)
    _clear_col(LIB_COLLECTION)
    _clear_v28_libs()
    original = v23._source()
    original.hide_set(False)
    _assert_native_hidden()


def _show_selection(group, isolate=False):
    _clear_v29_preview()
    _clear_col(SELECT_COLLECTION)
    original = v23._source()
    original.hide_set(not not isolate)
    _assert_native_hidden()
    col = v23._collection(SELECT_COLLECTION)
    ob = v23._create_inspection_mesh(original, group['faces'],
            f'PT_V26_SELECAO_{group["id"]}')
    if ob is None:
        raise ValueError('V26_ARVORE_SEM_FACES')
    col.objects.link(ob)
    ob.show_wire = True
    ob.show_all_edges = True
    ob.show_in_front = True
    ob['pt_v26_source_group_id'] = group['id']
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    return ob


def _refresh_rows(context):
    global LOCK
    LOCK = True
    try:
        sc = context.scene
        old = sc.pt_v26_active
        sc.pt_v26_rows.clear()
        for group in GROUPS:
            row = sc.pt_v26_rows.add()
            row.group_id = group['id']
            approved = SESSION['approvals'].get(group['id'], {}) if SESSION else {}
            marker = 'OK' if approved.get('approved') else '·'
            row.name = f'{marker} Árvore {group["id"][:7]} · {len(group["faces"])} faces'
        sc.pt_v26_active = min(old, max(0, len(GROUPS)-1))
    finally:
        LOCK = False


def _on_selected(self, context):
    # No 99 full object copies; only one inspected tree when user clicks Isolar.
    if not LOCK and bpy.data.collections.get(SELECT_COLLECTION):
        _clear_col(SELECT_COLLECTION)
        v23._source().hide_set(False)
        _assert_native_hidden()


class PT_V26TreeRow(bpy.types.PropertyGroup):
    group_id: StringProperty()


class PT_OT_V26Isolate(bpy.types.Operator):
    bl_idname = 'pt_env.v26_isolate'
    bl_label = 'Isolar árvore'
    bl_description = 'Cria UMA malha de inspeção a partir das faces aprovadas pelo detetor, sem copiar todo o Stage'

    def execute(self, context):
        try:
            g = _selected(context)
            if not g:
                raise ValueError('SELECIONAR_ARVORE')
            _show_selection(g, isolate=True)
            self.report({'INFO'}, 'Uma árvore isolada; mapa original preservado')
            print(f'PT_V26_ISOLATE=PASS tree={g["id"]} faces={len(g["faces"])} native_unchanged=true', flush=True)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            print(f'PT_V26_ISOLATE=FAIL {type(e).__name__}:{e}', flush=True)
            return {'CANCELLED'}


def _load_blend_library(blend_path, *, collection_name=LIB_COLLECTION, already_prepared=False):
    """Append data privately, then build a bounded *preview-only* LOD.

    The downloaded blend.zip and extracted source blend are read-only. Mesh
    decimation is evaluated only on our disposable Blender mesh copy. For
    exceptionally complex scenes, refuse with a clear error rather than risk
    exhausting Blender memory. Never touch the Stage proxy or game source.
    """
    with bpy.data.libraries.load(str(blend_path), link=False) as (src, dst):
        if len(src.objects) > MAX_OBJECTS:
            raise ValueError('MODELO_MUITOS_OBJETOS')
        dst.objects = list(src.objects)
    loaded = [o for o in dst.objects if o is not None]
    try:
        meshes = [o for o in loaded if o.type == 'MESH' and o.data and len(o.data.vertices)]
        if not meshes:
            raise ValueError('MODELO_BLEND_SEM_MALHAS')
        if any(o.find_armature() or o.data.shape_keys for o in meshes):
            raise ValueError('MODELO_ANIMADO_NAO_SUPORTADO_NA_V27')
        vertices = sum(len(o.data.vertices) for o in meshes)
        faces = sum(len(o.data.polygons) for o in meshes)
        # A V28.1 já reduziu esta malha em background. Não a decimar
        # novamente ao carregar o LOD0 de qualidade alta.
        settings = {'simplify':False, 'ratio':1.0} if already_prepared else lod_plan(vertices, faces)
        # Streaming extrema: no allocation of millions of transformed points.
        lo = Vector((float('inf'),)*3)
        hi = Vector((float('-inf'),)*3)
        for source in meshes:
            mw = source.matrix_world
            for vertex in source.data.vertices:
                point = mw @ vertex.co
                for axis in range(3):
                    lo[axis] = min(lo[axis], point[axis])
                    hi[axis] = max(hi[axis], point[axis])
        height = float(hi.z - lo.z)
        if height <= 1e-6:
            raise ValueError('MODELO_SEM_ALTURA')
        origin = Vector(((lo.x + hi.x)/2., (lo.y + hi.y)/2., lo.z))
        col = v23._collection(collection_name, linked=False)
        created = []
        try:
            for i, source in enumerate(meshes):
                if not len(source.data.polygons):
                    continue
                raw = source.data.copy()
                raw.transform(Matrix.Translation(-origin) @ source.matrix_world)
                raw.update()
                if settings['simplify'] and len(raw.polygons) > 20:
                    temp = bpy.data.objects.new(f'PT_V27_LOD_TEMP_{i:03}', raw)
                    col.objects.link(temp)
                    try:
                        mod = temp.modifiers.new('PT_V27_PREVIEW_ONLY_DECIMATE','DECIMATE')
                        mod.ratio = max(.01, settings['ratio'])
                        # evaluated mesh avoids bpy.ops, active selection, and
                        # applying modifiers to downloaded mesh data.
                        context = bpy.context.evaluated_depsgraph_get()
                        evaluated = temp.evaluated_get(context)
                        reduced = bpy.data.meshes.new_from_object(
                            evaluated, preserve_all_data_layers=True, depsgraph=context)
                        if not len(reduced.materials):
                            for mat in raw.materials:
                                reduced.materials.append(mat)
                    finally:
                        bpy.data.objects.remove(temp, do_unlink=True)
                        if raw.users == 0:
                            bpy.data.meshes.remove(raw)
                    raw = reduced
                obj = bpy.data.objects.new(f'PT_V26_LIBRARY_PART_{i:03}', raw)
                col.objects.link(obj)
                obj['pt_v26_library_only'] = True
                created.append(obj)
            out_vertices = sum(len(o.data.vertices) for o in created)
            if out_vertices > TARGET_PREVIEW_VERTICES * 1.65:
                raise ValueError(f'MODELO_LOD_AINDA_PESADO:{out_vertices}_vertices')
            missing_images = []
            mats = {mat for obj in created for mat in obj.data.materials if mat}
            for mat in mats:
                if not mat.use_nodes or not mat.node_tree:
                    continue
                for node in mat.node_tree.nodes:
                    img = getattr(node, 'image', None)
                    if img is None or img.packed_file:
                        continue
                    raw_path = img.filepath
                    if not raw_path:
                        continue
                    candidate = Path(raw_path[2:]) if raw_path.startswith('//') else Path(raw_path)
                    if not candidate.is_absolute():
                        candidate = blend_path.parent / candidate
                    if candidate.is_file():
                        img.filepath = str(candidate)
                    else:
                        missing_images.append(img.name)
            if missing_images:
                print(f'PT_V27_TEXTURES=REVIEW missing={sorted(set(missing_images))[:12]}', flush=True)
            print(f'PT_V27_MODEL_LOD=PASS input_vertices={vertices} output_vertices={out_vertices} '
                  f'ratio={settings["ratio"]:.5f} preview_only=true', flush=True)
            return col, height
        except Exception:
            v23._remove_collection(collection_name)
            raise
    finally:
        for obj in loaded:
            if bpy.data.objects.get(obj.name) is obj:
                bpy.data.objects.remove(obj, do_unlink=True)


def _loaded_prepared(name, lod, *, remove_old=False):
    """Never append multi-million-vertex sources in the interactive viewport."""
    models = {e.name:e for e in model_entries(_library_root())}
    if name not in models:
        raise ValueError('V28_MODELO_NAO_E_ARVORE')
    chosen = Path(models[name].path)
    source_path, metadata = validate_prepared(_root() / V28_CACHE_REL, chosen, lod)
    if remove_old:
        _clear_v28_libs()
    lib_name = PREPARED_PREFIX + metadata['source_sha256'][:14] + '_' + lod
    existing = bpy.data.collections.get(lib_name)
    if existing:
        return existing, float(metadata['height'])
    return _load_blend_library(source_path, collection_name=lib_name, already_prepared=True)


def _instance(group, collection, height, scale_factor, *, output_col, asset, lod):
    if height <= 0:
        raise ValueError('V28_ALTURA_MODELO_INVALIDA')
    ob = bpy.data.objects.new(f'PT_V28_NOVA_ARVORE_{group["id"]}', None)
    output_col.objects.link(ob)
    ob.instance_type = 'COLLECTION'
    ob.instance_collection = collection
    ob.location = tuple(group['anchor_view'])
    target_height = max(.4, float(group.get('height_view') or 1.))
    scaling = target_height / height * float(scale_factor)
    ob.scale = (scaling,) * 3
    ob['pt_v26_preview_only'] = True
    ob['pt_v26_group_id'] = group['id']
    ob['pt_v28_asset_name'] = asset
    ob['pt_v28_lod'] = lod
    return ob


def _preview_for(group, asset, *, lod, scale_factor):
    _clear_v29_preview()
    _clear_col(PREVIEW_COLLECTION)
    _clear_col(BATCH_COLLECTION)
    # Do not mutate a loaded collection that may be referenced by instances.
    _clear_v28_libs()
    library, height = _loaded_prepared(asset, lod)
    col = v23._collection(PREVIEW_COLLECTION)
    return _instance(group, library, height, scale_factor, output_col=col,
                     asset=asset, lod=lod)


class PT_OT_V26Preview(bpy.types.Operator):
    bl_idname = 'pt_env.v26_preview'
    bl_label = 'Pré-visualizar substituição'
    bl_description = 'Carrega o LOD previamente preparado em background; não abre arquivos pesados na cena'

    def execute(self, context):
        try:
            g = _selected(context)
            if not g:
                raise ValueError('SELECIONAR_ARVORE')
            name = context.scene.pt_v26_model
            entries = {e.name:e for e in model_entries(_library_root())}
            if name not in entries:
                raise ValueError('MODELO_DE_ARVORE_NAO_ENCONTRADO_NA_BIBLIOTECA')
            lod = context.scene.pt_v28_lod
            _preview_for(g, name, lod=lod, scale_factor=float(context.scene.pt_v26_scale))
            v23._source().hide_set(False)
            _clear_col(SELECT_COLLECTION)
            _assert_native_hidden()
            SESSION['last_model'] = name
            _save()
            print(f'PT_V28_PREVIEW=PASS group={g["id"]} model={name} lod={lod} '
                  'source_unchanged=true publish=false', flush=True)
            self.report({'INFO'}, 'Modelo colocado na base proposta; compara com a árvore original')
            return {'FINISHED'}
        except Exception as e:
            _clear_col(PREVIEW_COLLECTION)
            _clear_v28_libs()
            self.report({'ERROR'}, str(e))
            print(f'PT_V26_PREVIEW=FAIL {type(e).__name__}:{e}', flush=True)
            return {'CANCELLED'}


class PT_OT_V26Approve(bpy.types.Operator):
    bl_idname = 'pt_env.v26_approve'
    bl_label = 'Aprovar esta substituição'
    bl_description = 'Regista uma decisão de preview no JSON privado, NÃO modifica nem exporta o Stage'

    def execute(self, context):
        group = _selected(context)
        if not group:
            return {'CANCELLED'}
        preview = bpy.data.collections.get(PREVIEW_COLLECTION)
        chosen = context.scene.pt_v26_model
        lod = context.scene.pt_v28_lod
        if preview is None or not any(
                o.get('pt_v26_group_id') == group['id'] and
                o.get('pt_v28_asset_name') == chosen and o.get('pt_v28_lod') == lod
                for o in preview.objects):
            self.report({'ERROR'}, 'Pré-visualiza primeiro esta árvore com o modelo e LOD selecionados')
            return {'CANCELLED'}
        digest = hashlib.sha256()
        with (_library_root()/chosen).open('rb') as model_stream:
            for chunk in iter(lambda: model_stream.read(1024*1024), b''):
                digest.update(chunk)
        SESSION['approvals'][group['id']] = {
            'approved':True, 'asset_archive':chosen,
            'asset_sha256':digest.hexdigest(),
            'scale_factor':float(context.scene.pt_v26_scale),
            'lod':lod,
            'source_face_count':len(group['faces']),
            'runtime_certified':False,
        }
        _save()
        _refresh_rows(context)
        self.report({'INFO'}, 'Aprovada apenas a proposta visual; jogo não alterado')
        print(f'PT_V26_APPROVE=PASS group={group["id"]} saved={_state_path()} game_unchanged=true', flush=True)
        return {'FINISHED'}


class PT_OT_V28BatchPreview(bpy.types.Operator):
    bl_idname = 'pt_env.v28_preview_batch'
    bl_label = 'Mostrar instâncias aprovadas'
    bl_description = 'Partilha malhas LOD entre árvores aprovadas. Só gera objetos temporários.'

    def execute(self, context):
        try:
            if not SESSION:
                raise ValueError('V28_ESTADO_NAO_CARREGADO')
            valid = {g['id']: g for g in GROUPS}
            approved = [(valid[key], data) for key, data in SESSION['approvals'].items()
                        if key in valid and data.get('approved') is True]
            if not approved:
                raise ValueError('V28_NENHUMA_ARVORE_APROVADA')
            if len(approved) > MAX_SCENE_INSTANCES:
                raise ValueError('V28_DEMASIADAS_INSTANCIAS_PEDIR_LOTE_MENOR')
            models = {e.name:e for e in model_entries(_library_root())}
            lod = context.scene.pt_v28_lod
            # Validate everything *before* modifying scene. This catches
            # changed/removed downloaded models and stale LOD caches.
            verified = {}
            for _, data in approved:
                name = data.get('asset_archive')
                if name not in models:
                    raise ValueError(f'V28_MODELO_APROVADO_DESCONHECIDO:{name}')
                if name not in verified:
                    path = Path(models[name].path)
                    digest = sha256_file(path)
                    validate_prepared(_root()/V28_CACHE_REL, path, lod)
                    verified[name] = digest
                if verified[name] != data.get('asset_sha256'):
                    raise ValueError(f'V28_MODELO_APROVADO_MODIFICADO:{name}')
            _clear_v29_preview()
            _clear_col(PREVIEW_COLLECTION)
            _clear_col(BATCH_COLLECTION)
            _clear_v28_libs()
            seen = {}
            col = v23._collection(BATCH_COLLECTION)
            try:
                for group, data in approved:
                    name = data['asset_archive']
                    if name not in seen:
                        seen[name] = _loaded_prepared(name, lod)
                    lib, height = seen[name]
                    _instance(group, lib, height, data.get('scale_factor',1.),
                        output_col=col, asset=name, lod=lod)
            except Exception:
                _clear_col(BATCH_COLLECTION)
                _clear_v28_libs()
                raise
            v23._source().hide_set(False)
            _assert_native_hidden()
            print(f'PT_V28_BATCH=PASS instances={len(approved)} shared_libraries={len(seen)} '
                  'source_unchanged=true publish=false', flush=True)
            self.report({'INFO'}, f'{len(approved)} instâncias de {len(seen)} bibliotecas de malhas')
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            print(f'PT_V28_BATCH=FAIL {type(e).__name__}:{e}', flush=True)
            return {'CANCELLED'}



def _clear_v29_mask():
    """Remove ONLY V29 temporary Geometry Nodes from the V19 visual proxy."""
    source = v23._source()
    for modifier in list(source.modifiers):
        if modifier.name == V29_MASK_MOD:
            source.modifiers.remove(modifier)
    attribute = source.data.attributes.get(V29_MASK_ATTR)
    if attribute is not None:
        source.data.attributes.remove(attribute)
    node_group = bpy.data.node_groups.get(V29_MASK_NODE)
    if node_group is not None and node_group.users == 0:
        bpy.data.node_groups.remove(node_group)


def _clear_v29_preview():
    _clear_col(V29_BATCH_COLLECTION)
    _clear_col(V30_BATCH_COLLECTION)
    # V31 extras are disposable objects, not part of the original Stage.
    _clear_col('PT_V31_ARVORES_EXTRA_LOD0_SO_PREVIEW')
    _clear_col('PT_V31_FACES_RESTANTES_INSPECAO')
    _clear_v29_mask()
    # The remaining asset library is kept until the caller clears all libraries.
    v23._source().hide_set(False)
    _assert_native_hidden()


def _mask_v29_faces(face_ids):
    """Non-destructive Geometry Nodes face mask on the *existing* V19 proxy.

    No second full-stage mesh; no SMD or source mesh data is rewritten.
    Clearing the modifier and its private face attribute restores exactly the
    same proxy. This is a visual mask, NOT a collision or runtime operation.
    """
    _clear_v29_mask()
    if not face_ids:
        return
    source = v23._source()
    mesh = source.data
    if not all(0 <= face < len(mesh.polygons) for face in face_ids):
        raise ValueError('V29_MASK_FACE_INVALIDA')
    try:
        attr = mesh.attributes.new(name=V29_MASK_ATTR, type='BOOLEAN', domain='FACE')
        for face in face_ids:
            attr.data[face].value = True
        group = bpy.data.node_groups.new(V29_MASK_NODE, 'GeometryNodeTree')
        group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        group_input = group.nodes.new('NodeGroupInput')
        group_output = group.nodes.new('NodeGroupOutput')
        named = group.nodes.new('GeometryNodeInputNamedAttribute')
        named.data_type = 'BOOLEAN'
        named.inputs['Name'].default_value = V29_MASK_ATTR
        delete = group.nodes.new('GeometryNodeDeleteGeometry')
        delete.domain = 'FACE'
        delete.mode = 'ALL'
        group.links.new(group_input.outputs['Geometry'], delete.inputs['Geometry'])
        group.links.new(named.outputs['Attribute'], delete.inputs['Selection'])
        group.links.new(delete.outputs['Geometry'], group_output.inputs['Geometry'])
        modifier = source.modifiers.new(V29_MASK_MOD, 'NODES')
        modifier.node_group = group
        source.hide_set(False)
        _assert_native_hidden()
    except Exception:
        _clear_v29_mask()
        raise


class PT_OT_V29PreviewAllLOD0(bpy.types.Operator):
    bl_idname = 'pt_env.v29_preview_all_lod0'
    bl_label = 'Testar todas as árvores (LOD0 alto)'
    bl_description = ('Mostra UMA instância partilhada por árvore com tronco, mesmo sem '
                      'aprovação; só no Blender, sem escrever SMD, JSON de aprovações ou assets')

    def execute(self, context):
        try:
            if SESSION is None:
                raise ValueError('V29_ESTADO_NAO_CARREGADO')
            if v24.PLAN is None or v24.PLAN.get('source_sha256') != v23.CONFIG['sha']:
                raise ValueError('V29_V24_SOURCE_SHA_NAO_CORRESPONDE')
            source = v23._source()
            source_groups = virtual_groups(v25.PLAN, v24=v24.PLAN) if v25.PLAN else v24.PLAN['groups']
            plan = plan_tree_instances(source_groups,
                    source_face_count=len(source.data.polygons),
                    source_sha256=v23.CONFIG['sha'], asset=v23.CONFIG['asset'])
            # Explicitly force highest detail, regardless of the V28 UI setting.
            model = context.scene.pt_v26_model
            choices = {item.name:item for item in model_entries(_library_root())}
            if model not in choices:
                raise ValueError('V29_MODELO_NAO_ENCONTRADO')
            archive = Path(choices[model].path)
            lod_path, metadata = validate_prepared(_root()/V28_CACHE_REL, archive, 'LOD0')
            source_digest = sha256_file(archive)
            if source_digest != metadata['source_sha256']:
                raise ValueError('V29_SHA_DO_MODELO_NAO_CORRESPONDE')
            mask_old = bool(context.scene.pt_v29_mask_existing)
            multiplier = float(context.scene.pt_v26_scale)
            if not .1 <= multiplier <= 10.:
                raise ValueError('V29_ESCALA_INVALIDA')
            # No persisted approval is needed. Always clear the previous visual
            # batch and only then allocate one shared high-detail collection.
            _clear_v29_preview()
            v25._clear_pair()
            v25._hide_older_inspection()
            _clear_col(SELECT_COLLECTION)
            _clear_col(PREVIEW_COLLECTION)
            _clear_col(BATCH_COLLECTION)
            _clear_v28_libs()
            library, model_height = _loaded_prepared(model, 'LOD0')
            col = v23._collection(V29_BATCH_COLLECTION)
            try:
                indexed = {g['id']:g for g in GROUPS}
                for tree in plan['trees']:
                    obj = _instance(indexed[tree['id']], library, model_height,
                            multiplier, output_col=col, asset=model, lod='LOD0')
                    obj.name = f'PT_V29_LOD0_{tree["id"]}'
                    # Stable pseudo-random orientation prevents an obvious grid of
                    # identical trees. No position, source face or collision changes.
                    degrees = int(hashlib.sha256((tree['id'] + source_digest).encode()).hexdigest()[:8],16)
                    obj.rotation_euler.z = (degrees / 0xffffffff) * 2 * math.pi
                    obj['pt_v29_trial_only'] = True
                if mask_old:
                    _mask_v29_faces(plan['masked_face_indices'])
                else:
                    source.hide_set(False)
                _assert_native_hidden()
                record = preview_record(plan, model_name=model,
                            model_sha256=source_digest, mask_originals=mask_old,
                            cache_manifest=metadata)
                path = _state_path().with_suffix('.v29_batch_preview.json')
                atomic_write_json(path, record)
                # Restore only explicitly requested V32 replacement instances.
                # Old V31 hidden-only selections do not create any new trees.
                from pt_asset_tool.blender import environment_residual_v31 as res_v31
                res_v31.restore_v32_replacements()
            except Exception:
                _clear_v29_preview()
                _clear_v28_libs()
                raise
            print(f'PT_V29_BATCH=PASS instances={plan["count"]} lod=LOD0 '
                  f'library=1 original_faces_hidden={len(plan["masked_face_indices"]) if mask_old else 0} '
                  f'excluded_foliage_only={plan["excluded_groups"]} '
                  'source_unchanged=true game_unchanged=true publish=false',flush=True)
            self.report({'INFO'}, f'{plan["count"]} árvores LOD0 com malha partilhada · só preview')
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            print(f'PT_V29_BATCH=FAIL {type(e).__name__}:{e}',flush=True)
            return {'CANCELLED'}



def _v30_remaining_material_faces(source, masked_faces):
    """Audit only: leaf-related textures may also occur on ground or walls.

    The additional faces are NEVER hidden without source-level classification.
    """
    proposals = v23._v22()
    if not proposals:
        return 0
    materials = set()
    for candidate in proposals.get('candidates', []):
        if candidate.get('category') == 'ARVORE':
            materials.update(candidate.get('materials', []))
    if not materials:
        return 0
    marked = set(masked_faces)
    return sum(1 for face in source.data.polygons
               if face.index not in marked and
               face.material_index < len(source.data.materials) and
               source.data.materials[face.material_index] is not None and
               source.data.materials[face.material_index].name in materials)


class PT_OT_V30PreviewAllLOD0(bpy.types.Operator):
    bl_idname = 'pt_env.v30_preview_complete_lod0'
    bl_label = 'Testar cobertura completa (LOD0; experimental)'
    bl_description = ('Inclui folhas sem tronco (podem ser arbustos ou copas duplicadas), '
                      'tenta apoios de parede; SOMENTE visual, não aprova nem altera o jogo')

    def execute(self, context):
        try:
            if SESSION is None:
                raise ValueError('V30_ESTADO_NAO_CARREGADO')
            if v24.PLAN is None or v24.PLAN.get('source_sha256') != v23.CONFIG['sha']:
                raise ValueError('V30_V24_SOURCE_SHA_NAO_CORRESPONDE')
            source = v23._source()
            source_groups = virtual_groups(v25.PLAN, v24=v24.PLAN) if v25.PLAN else v24.PLAN['groups']
            plan = plan_complete_preview(source_groups,
                source_face_count=len(source.data.polygons),
                source_sha256=v23.CONFIG['sha'], asset=v23.CONFIG['asset'])
            model = context.scene.pt_v26_model
            models = {item.name:item for item in model_entries(_library_root())}
            if model not in models:
                raise ValueError('V30_MODELO_NAO_ENCONTRADO')
            archive = Path(models[model].path)
            lod_path, metadata = validate_prepared(_root()/V28_CACHE_REL, archive, 'LOD0')
            source_digest = sha256_file(archive)
            if source_digest != metadata['source_sha256']:
                raise ValueError('V30_SHA_DO_MODELO_NAO_CORRESPONDE')
            multiplier = float(context.scene.pt_v26_scale)
            if not .1 <= multiplier <= 10.:
                raise ValueError('V30_ESCALA_INVALIDA')
            mask_old = bool(context.scene.pt_v29_mask_existing)
            mount_on_wall = bool(context.scene.pt_v30_wall_placement)

            # Clear *only* generated previews. V22-V25 JSONs and the underlying
            # one-piece V19 proxy are never rewritten. V27 copied fragments can
            # otherwise look like old leaves even after the proxy is masked.
            _clear_v29_preview()
            v25._clear_inspection_copies()
            from pt_asset_tool.blender import stage072_textures_v27 as v27
            v27._clear()
            _clear_col(SELECT_COLLECTION)
            _clear_col(PREVIEW_COLLECTION)
            _clear_col(BATCH_COLLECTION)
            _clear_v28_libs()
            source.hide_set(False)
            _assert_native_hidden()
            library, model_height = _loaded_prepared(model, 'LOD0')
            col = v23._collection(V30_BATCH_COLLECTION)
            by_id = {group['id']:group for group in source_groups}
            wall_bvh = None
            if mount_on_wall and plan['foliage_only']:
                try:
                    wall_bvh = wall_v30.build_wall_probe(source, set(plan['masked_face_indices']))
                except (RuntimeError, ValueError) as exc:
                    print(f'PT_V30_WALL=SKIPPED reason={type(exc).__name__}:{exc}', flush=True)
            wall_candidates = 0
            try:
                for tree in plan['trees']:
                    group = by_id[tree['id']]
                    obj = _instance(group, library, model_height,
                        multiplier, output_col=col, asset=model, lod='LOD0')
                    obj.name = 'PT_V30_LOD0_' + tree['id']
                    angle_hash = hashlib.sha256((tree['id'] + source_digest).encode()).digest()
                    angle = int.from_bytes(angle_hash[:4], 'big') / 0xffffffff * 2*math.pi
                    obj.rotation_euler.z = angle
                    obj['pt_v30_trial_only'] = True
                    obj['pt_v30_source_kind'] = tree['placement']
                    if tree['placement'] == 'FOLIAGE_ONLY_UNVERIFIED':
                        obj['pt_v30_semantic_status'] = 'REVER_ARVORE_OU_ARBUSTO'
                        if wall_bvh is not None:
                            contact = wall_v30.candidate_wall_contact(wall_bvh, source, group)
                            if contact is not None:
                                hit,normal,distance = contact
                                obj.location = hit + normal*.04
                                # A wall-mounted trial grows out from the wall,
                                # not from an invented ground position.
                                direction = (normal + Vector((0., 0., .18))).normalized()
                                base_rot = Vector((0.,0.,1.)).rotation_difference(direction)
                                from mathutils import Quaternion
                                obj.rotation_mode = 'QUATERNION'
                                obj.rotation_quaternion = base_rot @ Quaternion((0.,0.,1.),angle)
                                obj['pt_v30_wall_candidate'] = True
                                obj['pt_v30_wall_distance_view'] = float(distance)
                                wall_candidates += 1
                if mask_old:
                    from pt_asset_tool.blender import environment_residual_v31 as res_v31
                    # Explicitly confirmed V31 residual masks survive a V30 rerun.
                    # This changes only the temporary proxy modifier, not Stage faces.
                    extra = res_v31.saved_extra_faces()
                    _mask_v29_faces(sorted(set(plan['masked_face_indices']) | extra))
                residual = _v30_remaining_material_faces(source,
                        set(plan['masked_face_indices']) | (extra if mask_old else set()))
                _assert_native_hidden()
                record = v30_preview_record(plan, model_name=model,
                    model_sha256=source_digest, mask_originals=mask_old,
                    cache_manifest=metadata, wall_candidates=wall_candidates,
                    residual_material_faces=residual)
                record['wall_detection_requested'] = mount_on_wall
                record['original_inspection_meshes_removed'] = True
                path = _state_path().with_suffix('.v30_full_preview.json')
                atomic_write_json(path, record)
            except Exception:
                _clear_v29_preview()
                _clear_v28_libs()
                raise
            print(f'PT_V30_BATCH=PASS instances={plan["count"]} with_trunk={plan["with_trunk"]} '
                  f'foliage_only_unverified={plan["foliage_only"]} '
                  f'wall_candidates_unverified={wall_candidates} '
                  f'original_faces_hidden={len(plan["masked_face_indices"]) if mask_old else 0} '
                  f'residual_material_suspects={residual} '
                  'source_unchanged=true game_unchanged=true publish=false',flush=True)
            self.report({'WARNING'}, f'{plan["count"]} instâncias LOD0; {plan["foliage_only"]} sem tronco: '
                                  'inspecionar antes de aprovar')
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            print(f'PT_V30_BATCH=FAIL {type(e).__name__}:{e}',flush=True)
            return {'CANCELLED'}


class PT_OT_V29Clear(bpy.types.Operator):
    bl_idname = 'pt_env.v29_clear_batch'
    bl_label = 'Restaurar árvores originais'
    bl_description = 'Elimina as instâncias V29 e o efeito Geometry Nodes temporário'

    def execute(self, context):
        _remove_visuals()
        print('PT_V29_RESTORE=PASS original_proxy_restored=true publish=false',flush=True)
        self.report({'INFO'}, 'Todas as árvores antigas voltaram a aparecer')
        return {'FINISHED'}


class PT_OT_V26Clear(bpy.types.Operator):
    bl_idname = 'pt_env.v26_clear'
    bl_label = 'Restaurar mapa e limpar prévia'
    def execute(self, context):
        _remove_visuals()
        self.report({'INFO'}, 'Pré-visualização removida; Stage original do jogo preservado')
        print('PT_V26_CLEAR=PASS source_unchanged=true', flush=True)
        return {'FINISHED'}


class PT_PT_EnvironmentV26(bpy.types.Panel):
    bl_label = 'Etervale · Modernizar ambiente'
    bl_idname = 'PT_PT_ETERVALE_ENVIRONMENT_V26'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Etervale'

    def draw(self, context):
        lay = self.layout
        sc = context.scene
        if not GROUPS:
            lay.label(text='Sem grupos de vegetação neste mapa', icon='INFO')
            return
        lay.label(text='1. Modelo para árvores', icon='OUTLINER_OB_MESH')
        lay.prop(sc, 'pt_v26_model', text='Modelo')
        lay.prop(sc, 'pt_v26_scale', text='Escala')
        lay.operator('pt_env.v30_preview_complete_lod0',
                     text='Mostrar floresta (LOD0)', icon='OUTLINER_OB_EMPTY')
        lay.separator()
        lay.label(text='2. Selecionar vegetação antiga', icon='EYEDROPPER')
        lay.operator('pt_env.v31_pick_remaining', text='Clicar no mapa', icon='EYEDROPPER')
        lay.prop(sc, 'pt_v31_only_suspects', text='Só vegetação')
        lay.prop(sc, 'pt_v31_scope', text='Alcance')
        if sc.pt_v31_scope == 'ARVORE_LOCAL':
            lay.prop(sc, 'pt_v31_radius', text='Raio')
        lay.operator('pt_env.v31_expand', text='Atualizar destaque', icon='RESTRICT_SELECT_OFF')
        from pt_asset_tool.blender import environment_residual_v31 as res_v31
        lay.label(text=f'{len(res_v31.SELECTED)} faces selecionadas')
        lay.separator()
        lay.label(text='3. O que fazer com a seleção?')
        line = lay.row(align=True)
        line.operator('pt_env.v32_hide_leaves', text='Só ocultar folhas', icon='HIDE_ON')
        line.operator('pt_env.v32_replace_tree', text='Substituir árvore', icon='OUTLINER_OB_EMPTY')
        row = lay.row(align=True)
        row.operator('pt_env.v32_undo', text='Desfazer última', icon='LOOP_BACK')
        row.operator('pt_env.v31_clear', text='Cancelar', icon='X')
        lay.separator()
        lay.operator('pt_env.v31_light_review', text='Mostrar / ocultar modelos 3D', icon='HIDE_OFF')
        lay.operator('pt_env.v29_clear_batch', text='Restaurar cenário', icon='LOOP_BACK')
        lay.label(text='Pré-visualização reversível · jogo intacto')
        lay.prop(sc, 'pt_v32_advanced', text='Ferramentas avançadas')
        if sc.pt_v32_advanced:
            b = lay.box()
            b.prop(sc, 'pt_v28_lod', text='LOD individual')
            b.prop(sc, 'pt_v29_mask_existing', text='Ocultar originais no lote')
            b.prop(sc, 'pt_v30_wall_placement', text='Tentativa de apoio em parede')
            b.prop(sc, 'pt_v31_snap_px', text='Tolerância do clique (px)')
            b.operator('pt_env.v31_reset_masks', text='Reverter seleções V31/V32')
            b.operator('pt_env.v29_preview_all_lod0', text='Ensaio conservador V29')
            b.operator('pt_env.v26_isolate', text='Inspecionar grupo V26')
            b.label(text='Operações V21–V31 disponíveis abaixo')


CLASSES = (PT_V26TreeRow, PT_OT_V26Isolate, PT_OT_V26Preview,
           PT_OT_V26Approve, PT_OT_V28BatchPreview, PT_OT_V29PreviewAllLOD0,
           PT_OT_V30PreviewAllLOD0, PT_OT_V29Clear, PT_OT_V26Clear, PT_PT_EnvironmentV26)


def configure():
    global GROUPS, SESSION, MODEL_ENUM_ITEMS
    _assert_native_hidden()
    GROUPS = _get_groups()
    SESSION = _load_state()
    MODEL_ENUM_ITEMS = [(e.name, e.name, f'Modelo em {e.source}; apenas prévia')
                        for e in model_entries(_library_root())]
    if not MODEL_ENUM_ITEMS:
        MODEL_ENUM_ITEMS = [('NONE', 'Sem modelos de árvore', 'Adicionar modelos *.blend.zip')]
    sc = bpy.context.scene
    if not hasattr(bpy.types.Scene, 'pt_v26_rows'):
        bpy.types.Scene.pt_v26_rows = CollectionProperty(type=PT_V26TreeRow)
        bpy.types.Scene.pt_v26_active = IntProperty(min=0,default=0,update=_on_selected)
        bpy.types.Scene.pt_v26_model = EnumProperty(name='Modelo',items=_model_items)
        bpy.types.Scene.pt_v28_lod = EnumProperty(name='LOD',items=[
            ('LOD0','Próximo','Mais geometria; inspeção próxima'),
            ('LOD1','Médio','Equilíbrio para o mapa'),
            ('LOD2','Distante','Máxima redução para floresta'),], default='LOD1')
        bpy.types.Scene.pt_v26_scale = FloatProperty(name='Escala',min=.1,max=10.,default=1.)
    if not hasattr(bpy.types.Scene, 'pt_v29_mask_existing'):
        bpy.types.Scene.pt_v29_mask_existing = BoolProperty(name='Ocultar original', default=True)
    if not hasattr(bpy.types.Scene, 'pt_v32_advanced'):
        bpy.types.Scene.pt_v32_advanced = BoolProperty(
            name='Mostrar ferramentas antigas e diagnóstico', default=False)
    if not hasattr(bpy.types.Scene, 'pt_v30_wall_placement'):
        bpy.types.Scene.pt_v30_wall_placement = BoolProperty(
            name='Apoiar na parede (experimental)', default=True)
    _refresh_rows(bpy.context)
    _assert_native_hidden()
    print(f'PT_V26=READY trees={len(GROUPS)} models={len(model_entries(_library_root()))} '
          f'approvals={len(SESSION["approvals"])} publish=false',flush=True)
