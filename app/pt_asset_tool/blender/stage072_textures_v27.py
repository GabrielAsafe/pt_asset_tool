"""V27 Stage072 texture/component proposals within the V26 workbench.

Single V19 proxy; optional small inspection copies; no Stage writes, no game
export. Texture rules are SHA-locked to the currently loaded Stage.
"""
import json
from pathlib import Path

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty

from pt_asset_tool.stage072_semantic_core import atomic_write_json
from pt_asset_tool.stage072_texture_semantics_v27 import (
    ROLES, assign_rule, build_catalog, check_catalog, remove_rule,
)
from pt_asset_tool.blender import stage072_tree_v23 as v23
from pt_asset_tool.blender import stage072_tree_review_v25 as v25

COLLECTION = 'PT_V27_TEXTURA_COMPONENTES_SO_PREVIEW'
CATALOG = None
LOCK = False
MAX_COMPONENT_FACES = 14000
MAX_MATERIAL_PREVIEW_FACES = 18000
MAX_MATERIAL_PREVIEW_OBJECTS = 75


def _path():
    p = v23._plan_path()
    if not p.name.endswith('.v23_trees.json'):
        raise ValueError('V27_CAMINHO_BASE_INVALIDO')
    return p.with_name(p.name.replace('.v23_trees.json', '.v27_texture_semantics.json'))


def _identity():
    proxy = v23._source()
    return v23.CONFIG['asset'], v23.CONFIG['sha'], len(proxy.data.polygons)


def _save():
    if CATALOG is None:
        return
    asset, sha, count = _identity()
    check_catalog(CATALOG, asset=asset, sha=sha, face_count=count)
    atomic_write_json(_path(), CATALOG)


def _selected(context):
    if CATALOG is None:
        return None
    i = context.scene.pt_v27_texture_active
    return CATALOG['textures'][i] if 0 <= i < len(CATALOG['textures']) else None


def _refresh(context):
    global LOCK
    LOCK = True
    try:
        sc = context.scene
        old = sc.pt_v27_texture_active
        sc.pt_v27_textures.clear()
        for mat in CATALOG.get('textures', []) if CATALOG else []:
            row = sc.pt_v27_textures.add()
            row.key = mat['key']
            override = CATALOG['rules'].get(mat['key'], {})
            role = override.get('category') or mat['suggestion']
            marker = '✓' if override else '?'
            row.name = f'{marker} {role[:9]} · {mat["faces"]}f · {mat["component_count"]} obj · {mat["key"][4:34]}'
        sc.pt_v27_texture_active = min(old, max(0, len(sc.pt_v27_textures) - 1))
        sc.pt_v27_component_active = 0
    finally:
        LOCK = False


def _texture_changed(self, context):
    if not LOCK:
        context.scene.pt_v27_component_active = 0


def _get_faces():
    obj = v23._source()
    me = obj.data
    slots = []
    for i, slot in enumerate(obj.material_slots):
        mat = slot.material
        image = ''
        if mat and mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                img = getattr(node, 'image', None)
                if img is not None:
                    image = img.filepath or img.name
                    break
        slots.append({'index':i, 'name':mat.name if mat else '', 'image':image})
    # Prevent unusual proxy meshes with no material slots from crashing.
    if not slots:
        raise ValueError('V27_PROXY_SEM_MATERIAIS')
    polygons = [{'index':p.index, 'vertices':list(p.vertices),
                 'material_index':p.material_index, 'normal_z':float(p.normal.z),
                 'area':float(p.area)} for p in me.polygons]
    known = []
    proposals = v23._v22()
    if proposals:
        for c in proposals.get('candidates', []):
            if c.get('category') == 'ARVORE':
                known.extend(c.get('materials', []))
    return slots, polygons, known


def _clear():
    v23._remove_collection(COLLECTION)


