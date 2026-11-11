"""V31: pick uncovered legacy foliage on the ONE V19 proxy and expand by material.

Only temporary inspection meshes, Geometry Nodes visibility and SHA-locked JSON.
No SMD/export/runtime writer; wide material operations need explicit confirmation.
"""
import json
import math
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from pt_asset_tool.environment_residual_v31 import (
    MODES, expand, blank, check_state, accept,
)
from pt_asset_tool.stage072_texture_semantics_v27 import texture_identity
from pt_asset_tool.stage072_semantic_core import atomic_write_json
from pt_asset_tool.blender import stage072_tree_v23 as v23
from pt_asset_tool.blender import stage072_tree_group_v24 as v24
from pt_asset_tool.blender import stage072_textures_v27 as v27
from pt_asset_tool.blender import stage072_tree_review_v25 as v25
from pt_asset_tool.blender import environment_wall_probe_v30 as wall_probe

COLLECTION = 'PT_V31_FACES_RESTANTES_INSPECAO'
EXTRA_COLLECTION = 'PT_V31_ARVORES_EXTRA_LOD0_SO_PREVIEW'
CURRENT = None
SELECTED = []
SEED = -1
SELECTED_SCOPE = None
STATE = None


def _env():
    from pt_asset_tool.blender import stage072_environment_v26 as env
    return env


def _source():
    return v23._source()


def _path():
    return v24._plan_path().with_suffix('.v31_residuais.json')


def _identity():
    return v23.CONFIG['asset'], v23.CONFIG['sha'], len(_source().data.polygons)


def _existing_mask():
    source = _source()
    attribute = source.data.attributes.get(_env().V29_MASK_ATTR)
    if attribute is None:
        return set()
    return {i for i, d in enumerate(attribute.data) if d.value}


def saved_extra_faces():
    """Used by V30 when it is rebuilt; never changes a previously certified plan."""
    if STATE is None:
        return set()
    asset, sha, count = _identity()
    check_state(STATE, asset=asset, sha=sha, face_count=count)
    return set(STATE['extra_faces'])


def _face_keys():
    source = _source()
    keys = []
    for idx, slot in enumerate(source.material_slots):
        mat = slot.material
        keys.append(texture_identity(mat.name if mat else '', slot_index=idx))
    if not keys:
        raise ValueError('V31_PROXY_SEM_MATERIAIS')
    result = []
    for p in source.data.polygons:
        if p.material_index >= len(keys):
            raise ValueError('V31_MATERIAL_FORA_INDICE')
        result.append(keys[p.material_index])
    return result


def _foliage_keys():
    source = _source()
    keys = set()
    names = set()
    doc = v23._v22()
    if doc:
        for candidate in doc.get('candidates', []):
            if candidate.get('category') == 'ARVORE':
                names.update(candidate.get('materials', []))
    for idx, slot in enumerate(source.material_slots):
        if slot.material and slot.material.name in names:
            keys.add(texture_identity(slot.material.name, slot_index=idx))
    if v27.CATALOG:
        for texture in v27.CATALOG.get('textures', []):
            key = texture['key']
            confirmed = v27.CATALOG.get('rules', {}).get(key, {})
            if confirmed.get('confirmed') and confirmed.get('category') in ('FOLHAGEM','ARBUSTO'):
                keys.add(key)
    return keys


def _preview_selection(selected):
    v23._remove_collection(COLLECTION)
    if not selected:
        return
    original = _source()
    ob = v23._create_inspection_mesh(original, selected, 'PT_V31_SELECAO_TEMPORARIA')
    if ob is None:
        raise ValueError('V31_PREVIEW_SEM_FACES')
    col = v23._collection(COLLECTION)
    col.objects.link(ob)
    ob.display_type = 'WIRE'
    ob.color = (1., .65, .07, 1.)
    ob.show_in_front = True
    ob.hide_render = True
    _source().hide_set(False)
    v25._hide_native_stage_sources()


def _expand_from_seed(scene):
    global SELECTED, SELECTED_SCOPE
    if SEED < 0:
        raise ValueError('V31_CLICAR_PRIMEIRO_NUMA_FACE_RESTANTE')
    source = _source()
    me = source.data
    mw = source.matrix_world
    keys = _face_keys()
    hidden = _existing_mask()
    faces = [tuple(int(v) for v in poly.vertices) for poly in me.polygons]
    centres = [tuple(mw @ poly.center) for poly in me.polygons]
    selected = expand(SEED, scene.pt_v31_scope,
                      face_vertices=faces, face_keys=keys, face_centers=centres,
                      hidden=hidden, foliage_keys=_foliage_keys(),
                      radius=float(scene.pt_v31_radius))
    _preview_selection(selected)
    SELECTED = selected
    SELECTED_SCOPE = scene.pt_v31_scope
    return selected


