"""V31: pick uncovered legacy foliage on the ONE V19 proxy and expand by material.

Only temporary inspection meshes, Geometry Nodes visibility and SHA-locked JSON.
No SMD/export/runtime writer; wide material operations need explicit confirmation.
"""
import json
import math
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from pt_asset_tool.residual_actions_v32 import (
    placement_from_bounds, validate_replacements, with_replacement, undo_last, MAX_EXTRA_TREES,
)
from pt_asset_tool.environment_residual_v31 import (
    MODES, expand, blank, check_state, accept,
)
from pt_asset_tool.residual_review_v31_1 import click_offsets, additions
from pt_asset_tool.stage072_texture_semantics_v27 import texture_identity
from pt_asset_tool.stage072_semantic_core import atomic_write_json
from pt_asset_tool.blender import stage072_tree_v23 as v23
from pt_asset_tool.blender import stage072_tree_group_v24 as v24
from pt_asset_tool.blender import stage072_textures_v27 as v27
from pt_asset_tool.blender import stage072_tree_review_v25 as v25
from pt_asset_tool.blender import environment_wall_probe_v30 as wall_probe

COLLECTION = 'PT_V31_FACES_RESTANTES_INSPECAO'
EXTRA_COLLECTION = 'PT_V31_ARVORES_EXTRA_LOD0_SO_PREVIEW'
GEOMETRY_CACHE = None
HEAVY_VISIBILITY = {}
HEAVY_COLLECTIONS = (
    'PT_V29_ARVORES_LOD0_TODAS_PREVIEW',
    'PT_V30_COBERTURA_COMPLETA_SO_PREVIEW',
    'PT_V28_INSTANCIAS_APROVADAS',
    'PT_V31_ARVORES_EXTRA_LOD0_SO_PREVIEW',
    'PT_V26_MODELO_COMPARACAO',
)
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


def _set_light_review(enabled):
    """Hide only disposable NEW tree instances; never touch the Stage mesh.

    Heavy LOD0 libraries stay loaded, so un-hiding is cheap and avoids creating
    a second high-poly mesh. Record existing visibility for accurate restore.
    """
    if enabled:
        for name in HEAVY_COLLECTIONS:
            col = bpy.data.collections.get(name)
            if col is not None and name not in HEAVY_VISIBILITY:
                HEAVY_VISIBILITY[name] = bool(col.hide_viewport)
                col.hide_viewport = True
    else:
        for name, was_hidden in list(HEAVY_VISIBILITY.items()):
            col = bpy.data.collections.get(name)
            if col is not None:
                col.hide_viewport = was_hidden
        HEAVY_VISIBILITY.clear()
    _source().hide_set(False)
    v25._hide_native_stage_sources()


def _preview_selection(selected):
    """Geometry-only highlight: no PBR materials, no UV copies, no Stage clone."""
    v23._remove_collection(COLLECTION)
    if not selected:
        return
    original = _source()
    source_mesh = original.data
    selected_vertices = sorted({int(i) for fid in selected
        for i in source_mesh.polygons[fid].vertices})
    remap = {old: new for new, old in enumerate(selected_vertices)}
    verts = [tuple(source_mesh.vertices[i].co) for i in selected_vertices]
    polygons = [tuple(remap[i] for i in source_mesh.polygons[fid].vertices)
                for fid in selected]
    # Material-free wire mesh is dramatically cheaper than copying all Stage
    # material slots, image textures, UV layers and vertex-colour attributes.
    mesh = bpy.data.meshes.new('PT_V31_1_DESTAQUE_LEVE_MESH')
    try:
        mesh.from_pydata(verts, [], polygons)
        mesh.update()
        ob = bpy.data.objects.new('PT_V31_SELECAO_LEVE', mesh)
        ob.matrix_world = original.matrix_world.copy()
        ob.display_type = 'WIRE'
        ob.color = (1., .65, .07, 1.)
        ob.show_in_front = True
        ob.hide_render = True
        ob['pt_v31_preview_only'] = True
        col = v23._collection(COLLECTION)
        col.objects.link(ob)
    except Exception:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    original.hide_set(False)
    v25._hide_native_stage_sources()


