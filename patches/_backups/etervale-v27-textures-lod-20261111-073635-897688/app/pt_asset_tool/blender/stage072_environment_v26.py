"""V26 simplified Blender workbench for Stage072 forest replacement.

One visible panel, one proxy, one selected tree and a *private* asset preview.
All game-space metadata and V22–V25 decisions remain in their own JSON files.
This script intentionally does not implement SMD export or runtime deployment.
"""
import hashlib
import json
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector

from pt_asset_tool.environment_library_v26 import model_entries, prepare_model
from pt_asset_tool.stage072_semantic_core import atomic_write_json
from pt_asset_tool.stage072_tree_review_v25 import virtual_groups
from pt_asset_tool.blender import stage072_tree_v23 as v23
from pt_asset_tool.blender import stage072_tree_group_v24 as v24
from pt_asset_tool.blender import stage072_tree_review_v25 as v25

SELECT_COLLECTION = 'PT_V26_ARVORE_EM_INSPECAO'
PREVIEW_COLLECTION = 'PT_V26_MODELO_COMPARACAO'
LIB_COLLECTION = 'PT_V26_BIBLIOTECA_PRIVADA'
SESSION = None
GROUPS = []
DECISIONS = {}
MODEL_ENUM_ITEMS = []
LOCK = False
MAX_VERTICES = 750_000
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
        raise ValueError('V24_GRUPOS_NAO_CARREGADOS')
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
    sha = v24.PLAN['source_sha256']
    if path.is_file():
        doc = json.loads(path.read_text(encoding='utf-8'))
        if (doc.get('format') != 'PT_ETERVALE_ENVIRONMENT_V26' or
            doc.get('source_sha256') != sha or doc.get('asset') != v24.PLAN['asset'] or
            doc.get('publish_enabled') is not False):
            raise ValueError('V26_ESTADO_INCOMPATIVEL_PRESERVADO')
        if not isinstance(doc.get('approvals'), dict):
            raise ValueError('V26_APROVACOES_INVALIDAS')
        return doc
    return {'format':'PT_ETERVALE_ENVIRONMENT_V26', 'version':1,
            'source_sha256':sha, 'asset':v24.PLAN['asset'],
            'publish_enabled':False, 'game_assets_modified':False,
            'approvals':{}}


def _save():
    if SESSION is not None:
        atomic_write_json(_state_path(), SESSION)


def _clear_col(name):
    v23._remove_collection(name)


def _remove_visuals():
    _clear_col(SELECT_COLLECTION)
    _clear_col(PREVIEW_COLLECTION)
    _clear_col(LIB_COLLECTION)
    original = v23._source()
    original.hide_set(False)
    _assert_native_hidden()


def _show_selection(group, isolate=False):
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