class PT_OT_V31Pick(bpy.types.Operator):
    bl_idname = 'pt_env.v31_pick_remaining'
    bl_label = 'Clicar numa folha / árvore antiga'
    bl_description = ('Clica na vista 3D numa face ainda não ocultada: procura no proxy original '
                      'e ignora as faces já substituídas, sem alterar o Stage')

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, 'Abre o painel numa vista 3D')
            return {'CANCELLED'}
        try:
            source = _source()
            hidden = _existing_mask()
            keys = _face_keys()
            suspects = _foliage_keys()
            only_suspects = bool(context.scene.pt_v31_only_suspects)
            world = source.matrix_world
            verts = [tuple(world @ vertex.co) for vertex in source.data.vertices]
            faces = []
            self.face_ids = []
            for poly in source.data.polygons:
                if poly.index in hidden:
                    continue
                if only_suspects and keys[poly.index] not in suspects:
                    continue
                if len(poly.vertices) < 3:
                    continue
                faces.append(tuple(int(i) for i in poly.vertices))
                self.face_ids.append(poly.index)
            if not faces:
                raise ValueError('V31_SEM_FACES_CANDIDATAS_DESMARCAR_FILTRO')
            self.bvh = BVHTree.FromPolygons(verts, faces, all_triangles=False)
            self.window_region = next(r for r in context.area.regions if r.type == 'WINDOW')
            self.rv3d = context.space_data.region_3d
            context.window_manager.modal_handler_add(self)
            self.report({'INFO'}, f'Clica numa face restante ({len(faces)} candidatas); Esc cancela')
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            print(f'PT_V31_PICK=FAIL {type(exc).__name__}:{exc}', flush=True)
            return {'CANCELLED'}

    def modal(self, context, event):
        global SEED, SELECTED
        if event.type in {'ESC','RIGHTMOUSE'} and event.value == 'PRESS':
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        r = self.window_region
        mx = event.mouse_x-r.x
        my = event.mouse_y-r.y
        if not (0 <= mx < r.width and 0 <= my < r.height):
            self.report({'WARNING'}, 'Clica dentro da janela 3D, não no painel lateral')
            return {'RUNNING_MODAL'}
        try:
            coord = (mx,my)
            origin = view3d_utils.region_2d_to_origin_3d(r,self.rv3d,coord)
            direction = view3d_utils.region_2d_to_vector_3d(r,self.rv3d,coord)
            hit,normal,idx,distance = self.bvh.ray_cast(origin,direction,10000.)
            if hit is None or idx is None:
                raise ValueError('V31_NENHUMA_FACE_RESTANTE_SOB_CURSOR')
            SEED = self.face_ids[idx]
            selected = _expand_from_seed(context.scene)
            source = _source()
            mat = source.data.materials[source.data.polygons[SEED].material_index]
            print(f'PT_V31_PICK=PASS seed={SEED} material={mat.name if mat else "NONE"} '
                  f'scope={context.scene.pt_v31_scope} faces={len(selected)} publish=false', flush=True)
            self.report({'INFO'}, f'Face {SEED}: {len(selected)} faces destacadas (ainda não ocultadas)')
            context.area.tag_redraw()
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc))
            print(f'PT_V31_PICK=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V31Expand(bpy.types.Operator):
    bl_idname = 'pt_env.v31_expand'
    bl_label = 'Atualizar seleção'
    bl_description = 'Recalcula a expansão com o alcance e raio escolhidos; só destaca faces'

    def execute(self, context):
        try:
            result = _expand_from_seed(context.scene)
            print(f'PT_V31_EXPAND=PASS seed={SEED} scope={context.scene.pt_v31_scope} '
                  f'faces={len(result)} masked=false',flush=True)
            self.report({'INFO'}, f'{len(result)} faces destacadas; confirmar para ocultar')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}