def _geometry():
    """Cache immutable Stage topology/centres within one Blender session."""
    global GEOMETRY_CACHE
    src = _source()
    ptr = src.data.as_pointer()
    key = (ptr, len(src.data.polygons), len(src.data.vertices))
    if GEOMETRY_CACHE is None or GEOMETRY_CACHE[0] != key:
        m = src.data
        mw = src.matrix_world
        GEOMETRY_CACHE = (key,
            [tuple(int(v) for v in p.vertices) for p in m.polygons],
            [tuple(mw @ p.center) for p in m.polygons],
            _face_keys())
    return GEOMETRY_CACHE[1:]


def _append_mask_without_node_rebuild(env, selected):
    """Set Boolean face attributes in place; do not reallocate Geometry Nodes."""
    source = _source()
    attr = source.data.attributes.get(env.V29_MASK_ATTR)
    if attr is None or attr.domain != 'FACE' or attr.data_type != 'BOOLEAN':
        raise ValueError('V31_1_MASCARA_INCOMPATIVEL')
    if not any(mod.name == env.V29_MASK_MOD and mod.type == 'NODES'
               for mod in source.modifiers):
        raise ValueError('V31_1_MODIFICADOR_MASCARA_AUSENTE')
    for face_id in selected:
        attr.data[face_id].value = True
    source.data.update()
    source.update_tag(refresh={'DATA'})


def _rollback_mask_append(env, selected):
    source = _source()
    attr = source.data.attributes.get(env.V29_MASK_ATTR)
    if attr is not None:
        for face_id in selected:
            attr.data[face_id].value = False
        source.data.update()
        source.update_tag(refresh={'DATA'})


def _expand_from_seed(scene):
    global SELECTED, SELECTED_SCOPE
    if SEED < 0:
        raise ValueError('V31_CLICAR_PRIMEIRO_NUMA_FACE_RESTANTE')
    source = _source()
    faces, centres, keys = _geometry()
    hidden = _existing_mask()
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
            if context.scene.pt_v31_auto_light:
                _set_light_review(True)
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
            idx = None
            used_offset = (0, 0)
            # Pixel tolerance means small leaf cards can be picked without
            # zooming in repeatedly. Centre ray always wins on a direct hit.
            for dx, dy in click_offsets(int(context.scene.pt_v31_snap_px)):
                x, y = mx + dx, my + dy
                if not (0 <= x < r.width and 0 <= y < r.height):
                    continue
                coord = (x, y)
                origin = view3d_utils.region_2d_to_origin_3d(r,self.rv3d,coord)
                direction = view3d_utils.region_2d_to_vector_3d(r,self.rv3d,coord)
                hit, normal, candidate_idx, distance = self.bvh.ray_cast(origin,direction,10000.)
                if hit is not None and candidate_idx is not None:
                    idx = candidate_idx
                    used_offset = (dx, dy)
                    break
            if idx is None:
                raise ValueError('V31_NENHUMA_FACE_PERTO_CURSOR_DIMINUIR_ZOOM_OU_DESMARCAR_FILTRO')
            SEED = self.face_ids[idx]
            selected = _expand_from_seed(context.scene)
            source = _source()
            mat = source.data.materials[source.data.polygons[SEED].material_index]
            print(f'PT_V31_PICK=PASS seed={SEED} material={mat.name if mat else "NONE"} '
                  f'scope={context.scene.pt_v31_scope} faces={len(selected)} snap_offset={used_offset} publish=false', flush=True)
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
            additions(previous_mask, SELECTED, count)
            # Persist before GPU/depsgraph refresh. A Blender crash after this
            # point cannot lose accepted selections: V30 reapplies JSON on open.
            atomic_write_json(_path(), updated)
            try:
                _append_mask_without_node_rebuild(env, SELECTED)
            except Exception:
                _rollback_mask_append(env, SELECTED)
                atomic_write_json(_path(), STATE)
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