def _preview(components):
    groups = list(components)
    total = sum(c['face_count'] for c in groups)
    if len(groups) > MAX_MATERIAL_PREVIEW_OBJECTS or total > MAX_MATERIAL_PREVIEW_FACES:
        raise ValueError(f'V27_PREVIEW_EXCESSIVO:{total} faces/{len(groups)} objetos — isolar um componente')
    _clear()
    source = v23._source()
    col = v23._collection(COLLECTION)
    created = 0
    try:
        for index, component in enumerate(groups, 1):
            obj = v23._create_inspection_mesh(source, component['faces'], f'PT_V27_COMPONENTE_{index:03d}')
            if obj is None:
                continue
            col.objects.link(obj)
            obj['pt_v27_component_id'] = component['id']
            obj.show_in_front = True
            obj.show_wire = True
            created += 1
        if not created:
            raise ValueError('V27_COMPONENTE_VAZIO')
        source.hide_set(True)
        v25._hide_native_stage_sources()
    except Exception:
        _clear()
        source.hide_set(False)
        v25._hide_native_stage_sources()
        raise
    return created


class PT_V27TextureRow(bpy.types.PropertyGroup):
    key: StringProperty()


class PT_OT_V27Scan(bpy.types.Operator):
    bl_idname = 'pt_env.v27_scan'
    bl_label = 'Analisar texturas do Stage'
    bl_description = 'Lê materiais e faces do proxy e cria grupos ligados; não altera SMD'

    def execute(self, context):
        global CATALOG
        try:
            asset, sha, face_count = _identity()
            slots, polygons, known = _get_faces()
            fresh = build_catalog(asset=asset, source_sha256=sha,
                                  source_face_count=face_count, slots=slots, faces=polygons,
                                  v22_material_names=known, previous=CATALOG)
            # Saving is atomic. An old valid file with confirmed rules is preserved.
            CATALOG = fresh
            _save()
            _refresh(context)
            self.report({'INFO'}, f'{len(CATALOG["textures"])} texturas; {CATALOG["counts"]["components"]} componentes')
            print(f'PT_V27_SCAN=PASS textures={CATALOG["counts"]["textures"]} '
                  f'components={CATALOG["counts"]["components"]} faces={face_count} '
                  'source_unchanged=true publish=false', flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            print(f'PT_V27_SCAN=FAIL {type(exc).__name__}:{exc}', flush=True)
            return {'CANCELLED'}


class PT_OT_V27Classify(bpy.types.Operator):
    bl_idname = 'pt_env.v27_classify'
    bl_label = 'Confirmar categoria da textura'
    bl_description = 'Classifica TODAS as faces que utilizam esta imagem apenas neste Stage (SHA-256)'

    def execute(self, context):
        global CATALOG
        try:
            tex = _selected(context)
            if tex is None:
                raise ValueError('V27_ESCOLHER_TEXTURA')
            asset, sha, count = _identity()
            result = assign_rule(CATALOG, tex['key'], context.scene.pt_v27_role)
            check_catalog(result, asset=asset, sha=sha, face_count=count)
            CATALOG = result
            _save()
            _refresh(context)
            print(f'PT_V27_RULE=PASS texture={tex["key"]} category={context.scene.pt_v27_role} '
                  f'faces={tex["faces"]} only_this_stage=true', flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class PT_OT_V27ClearRole(bpy.types.Operator):
    bl_idname = 'pt_env.v27_unclassify'
    bl_label = 'Retirar regra da textura'
    def execute(self, context):
        global CATALOG
        tex = _selected(context)
        if tex is None:
            return {'CANCELLED'}
        CATALOG = remove_rule(CATALOG, tex['key'])
        _save()
        _refresh(context)
        return {'FINISHED'}


class PT_OT_V27ShowComponent(bpy.types.Operator):
    bl_idname = 'pt_env.v27_isolate_component'
    bl_label = 'Isolar componente selecionado'

    def execute(self, context):
        try:
            tex = _selected(context)
            if tex is None:
                raise ValueError('V27_ESCOLHER_TEXTURA')
            i = context.scene.pt_v27_component_active
            if not 0 <= i < len(tex['components']):
                raise ValueError('V27_COMPONENTE_NAO_EXISTE')
            group = tex['components'][i]
            if group['face_count'] > MAX_COMPONENT_FACES:
                raise ValueError('V27_COMPONENTE_GRANDE_DEMAIS_PARA_COPIAR')
            _preview([group])
            print(f'PT_V27_ISOLATE=PASS component={i} faces={group["face_count"]} '
                  'source_unchanged=true', flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class PT_OT_V27ShowMaterial(bpy.types.Operator):
    bl_idname = 'pt_env.v27_preview_material'
    bl_label = 'Criar objetos ligados desta textura'
    bl_description = 'Cria cópias temporárias dos componentes até um limite seguro; nunca altera a malha de origem'

    def execute(self, context):
        try:
            tex = _selected(context)
            if tex is None:
                raise ValueError('V27_ESCOLHER_TEXTURA')
            created = _preview(tex['components'])
            print(f'PT_V27_OBJECTS=PASS texture={tex["key"]} objects={created} '
                  'source_unchanged=true', flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class PT_OT_V27Restore(bpy.types.Operator):
    bl_idname = 'pt_env.v27_restore'
    bl_label = 'Restaurar mapa e limpar objetos'

    def execute(self, context):
        _clear()
        v23._source().hide_set(False)
        v25._hide_native_stage_sources()
        return {'FINISHED'}


class PT_PT_EnvironmentV27(bpy.types.Panel):
    bl_label = 'Texturas e componentes · V27'
    bl_idname = 'PT_PT_ETERVALE_ENVIRONMENT_V27'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Etervale'
    bl_parent_id = 'PT_PT_ETERVALE_ENVIRONMENT_V26'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context.scene, 'pt_v32_advanced', False))

    def draw(self, context):
        lay = self.layout
        lay.label(text='Agrupar faces por imagem e geometria ligada')
        lay.operator('pt_env.v27_scan', icon='TEXTURE')
        if CATALOG is None:
            lay.label(text='Analisar para catalogar o mapa')
            return
        lay.label(text=f'{CATALOG["counts"]["textures"]} texturas · {CATALOG["counts"]["components"]} componentes')
        sc = context.scene
        lay.template_list('UI_UL_list', 'PT_V27_TEXTURES', sc, 'pt_v27_textures',
                          sc, 'pt_v27_texture_active', rows=6)
        tex = _selected(context)
        if tex is None:
            return
        box = lay.box()
        box.label(text=tex['key'][:60])
        current = CATALOG['rules'].get(tex['key'])
        box.label(text=f'Confirmado: {current["category"]}' if current else
                  f'Sugestão: {tex["suggestion"]} (não confirmada)')
        box.label(text=tex['reason'][:50])
        box.label(text=f'{tex["faces"]} faces · {tex["component_count"]} componentes')
        box.prop(sc, 'pt_v27_role', text='Categoria')
        row = box.row(align=True)
        row.operator('pt_env.v27_classify', text='Confirmar')
        row.operator('pt_env.v27_unclassify', text='Retirar')
        box.prop(sc, 'pt_v27_component_active', text='Componente (0 = maior)')
        box.operator('pt_env.v27_isolate_component', text='Isolar componente')
        box.operator('pt_env.v27_preview_material', text='Criar objetos desta textura')
        box.operator('pt_env.v27_restore', text='Restaurar vista')
        box.label(text='Regras só neste mapa; SMD intacto')


CLASSES = (PT_V27TextureRow, PT_OT_V27Scan, PT_OT_V27Classify,
           PT_OT_V27ClearRole, PT_OT_V27ShowComponent,
           PT_OT_V27ShowMaterial, PT_OT_V27Restore, PT_PT_EnvironmentV27)


def configure():
    global CATALOG
    asset, sha, count = _identity()
    path = _path()
    CATALOG = None
    if path.exists():
        doc = json.loads(path.read_text(encoding='utf-8'))
        check_catalog(doc, asset=asset, sha=sha, face_count=count)
        CATALOG = doc
    if not hasattr(bpy.types.Scene, 'pt_v27_textures'):
        bpy.types.Scene.pt_v27_textures = CollectionProperty(type=PT_V27TextureRow)
        bpy.types.Scene.pt_v27_texture_active = IntProperty(default=0, min=0,
                                                             update=_texture_changed)
        bpy.types.Scene.pt_v27_component_active = IntProperty(default=0, min=0)
        bpy.types.Scene.pt_v27_role = EnumProperty(name='Categoria',
                items=[(x, x.title(), 'Classificação explícita desta textura') for x in ROLES],
                default='OUTRO')
    _refresh(bpy.context)
    print(f'PT_V27=READY asset={asset} textures={len(CATALOG["textures"]) if CATALOG else 0} '
          f'output={path} source_unchanged=true', flush=True)