class PT_OT_V31ConfirmMask(bpy.types.Operator):
    bl_idname = 'pt_env.v31_confirm_mask'
    bl_label = 'Ocultar faces selecionadas (só preview)'
    bl_description = ('Adiciona a seleção à máscara V30 apenas após confirmação; '
                      'regista JSON SHA-locked e mantém SMD intacto')

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        global STATE, SEED, SELECTED, SELECTED_SCOPE
        try:
            if not SELECTED or SEED < 0:
                raise ValueError('V31_NADA_SELECIONADO')
            if SELECTED_SCOPE != context.scene.pt_v31_scope:
                raise ValueError('V31_MODO_ALTERADO_CLICAR_ATUALIZAR_SELECAO')
            env = _env()
            source = _source()
            if source.data.attributes.get(env.V29_MASK_ATTR) is None:
                raise ValueError('V31_PRIMEIRO_EXECUTAR_V30_COM_OCULTACAO_ATIVA')
            previous_mask = _existing_mask()
            if set(SELECTED) & previous_mask:
                raise ValueError('V31_SELECAO_JA_OCULTADA_REFAZER')
            asset, sha, count = _identity()
            key = _face_keys()[SEED]
            updated = accept(STATE, SELECTED, seed=SEED,
                             mode=context.scene.pt_v31_scope, material_key=key,
                             asset=asset, sha=sha, face_count=count)
            try:
                env._mask_v29_faces(sorted(previous_mask | set(SELECTED)))
                atomic_write_json(_path(),updated)
            except Exception:
                env._mask_v29_faces(sorted(previous_mask))
                raise
            STATE = updated
            n = len(SELECTED)
            SELECTED = []
            SEED = -1
            SELECTED_SCOPE = None
            v23._remove_collection(COLLECTION)
            print(f'PT_V31_MASK=PASS added={n} saved_extra={len(STATE["extra_faces"])} '
                  'source_unchanged=true game_unchanged=true publish=false',flush=True)
            self.report({'INFO'}, f'{n} faces ocultadas apenas na pré-visualização')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc))
            print(f'PT_V31_MASK=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V31Clear(bpy.types.Operator):
    bl_idname = 'pt_env.v31_clear'
    bl_label = 'Limpar seleção destacada'
    def execute(self, context):
        global SELECTED, SEED, SELECTED_SCOPE
        SELECTED = []
        SEED = -1
        SELECTED_SCOPE = None
        v23._remove_collection(COLLECTION)
        _source().hide_set(False)
        v25._hide_native_stage_sources()
        return {'FINISHED'}


class PT_OT_V31ResetMasks(bpy.types.Operator):
    bl_idname = 'pt_env.v31_reset_masks'
    bl_label = 'Reverter seleções V31'
    bl_description = 'Remove somente faces adicionais V31, mantendo a máscara original V30'
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self,event)

    def execute(self, context):
        global STATE, SELECTED, SEED, SELECTED_SCOPE
        try:
            original_mask = _existing_mask()
            extra = saved_extra_faces()
            asset,sha,count = _identity()
            restored = blank(asset,sha,count)
            try:
                if original_mask:
                    _env()._mask_v29_faces(sorted(original_mask - extra))
                atomic_write_json(_path(),restored)
            except Exception:
                if original_mask:
                    _env()._mask_v29_faces(sorted(original_mask))
                raise
            STATE = restored
            SELECTED = []
            SEED = -1
            SELECTED_SCOPE = None
            v23._remove_collection(COLLECTION)
            print(f'PT_V31_RESET=PASS removed_extra={len(extra)} source_unchanged=true',flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}