def _v32_selected_position(model, sha, scale):
    """Only a selected *local* piece may seed one new tree, never whole material."""
    if not SELECTED or SEED < 0 or SELECTED_SCOPE not in {'ARVORE_LOCAL', 'ILHA_MATERIAL'}:
        raise ValueError('V32_SUBSTITUIR_REQUER_SELECAO_LOCAL')
    src = _source()
    mw = src.matrix_world
    pts = (tuple(mw @ src.data.vertices[int(vid)].co)
           for fid in SELECTED for vid in src.data.polygons[fid].vertices)
    return placement_from_bounds(pts, seed=SEED, face_count=len(src.data.polygons),
                                 model=model, model_sha=sha, scale=scale)


def restore_v32_replacements():
    """Called by V30 after rebuilding its global preview and old-face mask."""
    if STATE is None:
        return 0
    records = validate_replacements(STATE, face_count=len(_source().data.polygons))
    if not records:
        return 0
    env = _env()
    col = v23._collection(EXTRA_COLLECTION)
    restored = 0
    for rec in records:
        try:
            model = rec['model']
            # Must still match the exact downloaded original and prepared LOD.
            models = {item.name:item for item in env.model_entries(env._library_root())}
            if model not in models or env.sha256_file(Path(models[model].path)) != rec['model_sha256']:
                raise ValueError('V32_MODELO_FOI_ALTERADO')
            library, model_height = env._loaded_prepared(model, 'LOD0')
            group = {'id':f'V32_{rec["seed"]}', 'anchor_view':rec['anchor_view'],
                     'height_view':rec['height_view']}
            ob = env._instance(group, library, model_height, rec['scale'],
                               output_col=col, asset=model, lod='LOD0')
            ob.name = f'PT_V32_ARVORE_SUBSTITUTA_{rec["seed"]}'
            ob['pt_v32_saved_preview'] = True
            restored += 1
        except (ValueError, RuntimeError, OSError) as exc:
            print(f'PT_V32_RESTORE=SKIP seed={rec["seed"]} reason={exc}', flush=True)
    print(f'PT_V32_RESTORE=PASS restored={restored} saved={len(records)} '
          'preview_only=true publish=false', flush=True)
    return restored