def _load_blend_library(blend_path):
    """Read an external .blend, copy mesh-only geometry to an unlinked library.

    Never link external objects into the Stage scene. Their original datablocks
    are removed after normalization; only copied meshes survive in the library.
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
        if sum(len(o.data.vertices) for o in meshes) > MAX_VERTICES:
            raise ValueError('MODELO_POLIGONOS_DEMAIS')
        if any(o.find_armature() or o.data.shape_keys for o in meshes):
            raise ValueError('MODELO_ANIMADO_NAO_SUPORTADO_NA_V26')
        mw = {o.name:o.matrix_world.copy() for o in meshes}
        points = [mw[o.name] @ v.co for o in meshes for v in o.data.vertices]
        lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        height = float(hi.z - lo.z)
        if height <= 1e-6:
            raise ValueError('MODELO_SEM_ALTURA')
        origin = Vector(((lo.x + hi.x)/2., (lo.y + hi.y)/2., lo.z))
        col = v23._collection(LIB_COLLECTION, linked=False)
        for i, o in enumerate(meshes):
            me = o.data.copy()
            me.transform(Matrix.Translation(-origin) @ mw[o.name])
            me.update()
            ob = bpy.data.objects.new(f'PT_V26_LIBRARY_PART_{i:03}', me)
            col.objects.link(ob)
            ob['pt_v26_library_only'] = True
        # Record external paths that were not packed, rather than quietly
        # claiming all materials succeeded. Never edit Stage material slots.
        missing_images = []
        mats = {mat for o in col.objects for mat in o.data.materials if mat}
        for mat in mats:
            if not mat.use_nodes or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                img = getattr(node, 'image', None)
                if img is None or img.packed_file:
                    continue
                raw = img.filepath
                if not raw:
                    continue
                candidate = Path(raw[2:]) if raw.startswith('//') else Path(raw)
                if not candidate.is_absolute():
                    candidate = blend_path.parent / candidate
                if candidate.is_file():
                    img.filepath = str(candidate)
                else:
                    missing_images.append(img.name)
        if missing_images:
            print(f'PT_V26_TEXTURES=REVIEW missing={sorted(set(missing_images))[:12]}', flush=True)
        return col, height
    finally:
        for o in loaded:
            if bpy.data.objects.get(o.name) is o:
                bpy.data.objects.remove(o, do_unlink=True)


def _preview_for(group, source_path, *, scale_factor):
    _clear_col(PREVIEW_COLLECTION)
    _clear_col(LIB_COLLECTION)
    if source_path.suffix.casefold() == '.blend':
        library, height = _load_blend_library(source_path)
    else:
        library, height = v23._import_glb_library(source_path)
    col = v23._collection(PREVIEW_COLLECTION)
    ob = bpy.data.objects.new(f'PT_V26_NOVA_ARVORE_{group["id"]}', None)
    col.objects.link(ob)
    ob.instance_type = 'COLLECTION'
    ob.instance_collection = library
    ob.location = tuple(group['anchor_view'])
    goal = max(.4, float(group.get('height_view') or 1.))
    ratio = goal / height * scale_factor
    ob.scale = (ratio,) * 3
    ob['pt_v26_preview_only'] = True
    ob['pt_v26_group_id'] = group['id']
    return ob


class PT_OT_V26Preview(bpy.types.Operator):
    bl_idname = 'pt_env.v26_preview'
    bl_label = 'Pré-visualizar substituição'
    bl_description = 'Carrega *.blend.zip da biblioteca local e compara uma árvore, sem publicar nem remover faces'

    def execute(self, context):
        try:
            g = _selected(context)
            if not g:
                raise ValueError('SELECIONAR_ARVORE')
            name = context.scene.pt_v26_model
            entries = {e.name:e for e in model_entries(_library_root())}
            if name not in entries:
                raise ValueError('MODELO_DE_ARVORE_NAO_ENCONTRADO_NA_BIBLIOTECA')
            source = Path(entries[name].path)
            p = prepare_model(source, _library_root(), _cache_root())
            _preview_for(g, p, scale_factor=float(context.scene.pt_v26_scale))
            v23._source().hide_set(False)
            _clear_col(SELECT_COLLECTION)
            _assert_native_hidden()
            SESSION['last_model'] = name
            _save()
            print(f'PT_V26_PREVIEW=PASS group={g["id"]} model={name} '
                  'source_unchanged=true publish=false', flush=True)
            self.report({'INFO'}, 'Modelo colocado na base proposta; compara com a árvore original')
            return {'FINISHED'}
        except Exception as e:
            _clear_col(PREVIEW_COLLECTION)
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
        if preview is None or not any(o.get('pt_v26_group_id') == group['id'] for o in preview.objects):
            self.report({'ERROR'}, 'Pré-visualizar primeiro esta árvore')
            return {'CANCELLED'}
        chosen = context.scene.pt_v26_model
        digest = hashlib.sha256()
        with (_library_root()/chosen).open('rb') as model_stream:
            for chunk in iter(lambda: model_stream.read(1024*1024), b''):
                digest.update(chunk)
        SESSION['approvals'][group['id']] = {
            'approved':True, 'asset_archive':chosen,
            'asset_sha256':digest.hexdigest(),
            'scale_factor':float(context.scene.pt_v26_scale),
            'source_face_count':len(group['faces']),
            'runtime_certified':False,
        }
        _save()
        _refresh_rows(context)
        self.report({'INFO'}, 'Aprovada apenas a proposta visual; jogo não alterado')
        print(f'PT_V26_APPROVE=PASS group={group["id"]} saved={_state_path()} game_unchanged=true', flush=True)
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
        lay.label(text='Etapa 1 · Árvores do mapa', icon='OUTLINER_OB_MESH')
        if not GROUPS:
            lay.label(text='Abrir um mapa com grupos V24 guardados')
            return
        lay.label(text=f'{len(GROUPS)} com tronco · restantes para revisão')
        sc = context.scene
        lay.template_list('UI_UL_list','PT_V26_TREES', sc, 'pt_v26_rows',sc,'pt_v26_active', rows=7)
        selected = _selected(context)
        if selected:
            b = lay.box()
            b.label(text=f'Árvore {selected["id"][:10]} · {len(selected["faces"])} faces')
            b.label(text=selected.get('completion','REVIEW')[:40])
            b.operator('pt_env.v26_isolate', text='1. Isolar árvore', icon='VIEWZOOM')
        lay.separator()
        lay.label(text='Etapa 2 · Modelo da tua biblioteca')
        lay.prop(sc,'pt_v26_model',text='Árvore 3D')
        lay.prop(sc,'pt_v26_scale',text='Escala relativa')
        lay.operator('pt_env.v26_preview',text='2. Comparar modelo novo',icon='MESH_DATA')
        lay.operator('pt_env.v26_approve',text='3. Aprovar substituição',icon='CHECKMARK')
        lay.operator('pt_env.v26_clear',text='Restaurar vista',icon='LOOP_BACK')
        lay.separator()
        n = len(SESSION['approvals']) if SESSION else 0
        lay.label(text=f'{n} modelos aprovados (só JSON)')
        lay.label(text='SMD e colisões nunca modificados')
        lay.label(text='Material PBR: fase posterior')


CLASSES = (PT_V26TreeRow, PT_OT_V26Isolate, PT_OT_V26Preview,
           PT_OT_V26Approve, PT_OT_V26Clear, PT_PT_EnvironmentV26)


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
        bpy.types.Scene.pt_v26_scale = FloatProperty(name='Escala',min=.1,max=10.,default=1.)
    _refresh_rows(bpy.context)
    _assert_native_hidden()
    print(f'PT_V26=READY trees={len(GROUPS)} models={len(model_entries(_library_root()))} '
          f'approvals={len(SESSION["approvals"])} publish=false',flush=True)