class PT_OT_V31AddTree(bpy.types.Operator):
    bl_idname = 'pt_env.v31_trial_instance'
    bl_label = 'Colocar árvore LOD0 aqui (experimental)'
    bl_description = ('Só quando a seleção representa uma árvore em falta. '
                      'Cria uma instância LOD0, com apoio estimado, sem aprovar ou publicar')

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self,event)

    def execute(self, context):
        try:
            if not SELECTED or context.scene.pt_v31_scope in {'MATERIAL_TODO','FOLHAGEM_TODA'}:
                raise ValueError('V31_INSTANCIA_REQUER_SELECAO_LOCAL')
            env = _env()
            col = v23._collection(EXTRA_COLLECTION)
            if len(col.objects) >= 8:
                raise ValueError('V31_MAXIMO_8_ARVORES_EXTRA_POR_ENSAIO')
            source = _source()
            mw = source.matrix_world
            coords = [mw @ source.data.vertices[v].co
                      for face_id in SELECTED for v in source.data.polygons[face_id].vertices]
            if not coords:
                raise ValueError('V31_SELECAO_VAZIA')
            lo = [min(v[k] for v in coords) for k in range(3)]
            hi = [max(v[k] for v in coords) for k in range(3)]
            anchor = [(.5*(lo[0]+hi[0])),(.5*(lo[1]+hi[1])),lo[2]]
            height = max(.4,hi[2]-lo[2])
            model = context.scene.pt_v26_model
            library, library_height = env._loaded_prepared(model,'LOD0')
            group = {'id':'V31_' + str(SEED),'anchor_view':anchor,'height_view':height}
            obj = env._instance(group,library,library_height,float(context.scene.pt_v26_scale),
                                output_col=col,asset=model,lod='LOD0')
            obj.name = f'PT_V31_EXTRA_LOD0_{SEED}'
            obj['pt_v31_trial_only'] = True
            obj['pt_v31_ground_certified'] = False
            if context.scene.pt_v30_wall_placement:
                try:
                    wall = wall_probe.build_wall_probe(source,_existing_mask() | set(SELECTED))
                    result = wall_probe.candidate_wall_contact(wall,source,
                                             {'faces':SELECTED,'trunk_faces':[]})
                    if result:
                        hit, normal, distance = result
                        obj.location = hit + normal*.04
                        direction = (normal + Vector((0.,0.,.18))).normalized()
                        obj.rotation_mode = 'QUATERNION'
                        obj.rotation_quaternion = Vector((0.,0.,1.)).rotation_difference(direction)
                        obj['pt_v31_wall_candidate'] = True
                except (ValueError,RuntimeError) as exc:
                    print(f'PT_V31_WALL=SKIPPED {exc}',flush=True)
            print(f'PT_V31_INSTANCE=PASS count={len(col.objects)} source_face={SEED} '
                  'position_unverified=true preview_only=true publish=false',flush=True)
            self.report({'WARNING'}, 'Instância extra: posição/parede estimada — ajustar visualmente')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc))
            print(f'PT_V31_INSTANCE=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_PT_EnvironmentV31(bpy.types.Panel):
    bl_label = 'V31 · Selecionar folhas restantes'
    bl_idname = 'PT_PT_ETERVALE_ENVIRONMENT_V31'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Etervale'
    bl_parent_id = 'PT_PT_ETERVALE_ENVIRONMENT_V26'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        lay = self.layout
        lay.label(text='Clicar em folhas antigas no mapa')
        lay.prop(context.scene,'pt_v31_only_suspects',text='Só materiais de folhagem')
        lay.operator('pt_env.v31_pick_remaining',text='1. Clicar na face restante',icon='EYEDROPPER')
        lay.prop(context.scene,'pt_v31_scope',text='Expandir')
        if context.scene.pt_v31_scope == 'ARVORE_LOCAL':
            lay.prop(context.scene,'pt_v31_radius',text='Raio local (vista)')
        lay.operator('pt_env.v31_expand',text='2. Mostrar seleção',icon='RESTRICT_SELECT_OFF')
        lay.label(text=f'Seleção: {len(SELECTED)} faces · ainda não ocultadas')
        if SEED >= 0:
            lay.label(text=f'Face original: {SEED}')
        lay.operator('pt_env.v31_confirm_mask',text='3. Ocultar selecionadas (reversível)',icon='HIDE_ON')
        lay.operator('pt_env.v31_trial_instance',text='Árvore extra LOD0 aqui',icon='OUTLINER_OB_EMPTY')
        lay.operator('pt_env.v31_clear',text='Limpar destaque',icon='LOOP_BACK')
        lay.separator()
        lay.label(text=f'Faces extra V31 guardadas: {len(STATE["extra_faces"]) if STATE else 0}')
        lay.operator('pt_env.v31_reset_masks',text='Reverter máscaras extra V31',icon='BACK')
        lay.label(text='Revisão visual · SMD intacto')


CLASSES = (PT_OT_V31Pick, PT_OT_V31Expand, PT_OT_V31ConfirmMask,
           PT_OT_V31Clear, PT_OT_V31ResetMasks, PT_OT_V31AddTree,
           PT_PT_EnvironmentV31)


def configure():
    global STATE,SEED,SELECTED,SELECTED_SCOPE
    asset,sha,count = _identity()
    path = _path()
    if path.exists():
        state = json.loads(path.read_text(encoding='utf-8'))
        check_state(state,asset=asset,sha=sha,face_count=count)
    else:
        state = blank(asset,sha,count)
    STATE = state
    SEED = -1
    SELECTED = []
    SELECTED_SCOPE = None
    scene = bpy.context.scene
    if not hasattr(bpy.types.Scene,'pt_v31_scope'):
        bpy.types.Scene.pt_v31_scope = EnumProperty(
            name='Expansão',items=[
                ('ILHA_MATERIAL','Ilha do material','Faces conectadas com a mesma textura'),
                ('ARVORE_LOCAL','Árvore local','Materiais de vegetação próximos à face'),
                ('MATERIAL_TODO','Textura inteira','Todas as ocorrências da textura, confirmar visualmente'),
                ('FOLHAGEM_TODA','Folhagem inteira','Todas as faces de materiais V22 ou confirmados V27')],
            default='ARVORE_LOCAL')
        bpy.types.Scene.pt_v31_radius = FloatProperty(name='Raio',default=3.,min=.15,max=12.)
        bpy.types.Scene.pt_v31_only_suspects = BoolProperty(name='Só vegetação',default=True)
    print(f'PT_V31=READY asset={asset} extra_faces={len(STATE["extra_faces"])} '
          f'output={path} publish=false',flush=True)