def _v32_commit(context, *, replace_tree):
    """Persist choice atomically; mask and instance are only viewport changes."""
    global STATE, SELECTED, SEED, SELECTED_SCOPE
    if STATE is None or not SELECTED or SEED < 0:
        raise ValueError('V32_SELECIONAR_PRIMEIRO')
    scene = context.scene
    if SELECTED_SCOPE != scene.pt_v31_scope:
        raise ValueError('V32_ATUALIZAR_SELECAO_APOS_ALTERAR_ALCANCE')
    env = _env()
    src = _source()
    if src.data.attributes.get(env.V29_MASK_ATTR) is None:
        raise ValueError('V32_INICIAR_TESTE_GLOBAL_PRIMEIRO')
    previous_mask = _existing_mask()
    additions(previous_mask, SELECTED, len(src.data.polygons))
    asset, sha, count = _identity()
    updated = accept(STATE, SELECTED, seed=SEED, mode=SELECTED_SCOPE,
                     material_key=_face_keys()[SEED], asset=asset, sha=sha, face_count=count)
    instance = None
    if replace_tree:
        model = scene.pt_v26_model
        models = {item.name:item for item in env.model_entries(env._library_root())}
        if model not in models:
            raise ValueError('V32_ESCOLHER_MODELO_ARVORE')
        digest = env.sha256_file(Path(models[model].path))
        library, model_height = env._loaded_prepared(model, 'LOD0')
        placement = _v32_selected_position(model, digest, float(scene.pt_v26_scale))
        updated = with_replacement(updated, placement, face_count=count)
        col = v23._collection(EXTRA_COLLECTION)
        group = {'id':f'V32_{SEED}', 'anchor_view':placement['anchor_view'],
                 'height_view':placement['height_view']}
        instance = env._instance(group, library, model_height, placement['scale'],
                                 output_col=col, asset=model, lod='LOD0')
        instance.name = f'PT_V32_ARVORE_SUBSTITUTA_{SEED}'
        instance['pt_v32_saved_preview'] = True
        instance['pt_v32_ground_certified'] = False
    updated['selections'][-1]['v32_action'] = ('REPLACE_TREE' if replace_tree else 'HIDE_LEAVES')
    updated['selections'][-1]['v32_faces'] = list(SELECTED)
    try:
        # One write holds BOTH the faces and replacement instructions.
        atomic_write_json(_path(), updated)
        _append_mask_without_node_rebuild(env, SELECTED)
    except Exception:
        _rollback_mask_append(env, SELECTED)
        atomic_write_json(_path(), STATE)
        if instance is not None:
            bpy.data.objects.remove(instance, do_unlink=True)
        raise
    n = len(SELECTED)
    STATE = updated
    SELECTED = []
    SEED = -1
    SELECTED_SCOPE = None
    v23._remove_collection(COLLECTION)
    if replace_tree:
        _set_light_review(False)
    print(f'PT_V32_ACTION=PASS action={"REPLACE_TREE" if replace_tree else "HIDE_LEAVES"} '
          f'faces={n} saved_trees={len(STATE.get("v32_replacements",[]))} '
          'source_unchanged=true publish=false', flush=True)
    return n


class PT_OT_V32HideLeaves(bpy.types.Operator):
    bl_idname = 'pt_env.v32_hide_leaves'
    bl_label = 'Só ocultar folhas'
    bl_description = 'Oculta a região selecionada, SEM criar outra árvore (reversível)'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            n = _v32_commit(context, replace_tree=False)
            self.report({'INFO'}, f'{n} faces antigas ocultadas; nenhuma árvore nova')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            print(f'PT_V32_ACTION=FAIL HIDE_LEAVES {type(exc).__name__}:{exc}', flush=True)
            return {'CANCELLED'}


class PT_OT_V32ReplaceTree(bpy.types.Operator):
    bl_idname = 'pt_env.v32_replace_tree'
    bl_label = 'Substituir por árvore LOD0'
    bl_description = 'Esconde faces selecionadas e guarda UMA instância do modelo escolhido'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            n = _v32_commit(context, replace_tree=True)
            self.report({'WARNING'}, f'{n} faces substituídas visualmente; implantação por confirmar')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            print(f'PT_V32_ACTION=FAIL REPLACE_TREE {type(exc).__name__}:{exc}', flush=True)
            return {'CANCELLED'}


class PT_OT_V32Undo(bpy.types.Operator):
    bl_idname = 'pt_env.v32_undo'
    bl_label = 'Desfazer última escolha'
    bl_description = 'Desfaz somente a última ação V32; preserva todas as seleções V31 anteriores'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        global STATE, SELECTED, SEED, SELECTED_SCOPE
        try:
            if STATE is None:
                raise ValueError('V32_SEM_ESTADO')
            env = _env()
            if _source().data.attributes.get(env.V29_MASK_ATTR) is None:
                raise ValueError('V32_INICIAR_TESTE_GLOBAL_PRIMEIRO')
            updated, faces, action, seed = undo_last(STATE, face_count=len(_source().data.polygons))
            atomic_write_json(_path(), updated)
            try:
                _rollback_mask_append(env, faces)
            except Exception:
                atomic_write_json(_path(), STATE)
                _append_mask_without_node_rebuild(env, faces)
                raise
            STATE = updated
            if action == 'REPLACE_TREE':
                ob = bpy.data.objects.get(f'PT_V32_ARVORE_SUBSTITUTA_{seed}')
                if ob is not None and ob.get('pt_v32_saved_preview'):
                    bpy.data.objects.remove(ob, do_unlink=True)
            SELECTED = []
            SEED = -1
            SELECTED_SCOPE = None
            v23._remove_collection(COLLECTION)
            print(f'PT_V32_UNDO=PASS action={action} faces={len(faces)} preview_only=true', flush=True)
            self.report({'INFO'}, 'Última decisão desfeita; classificações anteriores preservadas')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            print(f'PT_V32_UNDO=FAIL {type(exc).__name__}:{exc}', flush=True)
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
            v23._remove_collection(EXTRA_COLLECTION)  # Includes saved V32 previews
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


class PT_OT_V31LightView(bpy.types.Operator):
    bl_idname = 'pt_env.v31_light_review'
    bl_label = 'Alternar revisão leve'
    bl_description = 'Oculta/mostra somente instâncias 3D modernas pesadas; mantém máscaras e Stage'

    def execute(self, context):
        try:
            light = not bool(HEAVY_VISIBILITY)
            _set_light_review(light)
            print(f'PT_V31_1_LIGHT=PASS heavy_instances_hidden={str(light).lower()} '
                  'source_unchanged=true publish=false', flush=True)
            self.report({'INFO'}, 'Árvores 3D ocultas para selecionar' if light
                        else 'Árvores 3D mostradas novamente')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class PT_PT_EnvironmentV31(bpy.types.Panel):
    bl_label = 'V31 · Selecionar folhas restantes'
    bl_idname = 'PT_PT_ETERVALE_ENVIRONMENT_V31'
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
        lay.label(text='Clicar em folhas antigas no mapa')
        lay.prop(context.scene,'pt_v31_only_suspects',text='Só materiais de folhagem')
        lay.prop(context.scene,'pt_v31_auto_light',text='Ocultar 3D novo ao selecionar')
        lay.prop(context.scene,'pt_v31_snap_px',text='Tolerância clique (px)')
        lay.operator('pt_env.v31_light_review',
            text=('Mostrar árvores 3D novamente' if HEAVY_VISIBILITY else
                  'Ocultar árvores 3D (modo leve)'),icon='HIDE_OFF' if HEAVY_VISIBILITY else 'HIDE_ON')
        lay.operator('pt_env.v31_pick_remaining',text='1. Clicar perto da face restante',icon='EYEDROPPER')
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
           PT_OT_V31LightView, PT_OT_V32HideLeaves, PT_OT_V32ReplaceTree, PT_OT_V32Undo,
           PT_PT_EnvironmentV31)


def configure():
    global STATE,SEED,SELECTED,SELECTED_SCOPE,GEOMETRY_CACHE
    HEAVY_VISIBILITY.clear()
    GEOMETRY_CACHE = None
    asset,sha,count = _identity()
    path = _path()
    if path.exists():
        state = json.loads(path.read_text(encoding='utf-8'))
        check_state(state,asset=asset,sha=sha,face_count=count)
    else:
        state = blank(asset,sha,count)
    validate_replacements(state, face_count=count)
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
    if not hasattr(bpy.types.Scene, 'pt_v31_auto_light'):
        bpy.types.Scene.pt_v31_auto_light = BoolProperty(
            name='Revisão leve automática', default=True,
            description='Oculta temporariamente árvores LOD0 enquanto selecionas folhas antigas')
    if not hasattr(bpy.types.Scene, 'pt_v31_snap_px'):
        bpy.types.Scene.pt_v31_snap_px = IntProperty(
            name='Margem do clique', min=0, max=20, default=10,
            description='Procura a folha mais próxima do clique; 0 exige acertar exatamente')
    print(f'PT_V31_1=READY asset={asset} extra_faces={len(STATE["extra_faces"])} '
          f'output={path} publish=false',flush=True)
